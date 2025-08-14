import logging
import aiohttp
import base64
from PIL import Image, ImageOps
import os
from urllib.request import urlopen
from copy import deepcopy
import paho.mqtt.client as mqtt
import json
from uuid import uuid4
import asyncio
from datetime import ( datetime, timedelta, UTC )
import ssl

from homeassistant.core import HomeAssistant
from homeassistant.helpers import translation
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components import persistent_notification
from homeassistant.util import dt

from .base import StellantisVehicleCoordinator
from .otp.otp import Otp, save_otp, load_otp, ConfigException
from .utils import get_datetime

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    FIELD_COUNTRY_CODE,
    MOBILE_APPS,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    OAUTH_AUTHORIZE_QUERY_PARAMS,
    OAUTH_GET_TOKEN_QUERY_PARAMS,
    OAUTH_REFRESH_TOKEN_QUERY_PARAMS,
    OAUTH_TOKEN_HEADERS,
    CAR_API_VEHICLES_URL,
    CLIENT_ID_QUERY_PARAMS,
    CAR_API_HEADERS,
    CAR_API_GET_VEHICLE_STATUS_URL,
    GET_OTP_URL,
    GET_OTP_HEADERS,
    GET_MQTT_TOKEN_URL,
    MQTT_SERVER,
    MQTT_RESP_TOPIC,
    MQTT_EVENT_TOPIC,
    MQTT_REQ_TOPIC,
    GET_USER_INFO_URL,
    CAR_API_GET_VEHICLE_TRIPS_URL,
    UPDATE_INTERVAL,
    IMAGE_PATH,
    MQTT_REFRESH_TOKEN_TTL,
    OTP_FILENAME
)

_LOGGER = logging.getLogger(__name__)

