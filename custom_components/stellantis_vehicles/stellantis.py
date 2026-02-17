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
from datetime import ( datetime, timedelta )
import ssl
import socket
import random

from homeassistant.core import ( HomeAssistant, HassJob)
from homeassistant.helpers import translation
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components import persistent_notification
from homeassistant.helpers.event import async_track_point_in_time

from .base import StellantisVehicleCoordinator
from .otp.otp import Otp, save_otp, load_otp, ConfigException
from .utils import ( get_datetime, rate_limit, SensitiveDataFilter, replace_string_placeholders )
from .exceptions import ( ComunicationError, RateLimitException )

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    FIELD_COUNTRY_CODE,
    FIELD_REMOTE_COMMANDS,
    FIELD_NOTIFICATIONS,
    MOBILE_APPS,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    OAUTH_CODE_URL,
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
    MQTT_PORT,
    MQTT_KEEP_ALIVE_S,
    MQTT_QOS,
    MQTT_RESP_TOPIC,
    MQTT_EVENT_TOPIC,
    MQTT_REQ_TOPIC,
    GET_USER_INFO_URL,
    CAR_API_GET_VEHICLE_TRIPS_URL,
    MQTT_REFRESH_TOKEN_JSON_DATA,
    MQTT_REFRESH_TOKEN_TTL,
    OTP_FILENAME,
    ABRP_URL,
    ABRP_API_KEY,
    TRANSLATION_PLACEHOLDERS
)

_LOGGER = logging.getLogger(__name__)


# Some Stellantis MQTT servers drop packets with a TCP payload greater than 1456 bytes
# which causes the TLS handshake to fail and later a "Connnection reset by peer" error.
# As a workaround, we modify the MQTT client to reduce the MSS before connecting the TCP socket
class MqttClientMod(mqtt.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def _create_socket_connection(self) -> socket.socket:
        if self._get_proxy():
            return super()._create_socket_connection()  # SOCKS will reduce MSS by itself
        
        addr_infos = socket.getaddrinfo(self._host, self._port, 0, socket.SOCK_STREAM)
        addr_cnt = len(addr_infos)
        if addr_cnt == 0:
            raise socket.error(f"getaddrinfo returned an empty list")

        # DNS returns multiple redundant MQTT IPs, but they are not rotated until the DNS cache expires
        # we randomize the order to reconnect more quickly in case oneof them has issues and
        # the connection fails after TCP socket open (SSL handshake, broker overloaded)
        random.shuffle(addr_infos)

        # attempt to connect, raise only if none of them are connectable
        for af, socktype, proto, canonname, sa in addr_infos:
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 1460 - 4)
                sock.settimeout(self._connect_timeout)
                sock.bind((self._bind_address, self._bind_port))
                _LOGGER.debug(f"Connecting to MQTT socket: {sa}")
                sock.connect(sa)
                return sock

            except socket.error:
                if sock is not None:
                    sock.close()
                addr_cnt -= 1
                if addr_cnt == 0:
                    raise


