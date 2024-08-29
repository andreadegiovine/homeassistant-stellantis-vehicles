from .const import (
    DOMAIN,
    MOBILE_APPS,
    WEBHOOK_ID,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    OAUTH_AUTHORIZE_QUERY_PARAMS,
    OAUTH_GET_TOKEN_QUERY_PARAMS,
    OAUTH_REFRESH_TOKEN_QUERY_PARAMS,
    OAUTH_TOKEN_HEADERS,
    CAR_API_VEHICLES_URL,
    CLIENT_ID_QUERY_PARAM,
    CAR_API_HEADERS,
    CAR_API_GET_VEHICLE_STATUS_URL,
    CAR_API_CALLBACK_URL,
    CAR_API_DELETE_CALLBACK_URL,
    CAR_API_SEND_COMMAND_URL,
    CAR_API_CHECK_COMMAND_URL
)

from homeassistant.components import (panel_custom, webhook)
from homeassistant.components.webhook import DOMAIN as WEBHOOK_DOMAIN
from homeassistant.components.frontend import async_remove_panel
from homeassistant.helpers.network import get_url

from .base import StellantisVehicleCoordinator

from pathlib import Path
import logging
import aiohttp
import base64
from PIL import Image, ImageOps
import os
from urllib.request import urlopen

from datetime import ( datetime, timedelta )

_LOGGER = logging.getLogger(__name__)

IMAGE_PATH = "stellantis-vehicles"

class StellantisBase:
    def __init__(self, hass) -> None:
        self._hass = hass
        self._config = {}
        self._session = aiohttp.ClientSession()

    def set_mobile_app(self, mobile_app):
        if mobile_app in MOBILE_APPS:
            self.save_config(MOBILE_APPS[mobile_app])
            self.save_config({"basic_token": base64.b64encode(bytes(self._config["client_id"] + ":" + self._config["secret"], 'utf-8')).decode('utf-8')})

    def save_config(self, data):
        for key in data:
            self._config[key] = data[key]
            if key == "mobile_app":
                self.set_mobile_app(data[key])

    def get_config(self, key):
        if key in self._config:
            return self._config[key]
        return None

    def replace_placeholders(self, string):
        params = self._config
        lang = self._hass.config.language
        params["locale"] = lang
        params["locale_2"] = lang + "-" + lang.upper()
        for key in self._config:
            string = string.replace("{#"+key+"#}", str(self._config[key]))
        return string

    def apply_headers_params(self, headers):
        new_headers = {}
        for key in headers:
            new_headers[key] = self.replace_placeholders(headers[key])
        return new_headers

    def apply_query_params(self, url, params):
        query_params = []
        for key in params:
            value = params[key]
            query_params.append(f"{key}={value}")
        query_params = '&'.join(query_params)
        return self.replace_placeholders(f"{url}?{query_params}")

    async def make_http_request(self, url, method = 'GET', headers = None, params = None, json = None, data = None):
        async with self._session.request(method, url, params=params, json=json, data=data, headers=headers) as resp:
            result = {}
            if method != "DELETE":
                result = await resp.json()
            if not str(resp.status).startswith("20"):
                _LOGGER.debug("---------- START make_http_request")
                _LOGGER.error(f"{method} request error " + str(resp.status))
                _LOGGER.debug(resp.url)
                _LOGGER.debug(headers)
                _LOGGER.debug(params)
                _LOGGER.debug(json)
                _LOGGER.debug(data)
                _LOGGER.debug(result)
                _LOGGER.debug("---------- END make_http_request")
                error = ''
                if "httpMessage" in result and "moreInformation" in result:
                    error = result["httpMessage"] + " - " + result["moreInformation"]
                elif "error" in result and "error_description" in result:
                    error = result["error"] + " - " + result["error_description"]
                elif "message" in result and "code" in result:
                    error = result["message"] + " - " + str(result["code"])
                raise Exception(error)
            return result


class StellantisOauth(StellantisBase):
    def get_oauth_url(self):
        return self.apply_query_params(OAUTH_AUTHORIZE_URL, OAUTH_AUTHORIZE_QUERY_PARAMS)

    async def get_access_token(self):
        url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_GET_TOKEN_QUERY_PARAMS)
        headers = self.apply_headers_params(OAUTH_TOKEN_HEADERS)
        return await self.make_http_request(url, 'POST', headers)