def _create_ssl_context() -> ssl.SSLContext:
    """Create a SSL context for the MQTT connection."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_default_certs()
    return context

_SSL_CONTEXT = _create_ssl_context()

class StellantisBase:
    def __init__(self, hass:HomeAssistant) -> None:
        self._hass = hass
        self._config = {}
        self._session = None
        self.otp = None

    def start_session(self):
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def close_session(self):
        if not self._session or self._session.closed:
            return
        await self._session.close()
        self._session = None

    def set_mobile_app(self, mobile_app, country_code):
        if mobile_app in MOBILE_APPS:
            app_data = deepcopy(MOBILE_APPS[mobile_app])
            del app_data["configs"]
            app_data.update(MOBILE_APPS[mobile_app]["configs"][country_code])
            self.save_config(app_data)
            self.save_config({
                "basic_token": base64.b64encode(bytes(self._config["client_id"] + ":" + self._config["client_secret"], 'utf-8')).decode('utf-8'),
                "culture": country_code.lower()
            })
            _LOGGER.debug(self._config)

    def save_config(self, data):
        for key in data:
            self._config[key] = data[key]
            if key == FIELD_MOBILE_APP and FIELD_COUNTRY_CODE in self._config:
                self.set_mobile_app(data[key], self._config[FIELD_COUNTRY_CODE])
            elif key == FIELD_COUNTRY_CODE and FIELD_MOBILE_APP in self._config:
                self.set_mobile_app(self._config[FIELD_MOBILE_APP], data[key])

    def get_config(self, key):
        if key in self._config:
            return self._config[key]
        return None

    def replace_placeholders(self, string, vehicle=None):
        if vehicle is None:
            vehicle = []
        for key in vehicle:
            string = string.replace("{#"+key+"#}", str(vehicle[key]))
        for key, value in self._config.items():
            string = string.replace("{#" + key + "#}", str(value))
        return string

    def apply_headers_params(self, headers):
        new_headers = {}
        for key in headers:
            new_headers[key] = self.replace_placeholders(headers[key])
        return new_headers

    def apply_query_params(self, url, params, vehicle=None):
        if vehicle is None:
            vehicle = []
        query_params = []
        for key in params:
            value = params[key]
            query_params.append(f"{key}={value}")
        query_params = '&'.join(query_params)
        return self.replace_placeholders(f"{url}?{query_params}", vehicle)

    async def make_http_request(self, url, method='GET', headers=None, params=None, json=None, data=None):
        _LOGGER.debug("---------- START make_http_request")
        self.start_session()
        try:
            async with self._session.request(method, url, params=params, json=json, data=data, headers=headers) as resp:
                result = {}
                error = None
                if method != "DELETE" and (await resp.text()):
                    result = await resp.json()
                if not str(resp.status).startswith("20"):
                    _LOGGER.debug(f"{method} request error {str(resp.status)}: {resp.url}")
                    _LOGGER.debug(headers)
                    _LOGGER.debug(params)
                    _LOGGER.debug(json)
                    _LOGGER.debug(data)
                    _LOGGER.debug(result)
                    if "httpMessage" in result and "moreInformation" in result:
                        error = result["httpMessage"] + " - " + result["moreInformation"]
                    elif "error" in result and "error_description" in result:
                        error = result["error"] + " - " + result["error_description"]
                    elif "message" in result and "code" in result:
                        error = result["message"] + " - " + str(result["code"])

                if str(resp.status) == "404" and str(result["code"]) == "40400":
                    _LOGGER.error(error) # "Not Found: We didn't find the status for this vehicle. - 40400"
                    result = {} # Clear result on error to avoid returning error details in the result
                    return result
                elif str(resp.status) == "400" and result.get("error", None) == "invalid_grant":
                    await self.close_session()
                    # Token expiration
                    raise ConfigEntryAuthFailed(error)
                if error is not None:
                    await self.close_session()
                    # Generic error
                    raise Exception(error)
                _LOGGER.debug("---------- END make_http_request")
                return result
        except ConfigEntryAuthFailed as e:
            # Logged only as a warning, the exception could be handled by the calling function
            _LOGGER.warning("Authentication failed during HTTP request: %s", e)
            raise
        except Exception as e:
            _LOGGER.error("Unexpected error during HTTP request: %s", e)
            raise

    def do_async(self, async_func):
        return asyncio.run_coroutine_threadsafe(async_func, self._hass.loop).result()

    async def hass_notify(self, translation_key):
        """Create a persistent notification."""
        if hasattr(self, '_entry') and not self.get_stored_config("switch_notifications"):
            return

        translations = await translation.async_get_translations(self._hass, self._hass.config.language, "common", {DOMAIN})
        notification_title = "Stellantis Vehicles"
        if translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None):
            notification_title = notification_title + " - " + str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None))
        notification_message = str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_message", None))
        persistent_notification.async_create(
            self._hass,
            notification_message,
            title=notification_title,
            notification_id=str(uuid4())
        )


class StellantisOauth(StellantisBase):
    def get_oauth_url(self):
        return self.apply_query_params(OAUTH_AUTHORIZE_URL, OAUTH_AUTHORIZE_QUERY_PARAMS)

    async def get_access_token(self):
        _LOGGER.debug("---------- START get_access_token")
        url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_GET_TOKEN_QUERY_PARAMS)
        headers = self.apply_headers_params(OAUTH_TOKEN_HEADERS)
        token_request = await self.make_http_request(url, 'POST', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(token_request)
        _LOGGER.debug("---------- END get_access_token")
        return token_request

    async def get_user_info(self):
        _LOGGER.debug("---------- START get_user_info")
        url = self.apply_query_params(GET_USER_INFO_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_headers_params(GET_OTP_HEADERS)
        headers["x-transaction-id"] = "1234"
        user_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(user_request)
        _LOGGER.debug("---------- END get_user_info")
        return user_request

    def new_otp(self, sms_code, pin_code):
        try:
            self.otp = Otp("bb8e981582b0f31353108fb020bead1c", device_id=str(self.get_config("access_token")[:16]))
            self.otp.smsCode = sms_code
            self.otp.codepin = pin_code
            if self.otp.activation_start():
                finalyze = self.otp.activation_finalyze()
                if finalyze != 0:
                    raise Exception(finalyze)
        except Exception as e:
            _LOGGER.error(str(e))
            raise Exception(str(e))

    async def get_otp_sms(self):
        _LOGGER.debug("---------- START get_otp_sms")
        url = self.apply_query_params(GET_OTP_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_headers_params(GET_OTP_HEADERS)
        sms_request = await self.make_http_request(url, 'POST', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(sms_request)
        _LOGGER.debug("---------- END get_otp_sms")
        return sms_request

    async def get_mqtt_access_token(self):
        _LOGGER.debug("---------- START get_mqtt_access_token")
        url = self.apply_query_params(GET_MQTT_TOKEN_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_headers_params(GET_OTP_HEADERS)
        try:
            otp_code = await self.get_otp_code()
            token_request = await self.make_http_request(url, 'POST', headers, None, {"grant_type": "password", "password": otp_code})
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(token_request)
        except ConfigException as e:
            _LOGGER.error(str(e))
            raise ConfigEntryAuthFailed(str(e))
        except Exception as e:
            _LOGGER.error(str(e))
            raise Exception(str(e))
        _LOGGER.debug("---------- END get_mqtt_access_token")
        return token_request

    async def get_otp_code(self):
        _LOGGER.debug("---------- START get_otp_code")
        # Check if storage path exists, if not create it
        hass_config_path = self._hass.config.path()
        storage_path = os.path.join(hass_config_path, ".storage", DOMAIN)
        if not os.path.isdir(storage_path):
            os.mkdir(storage_path)
        # Generate OTP file path from customer_id
        otp_file_path = os.path.join(storage_path, OTP_FILENAME)
        otp_file_path = otp_file_path.replace("{#customer_id#}", self.get_config("customer_id"))
        # Check if OTP object is already loaded, if not load it
        if self.otp is None:
            if not os.path.isfile(otp_file_path):
                _LOGGER.error(f"Error: OTP file '{otp_file_path}' not found, please reauthenticate")
                raise ConfigEntryAuthFailed(f"OTP file not found, please reauthenticate")
            self.otp = await self._hass.async_add_executor_job(load_otp, otp_file_path)
        # Get the OTP code using OTP object. It seems there is a rate limit of 6 requests per 24h
        otp_code = await self._hass.async_add_executor_job(self.otp.get_otp_code)
        if otp_code is None:
            _LOGGER.error("Error: OTP code is empty, please reauthenticate")
            raise ConfigEntryAuthFailed("OTP code is empty, please reauthenticate")
        # Save updated OTP object to file
        await self._hass.async_add_executor_job(save_otp, self.otp, otp_file_path)
        _LOGGER.debug("---------- END get_otp_code")
        return otp_code


class StellantisVehicles(StellantisOauth):
    def __init__(self, hass:HomeAssistant) -> None:
        super().__init__(hass)

        self._refresh_interval = UPDATE_INTERVAL
        self._entry = None
        self._coordinator_dict  = {}
        self._vehicles = []
        self._callback_id = None
        self._mqtt = None
        self._mqtt_last_request = None
        self._lock_refresh_token = asyncio.Lock()
        self._lock_refresh_mqtt_token = asyncio.Lock()

    def set_entry(self, entry):
        self._entry = entry

    def update_stored_config(self, config, value):
        data = self._entry.data
        new_data = {}
        for key in data:
            new_data[key] = deepcopy(data[key])
        if config not in new_data:
            new_data[config] = None
        new_data[config] = value
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)
        self._hass.config_entries._async_schedule_save()

    def get_stored_config(self, config):
        if config in self._entry.data:
            return self._entry.data[config]
        return False

    async def async_get_coordinator_by_vin(self, vin):
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        return None

    async def async_get_coordinator(self, vehicle):
        vin = vehicle["vin"]
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        translations = await translation.async_get_translations(self._hass, self._hass.config.language, "entity", {DOMAIN})
        coordinator = StellantisVehicleCoordinator(self._hass, self._config, vehicle, self, translations)
        self._coordinator_dict[vin] = coordinator
        return coordinator

    async def resize_and_save_picture(self, url, vin):
        public_path = self._hass.config.path("www")
        customer_id = self.get_config("customer_id")

        if not os.path.isdir(public_path):
            _LOGGER.warning("Folder \"www\" not found in configuration folder")
            return url

        stellantis_path = f"{public_path}/{IMAGE_PATH}"
        entry_path = f"{stellantis_path}/{customer_id}"
        if not os.path.isdir(entry_path):
            os.makedirs(entry_path, exist_ok=True)

        image_path = f"{entry_path}/{vin}.png"
        image_url = image_path.replace(public_path, "/local")
        # Migrate to new file structure - can be removed in future versions
        old_image_path = f"{stellantis_path}/{vin}.png"
        if os.path.isfile(old_image_path):
            _LOGGER.debug(f"Migrating image file: {old_image_path} -> {image_path}")
            os.rename(old_image_path, image_path)
        # END Migrate to new file structure
        if os.path.isfile(image_path):
            return image_url

        image = await self._hass.async_add_executor_job(urlopen, url)
        with Image.open(image) as im:
            im = ImageOps.pad(im, (400, 400))
        im.save(image_path)
        return image_url

    async def refresh_token(self):
        _LOGGER.debug("---------- START refresh_token")
        # to prevent concurrent updates
        async with self._lock_refresh_token:
            token_expiry = datetime.fromisoformat(self.get_config("expires_in"))
            _LOGGER.debug(f"------------- access_token valid until: {token_expiry}")
            if token_expiry < (get_datetime() + timedelta(seconds=self._refresh_interval)):
                url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_REFRESH_TOKEN_QUERY_PARAMS)
                headers = self.apply_headers_params(OAUTH_TOKEN_HEADERS)
                token_request = await self.make_http_request(url, 'POST', headers)
                _LOGGER.debug(url)
                _LOGGER.debug(headers)
                _LOGGER.debug(token_request)
                new_config = {
                    "access_token": token_request["access_token"],
                    "refresh_token": token_request["refresh_token"],
                    "expires_in": (get_datetime() + timedelta(seconds=int(token_request["expires_in"]))).isoformat()
                }
                self.save_config(new_config)
                self.update_stored_config("access_token", new_config["access_token"])
                self.update_stored_config("refresh_token", new_config["refresh_token"])
                self.update_stored_config("expires_in", new_config["expires_in"])
        _LOGGER.debug("---------- END refresh_token")

    async def get_user_vehicles(self):
        _LOGGER.debug("---------- START get_user_vehicles")
        if not self._vehicles:
            url = self.apply_query_params(CAR_API_VEHICLES_URL, CLIENT_ID_QUERY_PARAMS)
            headers = self.apply_headers_params(CAR_API_HEADERS)
            vehicles_request = await self.make_http_request(url, 'GET', headers)
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(vehicles_request)
            if "_embedded" in vehicles_request:
                if "vehicles" in vehicles_request["_embedded"]:
                    for vehicle in vehicles_request["_embedded"]["vehicles"]:
                        vehicle_data = {
                            "vehicle_id": vehicle["id"],
                            "vin": vehicle["vin"],
                            "type": vehicle["motorization"]
                        }
                        try:
                            picture = await self.resize_and_save_picture(vehicle["pictures"][0], vehicle["vin"])
                            vehicle_data["picture"] = picture
                        except Exception as e:
                            _LOGGER.error(str(e))
                        self._vehicles.append(vehicle_data)
                else:
                    _LOGGER.error("No vehicles found in vehicles_request['_embedded']")
            else:
                _LOGGER.error("No _embedded found in vehicles_request")
        _LOGGER.debug("---------- END get_user_vehicles")
        return self._vehicles

    async def get_vehicle_status(self, vehicle):
        _LOGGER.debug("---------- START get_vehicle_status")
        # Ensure that the MQTT client is connected
        if self._mqtt is None or self._mqtt.is_connected() is False:
            _LOGGER.debug("------------ MQTT client is not connected, try to connect it")
            await self.connect_mqtt()
        # Fetch the vehicle status using the API
        url = self.apply_query_params(CAR_API_GET_VEHICLE_STATUS_URL, CLIENT_ID_QUERY_PARAMS, vehicle)
        headers = self.apply_headers_params(CAR_API_HEADERS)
        vehicle_status_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(vehicle_status_request)
        _LOGGER.debug("---------- END get_vehicle_status")
        return vehicle_status_request

    async def get_vehicle_last_trip(self, vehicle, page_token = False):
        _LOGGER.debug("---------- START get_vehicle_last_trip")
        url = self.apply_query_params(CAR_API_GET_VEHICLE_TRIPS_URL, CLIENT_ID_QUERY_PARAMS, vehicle)
        headers = self.apply_headers_params(CAR_API_HEADERS)
        limit_date = (get_datetime() - timedelta(days=1)).isoformat()
        limit_date = limit_date.split(".")[0] + "+" + limit_date.split(".")[1].split("+")[1]
        url = url + "&timestamps=" + limit_date + "/&distance=0.1-"
        if page_token:
            url = url + "&pageToken=" + page_token
        vehicle_trips_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(vehicle_trips_request)
        if int(vehicle_trips_request["total"]) > 60 and not page_token:
            last_page_url = vehicle_trips_request["_links"]["last"]["href"]
            page_token = last_page_url.split("pageToken=")[1]
            _LOGGER.debug("---------- END get_vehicle_last_trip")
            return await self.get_vehicle_last_trip(page_token)
        _LOGGER.debug("---------- END get_vehicle_last_trip")
        return vehicle_trips_request

#     async def get_vehicle_trips(self, page_token=False):
#         _LOGGER.debug("---------- START get_vehicle_trips")
#         url = self.apply_query_params(CAR_API_GET_VEHICLE_TRIPS_URL, CLIENT_ID_QUERY_PARAMS)
#         headers = self.apply_headers_params(CAR_API_HEADERS)
#         url = url + "&distance=0.1-"
#         if page_token:
#             url = url + "&pageToken=" + page_token
#         vehicle_trips_request = await self.make_http_request(url, 'GET', headers)
#         _LOGGER.debug(url)
#         _LOGGER.debug(headers)
#         _LOGGER.debug(vehicle_trips_request)
#         _LOGGER.debug("---------- END get_vehicle_trips")
#         return vehicle_trips_request

    async def refresh_mqtt_token(self, force=False):
        _LOGGER.debug("---------- START refresh_mqtt_token")
        # Ensure that the MQTT token refresh process is thread-safe
        async with self._lock_refresh_mqtt_token:
            try:
                mqtt_config = self.get_config("mqtt")
                token_expiry = datetime.fromisoformat(mqtt_config["expires_in"])
                _LOGGER.debug(f"------------- mqtt access_token valid until: {token_expiry}")
                # Check if the token is expired or if a forced refresh is required
                if (token_expiry < (get_datetime() + timedelta(seconds=self._refresh_interval))) or force:
                    # Fetch a new MQTT token and update the configuration
                    token_request = await self._fetch_new_mqtt_token(mqtt_config)
                    _LOGGER.debug(token_request)
                    await self._update_mqtt_config(mqtt_config, token_request)
            except ConfigEntryAuthFailed as e:
                try:
                    _LOGGER.debug("------------- Attempt to refresh MQTT token failed, trying to refresh only the access_token (using refresh_token)")
                    token_request = await self._fetch_new_mqtt_token(mqtt_config, access_token_only=True)
                    _LOGGER.debug(token_request)
                    await self._update_mqtt_config(mqtt_config, token_request)
                except ConfigEntryAuthFailed as ee:
                    _LOGGER.error("------------- Attempt to refresh MQTT access token only failed as well. Error: %s", ee)
                    # If refreshing access_token only attempt fails as well, raise an exception
                    raise
            except Exception as e:
                _LOGGER.error("Unexpected error during MQTT token refresh: %s", e)
                raise
        _LOGGER.debug("---------- END refresh_mqtt_token")

    async def _fetch_new_mqtt_token(self, mqtt_config, access_token_only=False):
        """Fetch a new MQTT token using either the refresh token or an OTP code."""
        # Prepare the request URL and headers for fetching a new MQTT token
        url = self.apply_query_params(GET_MQTT_TOKEN_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_headers_params(GET_OTP_HEADERS)
        # Check if the refresh token is about to expire and use OTP if necessary
        refresh_token_almost_expired = "refresh_token_expires_at" not in mqtt_config or datetime.fromisoformat(mqtt_config["refresh_token_expires_at"]) < (get_datetime() + timedelta(seconds=self._refresh_interval))
        if refresh_token_almost_expired and not access_token_only:
            _LOGGER.debug("------------- mqtt refresh_token is almost expired, use OTP code to get a new one")
            # It seems there is a rate limit of 6 requests per 24h
            # Request new tokens (access_token and refresh_token) using the OTP code
            otp_code = await self.get_otp_code()
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            return await self.make_http_request(url, 'POST', headers, None, {"grant_type": "password", "password": otp_code})
        else:
            # Request a new access token using the refresh token
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            return await self.make_http_request(url, 'POST', headers, None, {"grant_type": "refresh_token", "refresh_token": mqtt_config["refresh_token"]})

    async def _update_mqtt_config(self, mqtt_config, token_request):
        """Update the MQTT configuration with the new token details."""
        if "access_token" in token_request:
            _LOGGER.debug("------------- refreshing mqtt access_token:")
            _LOGGER.debug(f"-------------- old access_token: {mqtt_config['access_token']}")
            _LOGGER.debug(f"-------------- new access_token: {token_request['access_token']}")
            # Update the access token and its expiration time
            mqtt_config["access_token"] = token_request["access_token"]
            mqtt_config["expires_in"] = (get_datetime() + timedelta(seconds=int(token_request["expires_in"]))).isoformat()
            # Update the refresh token if provided in the response
            if "refresh_token" in token_request:
                _LOGGER.debug("------------- refreshing mqtt refresh_token:")
                _LOGGER.debug(f"-------------- old refresh_token: {mqtt_config['refresh_token']}")
                _LOGGER.debug(f"-------------- new refresh_token: {token_request['refresh_token']}")
                mqtt_config["refresh_token"] = token_request["refresh_token"]
                mqtt_config["refresh_token_expires_at"] = (get_datetime() + timedelta(minutes=int(MQTT_REFRESH_TOKEN_TTL))).isoformat()
            # Save the updated MQTT configuration
            self.save_config({"mqtt": mqtt_config})
            self.update_stored_config("mqtt", mqtt_config)
            # Update the MQTT client with the new access token
            if self._mqtt is not None:
                self._mqtt.username_pw_set("IMA_OAUTH_ACCESS_TOKEN", mqtt_config["access_token"])
        else:
            # Log an error if the token refresh failed
            _LOGGER.error("------------- refreshing mqtt access_token failed (no access_token in response)")
            _LOGGER.debug(token_request)

    async def connect_mqtt(self):
        _LOGGER.debug("---------- START connect_mqtt")
        if self._mqtt is None:
            self._mqtt = mqtt.Client(clean_session=True, protocol=mqtt.MQTTv311)
            self._mqtt.enable_logger(logger=_LOGGER)
            self._mqtt.tls_set_context(_SSL_CONTEXT)
            self._mqtt.on_connect = self._on_mqtt_connect
            self._mqtt.on_disconnect = self._on_mqtt_disconnect
            self._mqtt.on_message = self._on_mqtt_message
        if self._mqtt.is_connected():
            self._mqtt.disconnect()
        await self.refresh_mqtt_token()
        self._mqtt.username_pw_set("IMA_OAUTH_ACCESS_TOKEN", self.get_config("mqtt")["access_token"])
        try:
            self._mqtt.connect(MQTT_SERVER, 8885, 60)
            self._mqtt.loop_start() # Under the hood, this will call loop_forever in a thread, which means that the thread will terminate if we call disconnect()
        except Exception as e:
            _LOGGER.error(f"connect_mqtt: {str(e)}")
        _LOGGER.debug("---------- END connect_mqtt")
        return self._mqtt.is_connected()

    def _on_mqtt_connect(self, client, userdata, result_code, _):
        _LOGGER.debug("---------- START _on_mqtt_connect")
        _LOGGER.debug("Code %s", result_code)
        topics = [MQTT_RESP_TOPIC + self.get_config("customer_id") + "/#"]
        for vehicle in self._vehicles:
            topics.append(MQTT_EVENT_TOPIC + vehicle["vin"])
        for topic in topics:
            client.subscribe(topic)
            _LOGGER.debug("Topic %s", topic)
        _LOGGER.debug("---------- END _on_mqtt_connect")

    def _on_mqtt_disconnect(self, client, userdata, result_code):
        _LOGGER.debug("---------- START _on_mqtt_disconnect")
        _LOGGER.debug(f"mqtt disconnected with result code {result_code} -> {mqtt.error_string(result_code)}")
        if result_code == 11: # MQTT_ERR_AUTH
            self.do_async(self.refresh_mqtt_token(force=True))
        else:
            self.do_async(self.refresh_mqtt_token(force=False))
        _LOGGER.debug("---------- END _on_mqtt_disconnect")

    def _on_mqtt_message(self, client, userdata, msg):
        _LOGGER.debug("---------- START _on_mqtt_message")
        try:
            _LOGGER.debug("MQTT msg received: %s %s", msg.topic, msg.payload)
            data = json.loads(msg.payload)
            charge_info = None
            if msg.topic.startswith(MQTT_RESP_TOPIC):
                coordinator = self.do_async(self.async_get_coordinator_by_vin(data["vin"]))
                if "return_code" not in data or data["return_code"] in ["0", "300", "500", "502", "422"]:
                    if "return_code" not in data:
                        result_code = data["process_code"]
                    else:
                        result_code = data["return_code"]
                    if result_code in ["300", "500"]:
                        self.do_async(self.hass_notify("command_error"))
                    if result_code != "901": # Not store "Vehicle as sleep" event
                        self.do_async(coordinator.update_command_history(data["correlation_id"], result_code))
                elif data["return_code"] == "400":
                    if "reason" in data and data["reason"] == "[authorization.denied.cvs.response.no.matching.service.key]":
                        self.do_async(coordinator.update_command_history(data["correlation_id"], "99"))
                    else:
                        if self._mqtt_last_request:
                            _LOGGER.debug("last request is send again, token was expired")
                            last_request = self._mqtt_last_request
                            self._mqtt_last_request = None
                            self.do_async(self.send_mqtt_message(last_request[0], last_request[1], coordinator._vehicle, store=False))
                        else:
                            _LOGGER.error("Last request might have been send twice without success")
                elif data["return_code"] != "0":
                    _LOGGER.error('%s : %s', data["return_code"], data.get("reason", "?"))
            elif msg.topic.startswith(MQTT_EVENT_TOPIC):
#                 charge_info = data["charging_state"]
#                 programs = data["precond_state"].get("programs", None)
#                 if programs:
#                     self.precond_programs[data["vin"]] = data["precond_state"]["programs"]
                _LOGGER.debug("Update data from mqtt?!?")
        except KeyError:
            _LOGGER.error("MQTT message error")
        _LOGGER.debug("---------- END _on_mqtt_message")

    async def send_mqtt_message(self, service, message, vehicle, store=True):
        _LOGGER.debug("---------- START send_mqtt_message")
        # we need to refresh the token if it is expired, either here upfront or in the mqtt callback '_on_mqtt_message' in case of result_code 400
        try:
            await self.refresh_mqtt_token(force=(store == False))
            customer_id = self.get_config("customer_id")
            topic = MQTT_REQ_TOPIC + customer_id + service
            date = datetime.utcnow()
            action_id = str(uuid4()).replace("-", "") + date.strftime("%Y%m%d%H%M%S%f")[:-3]
            data = json.dumps({
                "access_token": self.get_config("mqtt")["access_token"],
                "customer_id": customer_id,
                "correlation_id": action_id,
                "req_date": date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "vin": vehicle["vin"],
                "req_parameters": message
            })
            _LOGGER.debug(topic)
            _LOGGER.debug(data)
            message_info = self._mqtt.publish(topic, data)
            if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.error("Failed to send MQTT message: %s", mqtt.error_string(message_info.rc))
                action_id = None
            if store:
                self._mqtt_last_request = [service, message]
            _LOGGER.debug("---------- END send_mqtt_message")
            return action_id
        except ConfigEntryAuthFailed as e:
            _LOGGER.error("Failed to send MQTT message for vehicle '%s' due to authentication error: %s", vehicle["vin"], e)
            raise
        except Exception as e:
            _LOGGER.error("Unexpected error during MQTT message sending: %s", e)
            raise

    async def send_abrp_data(self, params):
        _LOGGER.debug("---------- START send_abrp_data")
        params["api_key"] = "1e28ad14-df16-49f0-97da-364c9154b44a"
        abrp_request = await self.make_http_request("https://api.iternio.com/1/tlm/send", "POST", None, params)
        _LOGGER.debug(params)
        _LOGGER.debug(abrp_request)
        if "status" not in abrp_request or abrp_request["status"] != "ok":
            _LOGGER.error(abrp_request)
        _LOGGER.debug("---------- END send_abrp_data")
