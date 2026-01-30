import logging
import voluptuous as vol
from datetime import timedelta
from uuid import uuid4

from homeassistant.config_entries import ( ConfigFlow, SOURCE_REAUTH, SOURCE_RECONFIGURE )
from homeassistant.helpers.selector import selector
from homeassistant.helpers import translation
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_EMAIL
)

from .utils import get_datetime
from .stellantis import StellantisOauth
from .const import (
    DOMAIN,
    MOBILE_APPS,
    FIELD_MOBILE_APP,
    FIELD_COUNTRY_CODE,
    FIELD_OAUTH_MANUAL_MODE,
    FIELD_OAUTH_CODE,
    FIELD_REMOTE_COMMANDS,
    FIELD_SMS_CODE,
    FIELD_PIN_CODE,
    MQTT_REFRESH_TOKEN_TTL
)

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_SCHEMA = vol.Schema({
    vol.Required(FIELD_MOBILE_APP): selector({ "select": { "options": list(MOBILE_APPS), "mode": "dropdown", "translation_key": FIELD_MOBILE_APP } })
})

def COUNTRY_SCHEMA(mobile_app):
    return vol.Schema({
        vol.Required(FIELD_COUNTRY_CODE): selector({ "select": { "options": list(MOBILE_APPS[mobile_app]["configs"]), "mode": "dropdown", "translation_key": FIELD_COUNTRY_CODE } })
    })

OAUTH_MODE_SCHEMA = vol.Schema({
        vol.Required(FIELD_OAUTH_MANUAL_MODE, default=False): bool
})

OAUTH_MANUAL_SCHEMA = vol.Schema({
    vol.Required(FIELD_OAUTH_CODE): str
})

OAUTH_REMOTE_SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_PASSWORD): str
})

OTP_CONFIGURE_SCHEMA = vol.Schema({
    vol.Required(FIELD_REMOTE_COMMANDS, default=False): bool
})

OTP_SCHEMA = vol.Schema({
    vol.Required(FIELD_SMS_CODE): str,
    vol.Required(FIELD_PIN_CODE): str
})

class StellantisVehiclesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 4

    def __init__(self) -> None:
        self.data = dict()
        self.stellantis = None
        self.stellantis_oauth_panel_exist = False
        self.vehicles = {}
        self.errors = {}
        self._translations = None


    async def init_translations(self):
        if not self._translations:
            self._translations = await translation.async_get_translations(self.hass, self.hass.config.language, "config", {DOMAIN})


    def get_translation(self, path, default = None):
        return self._translations.get(path, default)


    def get_error_message(self, error, message = None):
        result = str(self.get_translation(f"component.stellantis_vehicles.config.error.{error}", error))
        if message:
            result = result + ": " + str(message)
        return result


    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=MOBILE_APP_SCHEMA)

        self.data.update(user_input)
        return await self.async_step_country()


    async def async_step_country(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="country", data_schema=COUNTRY_SCHEMA(self.data[FIELD_MOBILE_APP]))

        self.data.update(user_input)
        return await self.async_step_oauth_mode()


    async def async_step_oauth_mode(self, user_input=None):
        if user_input is None:
            errors = self.errors
            self.errors = {}
            return self.async_show_form(step_id="oauth_mode", data_schema=OAUTH_MODE_SCHEMA, errors=errors)

        await self.init_translations()
        self.stellantis = StellantisOauth(self.hass)
        self.stellantis.set_mobile_app(self.data[FIELD_MOBILE_APP], self.data[FIELD_COUNTRY_CODE])

        if user_input[FIELD_OAUTH_MANUAL_MODE]:
            return await self.async_step_oauth_manual()

        return await self.async_step_oauth_remote()


    async def async_step_oauth_remote(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="oauth_remote", data_schema=OAUTH_REMOTE_SCHEMA)

        try:
            code_request = await self.stellantis.get_oauth_code(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        except Exception as e:
            self.errors[FIELD_OAUTH_MANUAL_MODE] = self.get_error_message("get_oauth_code", e)
            await self.stellantis.hass_notify("get_oauth_code")
            return await self.async_step_oauth_mode()

        self.stellantis.save_config({"oauth_code": code_request["code"]})
        return await self.async_step_get_access_token()


    async def async_step_oauth_manual(self, user_input=None):
        if user_input is None:
            errors = self.errors
            self.errors = {}
            oauth_link = f"[{self.data[FIELD_MOBILE_APP]}]({self.stellantis.get_oauth_url()})"
            oauth_label = self.get_translation("component.stellantis_vehicles.config.step.oauth_manual.data.oauth_code").replace(" ", "_").upper()
            oauth_devtools = f"\n\n>***://oauth2redirect...?code=`{oauth_label}`&scope=openid..."
            return self.async_show_form(step_id="oauth_manual", data_schema=OAUTH_MANUAL_SCHEMA, description_placeholders={"oauth_link": oauth_link, "oauth_label": oauth_label, "oauth_devtools": oauth_devtools}, errors=errors)

        self.stellantis.save_config({"oauth_code": user_input[FIELD_OAUTH_CODE]})
        return await self.async_step_get_access_token()


    async def async_step_get_access_token(self, user_input=None):
        if user_input is None:
            try:
                token_request = await self.stellantis.get_access_token()
            except Exception as e:
                self.errors[FIELD_OAUTH_MANUAL_MODE] = self.get_error_message("get_access_token", e)
                await self.stellantis.hass_notify("access_token_error")
                return await self.async_step_oauth_mode()
            oauth = {"oauth": {
                "access_token": token_request["access_token"],
                "refresh_token": token_request["refresh_token"],
                "expires_in": (get_datetime() + timedelta(0, int(token_request["expires_in"]))).isoformat()
            }}
            self.data.update(oauth)
            self.stellantis.save_config(oauth)
            return self.async_show_form(step_id="get_access_token", data_schema=OTP_CONFIGURE_SCHEMA)

        self.data.update({FIELD_REMOTE_COMMANDS: user_input[FIELD_REMOTE_COMMANDS]})
        self.stellantis.save_config({FIELD_REMOTE_COMMANDS: self.data[FIELD_REMOTE_COMMANDS]})
        if self.data[FIELD_REMOTE_COMMANDS]:
            return await self.async_step_otp()
        else:
            self.data.update({"customer_id": "MN-" + str(uuid4()).replace("-", "")[:16]})
            return await self.async_step_final()


    async def async_step_otp(self, user_input=None):
        if user_input is None:
            try:
                user_info_request = await self.stellantis.get_user_info()
            except Exception as e:
                message = self.get_error_message("get_user_info", e)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_abort(reason=message)
                self.errors[FIELD_OAUTH_MANUAL_MODE] = message
                return await self.async_step_oauth_mode()

            if not user_info_request or "customer" not in user_info_request[0]:
                message = self.get_error_message("missing_user_info")
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_abort(reason=message)
                self.errors[FIELD_OAUTH_MANUAL_MODE] = message
                return await self.async_step_oauth_mode()

            self.data.update({"customer_id": user_info_request[0]["customer"]})
            self.stellantis.save_config({"customer_id": self.data["customer_id"]})

            try:
                await self.stellantis.get_otp_sms()
            except Exception as e:
                message = self.get_error_message("get_otp_sms", e)
                await self.stellantis.hass_notify("otp_error")
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_abort(reason=message)
                self.errors[FIELD_OAUTH_MANUAL_MODE] = message
                return await self.async_step_oauth_mode()

            return self.async_show_form(step_id="otp", data_schema=OTP_SCHEMA)

        try:
            await self.hass.async_add_executor_job(self.stellantis.new_otp, user_input[FIELD_SMS_CODE], user_input[FIELD_PIN_CODE])
            otp_token_request = await self.stellantis.get_mqtt_access_token()
        except Exception as e:
            message = self.get_error_message("get_mqtt_access_token_" + str(e).lower().replace(":", "_"), e)
            await self.stellantis.hass_notify("otp_error")
            if not message:
                message = self.get_error_message("get_mqtt_access_token", e)
            if self.source == SOURCE_RECONFIGURE:
                return self.async_abort(reason=message)
            self.errors[FIELD_OAUTH_MANUAL_MODE] = message
            return await self.async_step_oauth_mode()

        self.data.update({"mqtt": {
            "access_token": otp_token_request["access_token"],
            "refresh_token": otp_token_request["refresh_token"],
            "expires_in": (get_datetime() + timedelta(0, int(otp_token_request["expires_in"]))).isoformat(),
            # The refresh token seems to be valid for 7 days, so we need to get a new one from time to time.
            "refresh_token_expires_at": (get_datetime() + timedelta(minutes=int(MQTT_REFRESH_TOKEN_TTL))).isoformat()
        }})

        return await self.async_step_final()


    async def async_step_final(self, user_input=None):
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self.data, reload_even_if_entry_is_unchanged=False)
        if self.source == SOURCE_RECONFIGURE:
            if self._get_reconfigure_entry().unique_id != str(self.data["customer_id"]):
                await self.async_set_unique_id(str(self.data["customer_id"]))
                self._abort_if_unique_id_configured()
            self.data.update({FIELD_REMOTE_COMMANDS: True})
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=self.data, reload_even_if_entry_is_unchanged=False, unique_id=str(self.data["customer_id"]))

        await self.async_set_unique_id(str(self.data["customer_id"]))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self.data[FIELD_MOBILE_APP], data=self.data)


    async def async_step_reconfigure(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reconfigure")
        await self.init_translations()
        self.stellantis = self.hass.data[DOMAIN][self._reconfigure_entry_id]
        self.data = dict(self.stellantis._entry.data)
        self.stellantis.disable_remote_commands()
        return await self.async_step_otp()


    async def async_step_reauth(self, entry_data):
        _LOGGER.debug("---------- START async_step_reauth")
        self.data.update({FIELD_MOBILE_APP: entry_data[FIELD_MOBILE_APP], FIELD_COUNTRY_CODE: entry_data[FIELD_COUNTRY_CODE]})
        _LOGGER.debug("---------- END async_step_reauth")
        return await self.async_step_reauth_confirm()


    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")

        return await self.async_step_oauth_mode()