def _create_ssl_context() -> ssl.SSLContext:
    """Create a SSL context for the MQTT connection."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_default_certs()
    return context

_SSL_CONTEXT = _create_ssl_context()

class StellantisBase:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._config = {}
        self._session = None
        self.otp = None

        self.logger_filter = SensitiveDataFilter()
        _LOGGER.addFilter(self.logger_filter)

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

    @property
    def remote_commands(self):
        return self.get_config(FIELD_REMOTE_COMMANDS) in [None, True]

    def disable_remote_commands(self):
        self.save_config({FIELD_REMOTE_COMMANDS: False})
        self.update_stored_config(FIELD_REMOTE_COMMANDS, False)

    def replace_placeholders(self, string, vehicle=None):
        if vehicle is None:
            vehicle = []
        for key in vehicle:
            string = string.replace("{#" + key + "#}", str(vehicle[key]))
        for key, value in self._config.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    string = string.replace("{#" + key + "|" + subkey + "#}", str(subvalue))
            else:
                string = string.replace("{#" + key + "#}", str(value))
        return string

    def apply_dict_params(self, headers):
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

    async def make_http_request(self, url, method='GET', headers=None, params=None, json_data=None, data=None, timeout=60):
        _LOGGER.debug("---------- START make_http_request")
        self.start_session()
        try:
            _timeout = aiohttp.ClientTimeout(total=timeout)
            async with self._session.request(method, url, params=params, json=json_data, data=data, headers=headers, timeout=_timeout) as resp:
                result = {}
                error = None
                if method != "DELETE" and (await resp.text()):
                    result = await resp.json()
                if not str(resp.status).startswith("20"):
                    _LOGGER.debug(f"{method} request error {str(resp.status)}: {resp.url}")
                    _LOGGER.debug(headers)
                    _LOGGER.debug(params)
                    _LOGGER.debug(json_data)
                    _LOGGER.debug(data)
                    _LOGGER.debug(result)
                    if "httpMessage" in result and "moreInformation" in result:
                        error = result["httpMessage"] + " - " + result["moreInformation"]
                    elif "error" in result and "error_description" in result:
                        error = result["error"] + " - " + result["error_description"]
                    elif "message" in result and "code" in result:
                        error = result["message"] + " - " + str(result["code"])

                if str(resp.status) == "404" and str(result["code"]) == "40400":
                    # Not Found: We didn't find the status for this vehicle. - 40400
                    _LOGGER.warning(error)
                    result = {}
                elif str(resp.status) == "500" and result.get("code", None) == "50000":
                    # Connection module replaced (https://github.com/andreadegiovine/homeassistant-stellantis-vehicles/issues/388)
                    raise ConfigEntryAuthFailed(error)
                elif str(resp.status) == "400" and result.get("error", None) == "invalid_grant":
                    # Token expiration
                    raise ConfigEntryAuthFailed(error)
                elif str(resp.status) == "401":
                    # Oauth token seem expired, refresh request blocked by server/connection error
                    raise ComunicationError(error)
                elif str(resp.status).startswith("50"):
                    # Internal error
                    raise ComunicationError(error)
                if error is not None:
                    # Generic error
                    raise Exception(error)
                _LOGGER.debug("---------- END make_http_request")
                return result
        except asyncio.TimeoutError as e:
            await self.close_session()
            _LOGGER.warning(f"Error: {e}")
            _LOGGER.debug("---------- END make_http_request")
            # Connection error
            raise ComunicationError("Request timeout")
        except aiohttp.client_exceptions.ClientError as e:
            await self.close_session()
            _LOGGER.warning(f"Error: {e}")
            _LOGGER.debug("---------- END make_http_request")
            # Connection error
            raise ComunicationError(e)
        except Exception as e:
            await self.close_session()
            _LOGGER.warning(f"Error: {e}")
            _LOGGER.debug("---------- END make_http_request")
            raise

    def do_async(self, async_func, delay=0):
        async def delayed_execution():
            if delay > 0:
                await asyncio.sleep(delay)
            return await async_func
        return asyncio.run_coroutine_threadsafe(delayed_execution(), self._hass.loop).result()

    async def hass_notify(self, translation_key):
        """Create a persistent notification."""
        if hasattr(self, '_entry') and not self.get_stored_config(FIELD_NOTIFICATIONS):
            return

        translations = await translation.async_get_translations(self._hass, self._hass.config.language, "common", {DOMAIN})
        notification_title = "Stellantis Vehicles"
        if translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None):
            notification_title = notification_title + " - " + str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None))
        notification_message = str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_message", None))

        notification_title = replace_string_placeholders(notification_title, TRANSLATION_PLACEHOLDERS)
        notification_message = replace_string_placeholders(notification_message, TRANSLATION_PLACEHOLDERS)

        persistent_notification.async_create(
            self._hass,
            notification_message,
            title=notification_title,
            notification_id=str(uuid4())
        )


class StellantisOauth(StellantisBase):
    def get_oauth_url(self):
        return self.apply_query_params(OAUTH_AUTHORIZE_URL, OAUTH_AUTHORIZE_QUERY_PARAMS)

    async def get_oauth_code(self, email, password):
        _LOGGER.debug("---------- START get_oauth_code")
        oauth_code_request = await self.make_http_request(OAUTH_CODE_URL, 'POST', None, None, {"url": self.get_oauth_url(), "email": email, "password": password}, None, 300)
        if "code" in oauth_code_request:
            self.logger_filter.add_custom_value(oauth_code_request["code"])
        _LOGGER.debug(oauth_code_request)
        _LOGGER.debug("---------- END get_oauth_code")
        return oauth_code_request

    async def get_access_token(self):
        _LOGGER.debug("---------- START get_access_token")
        url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_GET_TOKEN_QUERY_PARAMS)
        headers = self.apply_dict_params(OAUTH_TOKEN_HEADERS)
        token_request = await self.make_http_request(url, 'POST', headers)
        if "access_token" in token_request:
            self.logger_filter.add_custom_value(token_request["access_token"])
        if "refresh_token" in token_request:
            self.logger_filter.add_custom_value(token_request["refresh_token"])
        if "id_token" in token_request:
            self.logger_filter.add_custom_value(token_request["id_token"])
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(token_request)
        _LOGGER.debug("---------- END get_access_token")
        return token_request

    async def get_user_info(self):
        _LOGGER.debug("---------- START get_user_info")
        url = self.apply_query_params(GET_USER_INFO_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_dict_params(GET_OTP_HEADERS)
        headers["x-transaction-id"] = "1234"
        user_request = await self.make_http_request(url, 'GET', headers)
        if "customer" in user_request[0]:
            self.logger_filter.add_custom_value(user_request[0]["customer"])
        if "vehicle" in user_request[0]:
            self.logger_filter.add_custom_value(user_request[0]["vehicle"])
        if "car_association_id" in user_request[0]:
            self.logger_filter.add_custom_value(user_request[0]["car_association_id"])
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(user_request)
        _LOGGER.debug("---------- END get_user_info")
        return user_request

    def new_otp(self, sms_code, pin_code):
        try:
            self.otp = Otp("bb8e981582b0f31353108fb020bead1c", device_id=str(self.get_config("oauth")["access_token"][:16]))
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
        headers = self.apply_dict_params(GET_OTP_HEADERS)
        sms_request = await self.make_http_request(url, 'POST', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(sms_request)
        _LOGGER.debug("---------- END get_otp_sms")
        return sms_request

    async def get_mqtt_access_token(self):
        _LOGGER.debug("---------- START get_mqtt_access_token")
        url = self.apply_query_params(GET_MQTT_TOKEN_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_dict_params(GET_OTP_HEADERS)
        try:
            otp_code = await self.get_otp_code()
            token_request = await self.make_http_request(url, 'POST', headers, None, {"grant_type": "password", "password": otp_code})
            if "access_token" in token_request:
                self.logger_filter.add_custom_value(token_request["access_token"])
            if "refresh_token" in token_request:
                self.logger_filter.add_custom_value(token_request["refresh_token"])
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(token_request)
        except ConfigException as e:
            _LOGGER.debug("---------- END get_mqtt_access_token")
            raise ConfigEntryAuthFailed(str(e))
        except Exception:
            _LOGGER.debug("---------- END get_mqtt_access_token")
            raise
        _LOGGER.debug("---------- END get_mqtt_access_token")
        return token_request

    @rate_limit(6, 86400) # 6 per 1 day
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
                _LOGGER.debug("---------- END get_otp_code")
                raise ConfigEntryAuthFailed("OTP file not found, please reauthenticate")
            self.otp = await self._hass.async_add_executor_job(load_otp, otp_file_path)
        # Get the OTP code using OTP object. It seems there is a rate limit of 6 requests per 24h
        otp_code = await self._hass.async_add_executor_job(self.otp.get_otp_code)
        if otp_code is None:
            _LOGGER.error("Error: OTP code is empty, please reauthenticate")
            _LOGGER.debug("---------- END get_otp_code")
            raise ConfigEntryAuthFailed("OTP code is empty, please reauthenticate")
        # Save updated OTP object to file
        await self._hass.async_add_executor_job(save_otp, self.otp, otp_file_path)
        _LOGGER.debug("---------- END get_otp_code")
        return otp_code


class StellantisVehicles(StellantisOauth):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)

        self._entry = None
        self._coordinator_dict = {}
        self._vehicles = []
        self._mqtt = None
        self._mqtt_last_request = None

        self._oauth_token_scheduled = None
        self._mqtt_token_scheduled = None

    def set_entry(self, entry):
        self._entry = entry
        self.logger_filter.add_entry_values(self._config)

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
        return None

    def update_vehicle_stored_config(self, vin, key, value):
        data = self.get_stored_config(vin)
        if not data:
            data = {}
        data[key] = value
        self.update_stored_config(vin, data)

    def get_vehicle_stored_config(self, vin, key):
        data = self.get_stored_config(vin)
        if data and key in data:
            return data[key]
        return None

    def async_get_coordinator_by_vin(self, vin):
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        return None

    def async_get_coordinator_by_action_id(self, action_id):
        for vin in self._coordinator_dict:
            if action_id in self._coordinator_dict[vin]._commands_history:
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
        entry_path = f"{public_path}/{DOMAIN}/{customer_id}"
        if not os.path.isdir(entry_path):
            os.makedirs(entry_path, exist_ok=True)
        image_path = f"{entry_path}/{vin}.png"
        image_url = image_path.replace(public_path, "/local")
        if os.path.isfile(image_path):
            return image_url
        image = await self._hass.async_add_executor_job(urlopen, url)
        with Image.open(image) as im:
            im = ImageOps.pad(im, (400, 400))
        await self._hass.async_add_executor_job(im.save, image_path)
        return image_url

    async def scheduled_tokens_refresh(self):
        if self._oauth_token_scheduled is not None:
            self._oauth_token_scheduled()
            self._oauth_token_scheduled = None
        if self._mqtt_token_scheduled is not None:
            self._mqtt_token_scheduled()
            self._mqtt_token_scheduled = None
        await self.scheduled_oauth_token_refresh()
        await self.scheduled_mqtt_token_refresh()

    async def scheduled_oauth_token_refresh(self, now=None):
        _LOGGER.debug("---------- START scheduled_oauth_token_refresh")
        def get_next_run():
            expires_in = self.get_config("oauth")["expires_in"]
            return datetime.fromisoformat(expires_in) - timedelta(minutes=5)
        try:
            if self._oauth_token_scheduled is not None:
                self._oauth_token_scheduled()
                self._oauth_token_scheduled = None
                await self.refresh_token_request()
            elif get_datetime() > get_next_run():
                await self.refresh_token_request()
            next_run = get_next_run()
        except ComunicationError:
            next_run = get_datetime() + timedelta(minutes=5)
        except RateLimitException:
            _LOGGER.warning("Rate limit exceeded, retry after 30 mins or check logs and restart integration")
            next_run = get_datetime() + timedelta(minutes=30)
        _LOGGER.debug(f"Current time: {get_datetime()}")
        _LOGGER.debug(f"Next refresh: {next_run}")
        next_job = HassJob(self.scheduled_oauth_token_refresh, f"{DOMAIN} refresh oauth token: {next_run}", cancel_on_shutdown=True)
        self._oauth_token_scheduled = async_track_point_in_time(self._hass, next_job, next_run)
        _LOGGER.debug("---------- END scheduled_oauth_token_refresh")

    @rate_limit(6, 1800) # 6 per 30 min
    async def refresh_token_request(self):
        _LOGGER.debug("---------- START refresh_token_request")
        url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_REFRESH_TOKEN_QUERY_PARAMS)
        headers = self.apply_dict_params(OAUTH_TOKEN_HEADERS)
        token_request = await self.make_http_request(url, 'POST', headers)
        self.logger_filter.add_custom_value(token_request["access_token"])
        self.logger_filter.add_custom_value(token_request["refresh_token"])
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(token_request)
        new_config = {
            "access_token": token_request["access_token"],
            "refresh_token": token_request["refresh_token"],
            "expires_in": (get_datetime() + timedelta(seconds=int(token_request["expires_in"]))).isoformat()
        }
        self.save_config({"oauth": new_config})
        self.update_stored_config("oauth", new_config)
        _LOGGER.debug("---------- END refresh_token_request")

    async def get_user_vehicles(self):
        _LOGGER.debug("---------- START get_user_vehicles")
        if not self._vehicles:
            url = self.apply_query_params(CAR_API_VEHICLES_URL, CLIENT_ID_QUERY_PARAMS)
            headers = self.apply_dict_params(CAR_API_HEADERS)
            vehicles_request = await self.make_http_request(url, 'GET', headers)
            if "_embedded" in vehicles_request:
                if "vehicles" in vehicles_request["_embedded"]:
                    for vehicle in vehicles_request["_embedded"]["vehicles"]:
                        self.logger_filter.add_custom_value(vehicle["vin"])
                        self.logger_filter.add_custom_value(vehicle["id"])
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
                            _LOGGER.warning(str(e))
                        self._vehicles.append(vehicle_data)
                else:
                    _LOGGER.warning("No vehicles found in vehicles_request['_embedded']")
            else:
                _LOGGER.warning("No _embedded found in vehicles_request")
        _LOGGER.debug("---------- END get_user_vehicles")
        return self._vehicles

    async def get_vehicle_status(self, vehicle):
        _LOGGER.debug("---------- START get_vehicle_status")
        # Ensure that the MQTT client is connected
        if self.remote_commands and (self._mqtt is None or self._mqtt.is_connected() is False):
            _LOGGER.debug("MQTT client is not connected, try to connect it")
            await self.connect_mqtt()
        # Fetch the vehicle status using the API
        url = self.apply_query_params(CAR_API_GET_VEHICLE_STATUS_URL, CLIENT_ID_QUERY_PARAMS, vehicle)
        headers = self.apply_dict_params(CAR_API_HEADERS)
        vehicle_status_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(vehicle_status_request)
        _LOGGER.debug("---------- END get_vehicle_status")
        return vehicle_status_request

    async def get_vehicle_last_trip(self, vehicle, page_token=False):
        _LOGGER.debug("---------- START get_vehicle_last_trip")
        url = self.apply_query_params(CAR_API_GET_VEHICLE_TRIPS_URL, CLIENT_ID_QUERY_PARAMS, vehicle)
        headers = self.apply_dict_params(CAR_API_HEADERS)
        limit_date = (get_datetime() - timedelta(days=1)).isoformat()
        limit_date = limit_date.split(".")[0] + "+" + limit_date.split(".")[1].split("+")[1]
        url = url + "&timestamps=" + limit_date + "/&distance=0.1-"
        if page_token:
            url = url + "&pageToken=" + page_token
        vehicle_trips_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(vehicle_trips_request)
        if "total" in vehicle_trips_request and int(vehicle_trips_request["total"]) > 60 and not page_token:
            last_page_url = vehicle_trips_request["_links"]["last"]["href"]
            page_token = last_page_url.split("pageToken=")[1]
            _LOGGER.debug("---------- END get_vehicle_last_trip")
            return await self.get_vehicle_last_trip(page_token)
        _LOGGER.debug("---------- END get_vehicle_last_trip")
        return vehicle_trips_request

#     async def get_vehicle_trips(self, page_token=False):
#         _LOGGER.debug("---------- START get_vehicle_trips")
#         url = self.apply_query_params(CAR_API_GET_VEHICLE_TRIPS_URL, CLIENT_ID_QUERY_PARAMS)
#         headers = self.apply_dict_params(CAR_API_HEADERS)
#         url = url + "&distance=0.1-"
#         if page_token:
#             url = url + "&pageToken=" + page_token
#         vehicle_trips_request = await self.make_http_request(url, 'GET', headers)
#         _LOGGER.debug(url)
#         _LOGGER.debug(headers)
#         _LOGGER.debug(vehicle_trips_request)
#         _LOGGER.debug("---------- END get_vehicle_trips")
#         return vehicle_trips_request

    async def scheduled_mqtt_token_refresh(self, now=None, force=False):
        if not self.remote_commands:
            return
        _LOGGER.debug("---------- START scheduled_mqtt_token_refresh")
        def get_next_run():
            mqtt_config = self.get_config("mqtt")
            expires_in = mqtt_config["expires_in"]
            return datetime.fromisoformat(expires_in) - timedelta(minutes=3)
        try:
            if self._mqtt_token_scheduled is not None or force:
                self._mqtt_token_scheduled()
                self._mqtt_token_scheduled = None
                await self.refresh_mqtt_token_request()
            elif get_datetime() > get_next_run():
                await self.refresh_mqtt_token_request()
            next_run = get_next_run()
        except ComunicationError:
            next_run = get_datetime() + timedelta(minutes=1)
        except RateLimitException:
            _LOGGER.warning("Rate limit exceeded, retry after 1 day or check logs and restart integration")
            next_run = get_datetime() + timedelta(days=1)
        except ConfigException:
            self.disable_remote_commands()
            await self.hass_notify("reconfigure_otp")
            _LOGGER.error("MQTT authentication error. To enable remote commands again please reconfigure the integration")
            _LOGGER.debug("---------- END scheduled_mqtt_token_refresh")
            return
        _LOGGER.debug(f"Current time: {get_datetime()}")
        _LOGGER.debug(f"Next refresh: {next_run}")
        next_job = HassJob(self.scheduled_mqtt_token_refresh, f"{DOMAIN} refresh mqtt token: {next_run}", cancel_on_shutdown=True)
        self._mqtt_token_scheduled = async_track_point_in_time(self._hass, next_job, next_run)
        _LOGGER.debug("---------- END scheduled_mqtt_token_refresh")

    async def refresh_mqtt_token_request(self, access_token_only=False):
        _LOGGER.debug("---------- START refresh_mqtt_token_request")
        url = self.apply_query_params(GET_MQTT_TOKEN_URL, CLIENT_ID_QUERY_PARAMS)
        headers = self.apply_dict_params(GET_OTP_HEADERS)
        mqtt_config = self.get_config("mqtt")
        refresh_token_almost_expired = "refresh_token_expires_at" not in mqtt_config or datetime.fromisoformat(mqtt_config["refresh_token_expires_at"]) < get_datetime()
        if refresh_token_almost_expired and not access_token_only:
            otp_code = await self.get_otp_code()
            try:
                token_request = await self.make_http_request(url, 'POST', headers, None, {"grant_type": "password", "password": otp_code})
            except ConfigEntryAuthFailed:
                _LOGGER.warning("Attempt to refresh MQTT access_token/refresh_token failed. This is NOT an error as long as the following attempt to refresh only the access_token (using current refresh_token) succeeds.")
                return await self.refresh_mqtt_token_request(True)
        else:
            json_data = self.apply_dict_params(MQTT_REFRESH_TOKEN_JSON_DATA)
            token_request = await self.make_http_request(url, 'POST', headers, None, json_data)
        if "access_token" in token_request:
            self.logger_filter.add_custom_value(token_request["access_token"])
        if "refresh_token" in token_request:
            self.logger_filter.add_custom_value(token_request["refresh_token"])
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(token_request)
        if not "access_token" in token_request:
            _LOGGER.warning("Refreshing mqtt access_token failed (no access_token in response)")
            _LOGGER.debug("---------- END refresh_mqtt_token_request")
            return None
        mqtt_config["access_token"] = token_request["access_token"]
        mqtt_config["expires_in"] = (get_datetime() + timedelta(seconds=int(token_request["expires_in"]))).isoformat()
        if "refresh_token" in token_request:
            mqtt_config["refresh_token"] = token_request["refresh_token"]
            mqtt_config["refresh_token_expires_at"] = (get_datetime() + timedelta(minutes=int(MQTT_REFRESH_TOKEN_TTL))).isoformat()
        self.save_config({"mqtt": mqtt_config})
        self.update_stored_config("mqtt", mqtt_config)
        _LOGGER.debug("---------- END refresh_mqtt_token_request")

    async def connect_mqtt(self):
        _LOGGER.debug("---------- START connect_mqtt")
        if self._mqtt is None:
            self._mqtt = MqttClientMod(clean_session=True, protocol=mqtt.MQTTv311)
            # self._mqtt.enable_logger(logger=_LOGGER)
            self._mqtt.tls_set_context(_SSL_CONTEXT)
            self._mqtt.on_connect = self._on_mqtt_connect
            self._mqtt.on_disconnect = self._on_mqtt_disconnect
            self._mqtt.on_message = self._on_mqtt_message
            self._mqtt.on_subscribe = self._on_mqtt_subscribe
        if self._mqtt.is_connected():
            self._mqtt.disconnect()
        self._mqtt.username_pw_set("IMA_OAUTH_ACCESS_TOKEN", self.get_config("mqtt")["access_token"])
        try:
            self._mqtt.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEP_ALIVE_S)
            self._mqtt.loop_start() # Under the hood, this will call loop_forever in a thread, which means that the thread will terminate if we call disconnect()
        except Exception as e:
            _LOGGER.warning(f"Error: {str(e)}")
        _LOGGER.debug("---------- END connect_mqtt")
        return self._mqtt.is_connected()

    def _on_mqtt_connect(self, client, userdata, result_code, _):
        _LOGGER.debug("---------- START _on_mqtt_connect")
        _LOGGER.debug(f"Code: {result_code}")
        try:
            topics = [MQTT_RESP_TOPIC + self.get_config("customer_id") + "/#"]
            for vehicle in self._vehicles:
                topics.append(MQTT_EVENT_TOPIC + vehicle["vin"])
            for topic in topics:
                client.subscribe(topic, qos=MQTT_QOS)
                _LOGGER.debug(f"Topic: {topic}")
        except Exception as e:
            _LOGGER.warning(f"Error: {str(e)}")
        _LOGGER.debug("---------- END _on_mqtt_connect")

    def _on_mqtt_disconnect(self, client, userdata, result_code):
        _LOGGER.debug("---------- START _on_mqtt_disconnect")
        _LOGGER.debug(f"Code: {result_code} -> {mqtt.error_string(result_code)}")
        try:
            if result_code == 11: # MQTT_ERR_AUTH
                self.do_async(self.scheduled_mqtt_token_refresh(force=True))
        except:
            pass  # refresh_mqtt_token already logs the exception, and raising would halt the Paho reconnect loop
        _LOGGER.debug("---------- END _on_mqtt_disconnect")

    def _on_mqtt_subscribe(self, client, userdata, mid, granted_qos):
        _LOGGER.debug("---------- START _on_mqtt_subscribe")
        for i, qos in enumerate(granted_qos):
            if qos == 0x80:
                _LOGGER.debug("Failed")
            else:
                _LOGGER.debug(f"Completed (QoS: {qos})")
        _LOGGER.debug("---------- END _on_mqtt_subscribe")

    def _on_mqtt_message(self, client, userdata, msg):
        _LOGGER.debug("---------- START _on_mqtt_message")
        try:
            _LOGGER.debug(f"Message: {msg.topic} {msg.payload} {msg.qos}")
            data = json.loads(msg.payload)
            if msg.topic.startswith(MQTT_RESP_TOPIC):
                if "vin" in data:
                    coordinator = self.async_get_coordinator_by_vin(data["vin"])
                else:
                    coordinator = self.async_get_coordinator_by_action_id(data["correlation_id"])

                if not coordinator:
                    _LOGGER.error("No coordinator found by vin o correlation_id")
                    _LOGGER.debug("---------- END _on_mqtt_message")
                    return

                result_code = None
                if "return_code" in data:
                    result_code = data["return_code"]
                elif "process_code" in data:
                    result_code = data["process_code"]

                if result_code:
                    if result_code == "400":
                        if "reason" in data and data["reason"] == "[authorization.denied.cvs.response.no.matching.service.key]":
                            result_code = "not_compatible"
                        elif self._mqtt_last_request:
                            _LOGGER.debug("The mqtt token seems invalid, refresh the token and try sending the request again")
                            last_request = self._mqtt_last_request
                            self._mqtt_last_request = None
                            self.do_async(self.send_mqtt_message(last_request[0], last_request[1], coordinator._vehicle, False, data["correlation_id"]))
                            _LOGGER.debug("---------- END _on_mqtt_message")
                            return
                        else:
                            _LOGGER.warning("Last request was sent twice without success")
                            result_code = "failed"
                    if result_code == "113":  # Error: vin (https://github.com/andreadegiovine/homeassistant-stellantis-vehicles/issues/388)
                        result_code = "failed"
                    if result_code in ["300", "500", "not_compatible", "failed"]:
                        self.do_async(self.hass_notify("command_error"))
                    if result_code == "0":
                        _LOGGER.debug(f"Fetch updates after code: {result_code}")
                        self.do_async(coordinator.async_refresh(), 10)

                    if result_code != "901":  # Not store "Vehicle as sleep" event
                        self.do_async(coordinator.update_command_history(data["correlation_id"], result_code))
                else:
                    _LOGGER.error("No result code")

            elif msg.topic.startswith(MQTT_EVENT_TOPIC):
#                 charge_info = data["charging_state"]
#                 programs = data["precond_state"].get("programs", None)
#                 if programs:
#                     self.precond_programs[data["vin"]] = data["precond_state"]["programs"]
                _LOGGER.debug("Update data from mqtt?!?")
        except (KeyError, Exception) as e:
            _LOGGER.warning(f"Error: {str(e)}")
        _LOGGER.debug("---------- END _on_mqtt_message")

    async def send_mqtt_message(self, service, message, vehicle, store=True, action_id=None):
        _LOGGER.debug("---------- START send_mqtt_message")
        # we need to refresh the token if it is expired, either here upfront or in the mqtt callback '_on_mqtt_message' in case of result_code 400
        try:
            await self.scheduled_mqtt_token_refresh(force=(store == False))
            customer_id = self.get_config("customer_id")
            topic = MQTT_REQ_TOPIC + customer_id + service
            date = get_datetime()
            if action_id is None:
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
            message_info = self._mqtt.publish(topic, data, qos=MQTT_QOS, retain=False)
            if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.warning(f"Failed to send MQTT message: {mqtt.error_string(message_info.rc)}")
                action_id = None
            if store:
                self._mqtt_last_request = [service, message]
            _LOGGER.debug("---------- END send_mqtt_message")
            return action_id
        except ConfigEntryAuthFailed:
            self.disable_remote_commands()
            await self.hass_notify("reconfigure_otp")
            _LOGGER.error("MQTT authentication error. To enable remote commands again please reconfigure the integration")
            _LOGGER.debug("---------- END send_mqtt_message")
            pass
        except Exception as e:
            _LOGGER.error(f"Unexpected error during MQTT message sending: {e}")
            _LOGGER.debug("---------- END send_mqtt_message")
            raise

    async def send_abrp_data(self, params):
        _LOGGER.debug("---------- START send_abrp_data")
        params["api_key"] = ABRP_API_KEY
        _LOGGER.debug(params)
        try:
            abrp_request = await self.make_http_request(ABRP_URL, "POST", None, params)
            _LOGGER.debug(abrp_request)
            if "status" not in abrp_request or abrp_request["status"] != "ok":
                _LOGGER.warning(abrp_request)
        except Exception:
            pass
        _LOGGER.debug("---------- END send_abrp_data")