class StellantisVehicles(StellantisBase):
    def __init__(self, hass) -> None:
        super().__init__(hass)

        self._entry = None
        self._vehicle = None
        self._coordinator_dict  = {}
        self._vehicles = []
        self._callback_id = None

    def set_entry(self, entry):
        self._entry = entry

    def set_vehicle(self, vehicle):
        if not self._vehicle and vehicle:
            self._vehicle = vehicle
            self.save_config(vehicle)

    async def async_get_coordinator_by_vin(self, vin):
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        return None

    async def async_get_coordinator(self, vehicle):
        self.set_vehicle(vehicle)
        vin = vehicle.get("vin", "")
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        coordinator = StellantisVehicleCoordinator(self._hass, self._config, vehicle, self)
        self._coordinator_dict[vin] = coordinator
        return coordinator

    async def _handle_webhook(self, hass, webhook_id, request):
        _LOGGER.debug("---------- START _handle_webhook")
        body = await request.json()
        _LOGGER.debug(body)
        event = body["remoteEvent"]
        vin = event["vin"]
        coordinator = await self.async_get_coordinator_by_vin(vin)
        name = event["remoteType"]
        action_id = event["remoteActionId"]
        type = event["eventStatus"]["type"]
        status = event["eventStatus"]["status"]
        detail = None
        if "failureCause" in event["eventStatus"]:
            detail = event["eventStatus"]["failureCause"]
        if coordinator:
            await coordinator.update_command_history(action_id, {"status": status, "source": "Callback"})
        _LOGGER.debug("---------- END _handle_webhook")

    def register_webhook(self):
        if not WEBHOOK_ID in self._hass.data.setdefault(WEBHOOK_DOMAIN, {}):
            webhook.async_register(self._hass, DOMAIN, "Stellantis Vehicles", WEBHOOK_ID, self._handle_webhook)

    async def remove_webhooks(self):
        if WEBHOOK_ID in self._hass.data.setdefault(WEBHOOK_DOMAIN, {}):
            webhook.async_unregister(self._hass, WEBHOOK_ID)

    async def resize_and_save_picture(self, url, vin):
        public_path = self._hass.config.path("www")

        if not os.path.isdir(public_path):
            _LOGGER.warning("Folder \"www\" not found in configuration folder")
            return url

        stellantis_path = f"{public_path}/{IMAGE_PATH}"
        if not os.path.isdir(stellantis_path):
            os.mkdir(stellantis_path)

        new_image_path = f"{stellantis_path}/{vin}.png"
        new_image_url = f"/local/{IMAGE_PATH}/{vin}.png"
        if os.path.isfile(new_image_path):
            return new_image_url

        image = await self._hass.async_add_executor_job(urlopen, url)
        with Image.open(image) as im:
            im = ImageOps.pad(im, (400, 400))
        im.save(new_image_path)
        return new_image_url

    async def refresh_token(self):
        _LOGGER.debug("---------- START refresh_token")
        # Aggiungere notifica frontend di rinconfigurazione oauth token in caso di errore
        token_expiry = datetime.fromisoformat(self.get_config("expires_in"))
        if token_expiry < (datetime.now() - timedelta(0, 10)):
            url = self.apply_query_params(OAUTH_TOKEN_URL, OAUTH_REFRESH_TOKEN_QUERY_PARAMS)
            headers = self.apply_headers_params(OAUTH_TOKEN_HEADERS)
            token_request = await self.make_http_request(url, 'POST', headers)
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(token_request)
            new_config = {
                "access_token": token_request["access_token"],
                "refresh_token": token_request["refresh_token"],
                "expires_in": (datetime.now() + timedelta(0, int(token_request["expires_in"]))).isoformat()
            }
            self.save_config(new_config)
            new_config["mobile_app"] = self.get_config("mobile_app")
            new_config["callback_id"] = self.get_config("callback_id")
            self._hass.config_entries.async_update_entry(self._entry, data=new_config)
        _LOGGER.debug("---------- END refresh_token")


    async def get_user_vehicles(self):
        _LOGGER.debug("---------- START get_user_vehicles")
        await self.refresh_token()
        if not self._vehicles:
            url = self.apply_query_params(CAR_API_VEHICLES_URL, CLIENT_ID_QUERY_PARAM)
            headers = self.apply_headers_params(CAR_API_HEADERS)
            vehicles_request = await self.make_http_request(url, 'GET', headers)
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(vehicles_request)
            for vehicle in vehicles_request["_embedded"]["vehicles"]:
                self._vehicles.append({
                    "vehicle_id": vehicle["id"],
                    "vin": vehicle["vin"],
                    "type": vehicle["motorization"],
                    "picture": await self.resize_and_save_picture(vehicle["pictures"][0], vehicle["vin"])
                })
        _LOGGER.debug("---------- END get_user_vehicles")
        return self._vehicles

    async def get_vehicle_status(self):
        _LOGGER.debug("---------- START get_vehicle_status")
        await self.refresh_token()
        url = self.apply_query_params(CAR_API_GET_VEHICLE_STATUS_URL, CLIENT_ID_QUERY_PARAM)
        headers = self.apply_headers_params(CAR_API_HEADERS)
        vehicle_status_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(vehicle_status_request)
        _LOGGER.debug("---------- END get_vehicle_status")
        return vehicle_status_request

    async def get_callback_id(self):
        _LOGGER.debug("---------- START get_callback_id")
        await self.refresh_token()
        callback_target = get_url(self._hass, prefer_external=True, prefer_cloud=True) + "/api/webhook/" + WEBHOOK_ID
        callback_id = self.get_config("callback_id")
        # Check for existing callback
        if not callback_id:
            _LOGGER.debug("check_callback")
            url = self.apply_query_params(CAR_API_CALLBACK_URL, CLIENT_ID_QUERY_PARAM)
            headers = self.apply_headers_params(CAR_API_HEADERS)
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            try:
                callbacks_request =  await self.make_http_request(url, 'GET', headers)
                _LOGGER.debug(callbacks_request)
                for callback in callbacks_request["_embedded"]["callbacks"]:
                    if callback["status"] == "Running" and callback["subscribe"]["callback"]["webhook"]["target"] == callback_target:
                        callback_id = callback["id"]
            except Exception as e:
                _LOGGER.debug(str(e))
        # Create callback
        if not callback_id:
            _LOGGER.debug("create_callback")
            url = self.apply_query_params(CAR_API_CALLBACK_URL, CLIENT_ID_QUERY_PARAM)
            headers = self.apply_headers_params(CAR_API_HEADERS)
            json = {
               "label": "HomeAssistant - Stellantis Vehicles",
               "type": ["Remote"],
               "callback": {
                   "webhook": {
                       "name": "HomeAssistant - Stellantis Vehicles",
                       "target": callback_target,
                       "attributes": [
                           {
                               "type": "Query",
                               "key": "vin",
                               "value": "$Vin"
                           }
                       ]
                   }
               }
            }
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(json)
            callback_request =  await self.make_http_request(url, 'POST', headers, None, json)
            _LOGGER.debug(callback_request)
            callback_id = callback_request["callbackId"]
        # Save callback id
        if callback_id:
            new_config = {
                "access_token": self.get_config("access_token"),
                "refresh_token": self.get_config("refresh_token"),
                "expires_in": self.get_config("expires_in"),
                "mobile_app": self.get_config("mobile_app"),
                "callback_id": callback_id
            }
            self.save_config(new_config)
            self._hass.config_entries.async_update_entry(self._entry, data=new_config)

        _LOGGER.debug("---------- END get_callback_id")
        return self.get_config("callback_id")

    async def delete_user_callback(self):
        _LOGGER.debug("---------- START delete_user_callback")
        await self.refresh_token()
        if self.get_config("callback_id"):
            url = self.apply_query_params(CAR_API_DELETE_CALLBACK_URL, CLIENT_ID_QUERY_PARAM)
            headers = self.apply_headers_params(CAR_API_HEADERS)
            delete_request = await self.make_http_request(url, 'DELETE', headers)
            _LOGGER.debug(url)
            _LOGGER.debug(headers)
            _LOGGER.debug(delete_request)
        _LOGGER.debug("---------- END delete_user_callback")
        return True

    async def get_action_status(self, action_id):
        _LOGGER.debug("---------- START get_action_status")
        await self.refresh_token()
        self._config["remote_action_id"] = action_id
        url = self.apply_query_params(CAR_API_CHECK_COMMAND_URL, CLIENT_ID_QUERY_PARAM)
        del self._config["remote_action_id"]
        headers = self.apply_headers_params(CAR_API_HEADERS)
        action_status_request = await self.make_http_request(url, 'GET', headers)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(action_status_request)
        _LOGGER.debug("---------- END get_action_status")
        return action_status_request

    async def send_command(self, json):
        _LOGGER.debug("---------- START send_command")
        await self.refresh_token()
        url = self.apply_query_params(CAR_API_SEND_COMMAND_URL, CLIENT_ID_QUERY_PARAM)
        headers = self.apply_headers_params(CAR_API_HEADERS)
        command_request = await self.make_http_request(url, 'POST', headers, None, json)
        _LOGGER.debug(url)
        _LOGGER.debug(headers)
        _LOGGER.debug(json)
        _LOGGER.debug(command_request)
        _LOGGER.debug("---------- END send_command")
        return command_request