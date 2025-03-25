import logging
import voluptuous as vol
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.helpers.selector import selector
from homeassistant.helpers import translation

from .utils import get_datetime
from .stellantis import StellantisOauth
from .const import (
    DOMAIN,
    MOBILE_APPS,
    FIELD_MOBILE_APP,
    FIELD_COUNTRY_CODE,
    FIELD_OAUTH_CODE,
    FIELD_SMS_CODE,
    FIELD_PIN_CODE
)

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_SCHEMA = vol.Schema({
    vol.Required(FIELD_MOBILE_APP): selector({ "select": { "options": list(MOBILE_APPS), "mode": "dropdown", "translation_key": FIELD_MOBILE_APP } })
})

def COUNTRY_SCHEMA(mobile_app):
    return vol.Schema({
        vol.Required(FIELD_COUNTRY_CODE): selector({ "select": { "options": list(MOBILE_APPS[mobile_app]["configs"]), "mode": "dropdown", "translation_key": FIELD_COUNTRY_CODE } })
    })

OAUTH_SCHEMA = vol.Schema({
    vol.Required(FIELD_OAUTH_CODE): str
})

OTP_SCHEMA = vol.Schema({
    vol.Required(FIELD_SMS_CODE): str,
    vol.Required(FIELD_PIN_CODE): str
})

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
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

        return await self.async_step_oauth()


    async def async_step_oauth(self, user_input=None):
        await self.init_translations()

        self.stellantis = StellantisOauth(self.hass)
        self.stellantis.set_mobile_app(self.data[FIELD_MOBILE_APP], self.data[FIELD_COUNTRY_CODE])

        if user_input is None:
            errors = self.errors
            self.errors = {}
            oauth_link = f"[{self.data[FIELD_MOBILE_APP]}]({self.stellantis.get_oauth_url()})"
            oauth_label = self.get_translation("component.stellantis_vehicles.config.step.oauth.data.oauth_code").replace(" ", "_").upper()
            oauth_devtools = f"\n\n>***://oauth2redirect...?code=`{oauth_label}`&scope=openid..."
            return self.async_show_form(step_id="oauth", data_schema=OAUTH_SCHEMA, description_placeholders={"oauth_link": oauth_link, "oauth_label": oauth_label, "oauth_devtools": oauth_devtools}, errors=errors)

        self.data.update(user_input)

        self.stellantis.save_config({"oauth_code": self.data[FIELD_OAUTH_CODE]})

        try:
            token_request = await self.stellantis.get_access_token()
        except Exception as e:
            self.errors[FIELD_OAUTH_CODE] = self.get_error_message("get_access_token", e)
            return await self.async_step_oauth()

        self.data.update({
            "access_token": token_request["access_token"],
            "refresh_token": token_request["refresh_token"],
            "expires_in": (get_datetime() + timedelta(0, int(token_request["expires_in"]))).isoformat()
        })

        self.stellantis.save_config({"access_token": self.data["access_token"]})

        try:
            user_info_request = await self.stellantis.get_user_info()
        except Exception as e:
            self.errors[FIELD_OAUTH_CODE] = self.get_error_message("get_user_info", e)
            return await self.async_step_oauth()

        if not user_info_request or "customer" not in user_info_request[0]:
            self.errors[FIELD_OAUTH_CODE] = self.get_error_message("missing_user_info")
            return await self.async_step_oauth()

        self.data.update({"customer_id": user_info_request[0]["customer"]})

        return await self.async_step_otp()


    async def async_step_otp(self, user_input=None):
        if user_input is None:
            try:
                await self.stellantis.get_otp_sms()
            except Exception as e:
                self.errors[FIELD_OAUTH_CODE] = self.get_error_message("get_otp_sms", e)
                return await self.async_step_oauth()
            return self.async_show_form(step_id="otp", data_schema=OTP_SCHEMA)

        try:
            await self.hass.async_add_executor_job(self.stellantis.new_otp, user_input[FIELD_SMS_CODE], user_input[FIELD_PIN_CODE])
            otp_token_request = await self.stellantis.get_mqtt_access_token()
        except Exception as e:
            self.errors[FIELD_OAUTH_CODE] = self.get_error_message("get_mqtt_access_token", e)
            return await self.async_step_oauth()

        self.data.update({"mqtt": {
            "access_token": otp_token_request["access_token"],
            "refresh_token": otp_token_request["refresh_token"],
            "expires_in": (get_datetime() + timedelta(0, int(otp_token_request["expires_in"]))).isoformat()
        }})

        return await self.async_step_final()


    async def async_step_final(self, user_input=None):
        if self.source == config_entries.SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self.data, reload_even_if_entry_is_unchanged=False)

        await self.async_set_unique_id(self.data[FIELD_MOBILE_APP].lower()+str(self.data["access_token"][:5]))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self.data[FIELD_MOBILE_APP], data=self.data)


    async def async_step_reauth(self, entry_data):
        _LOGGER.debug("---------- START async_step_reauth")
        self.data.update({FIELD_MOBILE_APP: entry_data[FIELD_MOBILE_APP], FIELD_COUNTRY_CODE: entry_data[FIELD_COUNTRY_CODE]})
        _LOGGER.debug("---------- END async_step_reauth")
        return await self.async_step_reauth_confirm()


    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")

        return await self.async_step_oauth()