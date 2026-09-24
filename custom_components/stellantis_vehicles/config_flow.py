import logging
import voluptuous as vol
from datetime import timedelta
from uuid import uuid4

from homeassistant.config_entries import ( ConfigFlow, SOURCE_REAUTH, SOURCE_RECONFIGURE )
from homeassistant.helpers.selector import selector
from homeassistant.helpers import translation
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_EMAIL
)

from .utils import get_datetime, log_call
from .stellantis import StellantisOauth
from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    MOBILE_APPS,
    FIELD_MOBILE_APP,
    FIELD_COUNTRY_CODE,
    FIELD_OAUTH_MANUAL_MODE,
    FIELD_OAUTH_CODE,
    FIELD_OAUTH_CODE_URL,
    FIELD_REMOTE_COMMANDS,
    FIELD_SMS_CODE,
    FIELD_PIN_CODE,
    FIELD_NOTIFICATIONS,
    FIELD_ANONYMIZE_LOGS,
    FIELD_RECONFIGURE,
    MQTT_REFRESH_TOKEN_TTL,
    OAUTH_CODE_URL,
    TRANSLATION_PLACEHOLDERS
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

def OAUTH_REMOTE_SCHEMA(default_oauth_code_url=None):
    return vol.Schema({
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(FIELD_OAUTH_CODE_URL, default=default_oauth_code_url or OAUTH_CODE_URL): str
    })

def OTP_CONFIGURE_SCHEMA(default_remote_commands=False):
    return vol.Schema({
        vol.Required(FIELD_REMOTE_COMMANDS, default=default_remote_commands): bool
    })

OTP_SCHEMA = vol.Schema({
    vol.Required(FIELD_SMS_CODE): str,
    vol.Required(FIELD_PIN_CODE): str
})

def OPTIONS_SCHEMA(reconfig=None):
    defaults = {
        FIELD_NOTIFICATIONS: True,
        FIELD_ANONYMIZE_LOGS: True
    }
    if reconfig:
        defaults.update(reconfig)
    return vol.Schema({
        vol.Required(FIELD_NOTIFICATIONS, default=defaults[FIELD_NOTIFICATIONS]): bool,
        vol.Required(FIELD_ANONYMIZE_LOGS, default=defaults[FIELD_ANONYMIZE_LOGS]): bool
    })

RECONFIGURE_SCHEMA = vol.Schema({
    vol.Required(FIELD_RECONFIGURE): selector({ "select": { "options": ['options', 'oauth', FIELD_REMOTE_COMMANDS], "translation_key": FIELD_RECONFIGURE } })
})

class StellantisVehiclesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = INTEGRATION_VERSION

    def __init__(self) -> None:
        self.data = dict()
        self.stellantis = None
        self.stellantis_oauth_panel_exist = False
        self.vehicles = {}
        self.errors = {}
        self._translations = None
        self._enable_remote_commands = False
        self._discovered_oauth_code_url = None
        self._discovered_addon = None


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


    def configured_oauth_code_url(self):
        # A further account defaults to the login service the existing ones
        # already use (e.g. a local add-on) instead of the shared instance.
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(FIELD_OAUTH_CODE_URL):
                return entry.data[FIELD_OAUTH_CODE_URL]
        return None


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
            default_oauth_code_url = self.data.get(FIELD_OAUTH_CODE_URL) or self.configured_oauth_code_url()
            return self.async_show_form(step_id="oauth_remote", data_schema=OAUTH_REMOTE_SCHEMA(default_oauth_code_url), description_placeholders=TRANSLATION_PLACEHOLDERS)

        try:
            code_request = await self.stellantis.get_oauth_code(user_input[CONF_EMAIL], user_input[CONF_PASSWORD], user_input.get(FIELD_OAUTH_CODE_URL, OAUTH_CODE_URL))
        except Exception as e:
            message = self.get_error_message("get_oauth_code", e)
            if self.source == SOURCE_RECONFIGURE:
                return self.async_abort(reason=message)
            self.errors[FIELD_OAUTH_MANUAL_MODE] = message
            await self.stellantis.hass_notify("get_oauth_code")
            return await self.async_step_oauth_mode()

        self.data.update({FIELD_OAUTH_CODE_URL: user_input.get(FIELD_OAUTH_CODE_URL, OAUTH_CODE_URL)})
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
                message = self.get_error_message("get_access_token", e)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_abort(reason=message)
                self.errors[FIELD_OAUTH_MANUAL_MODE] = message
                await self.stellantis.hass_notify("access_token_error")
                return await self.async_step_oauth_mode()

            oauth = {"oauth": {
                "access_token": token_request["access_token"],
                "refresh_token": token_request["refresh_token"],
                "expires_in": (get_datetime() + timedelta(0, int(token_request["expires_in"]))).isoformat()
            }}
            self.data.update(oauth)
            self.stellantis.save_config(oauth)
            # Default to the account's current setting (e.g. on reauth/reconfigure)
            # instead of always showing the box unchecked, which would otherwise
            # silently turn remote commands off for an account that already has
            # them enabled if the form is submitted as-is.
            default_remote_commands = self.data.get(FIELD_REMOTE_COMMANDS, False)
            return self.async_show_form(step_id="get_access_token", data_schema=OTP_CONFIGURE_SCHEMA(default_remote_commands))

        self.data.update({FIELD_REMOTE_COMMANDS: user_input[FIELD_REMOTE_COMMANDS]})
        self.stellantis.save_config({FIELD_REMOTE_COMMANDS: self.data[FIELD_REMOTE_COMMANDS]})

        if self.source == SOURCE_RECONFIGURE:
            return await self.async_step_final()
        elif self.data[FIELD_REMOTE_COMMANDS]:
            return await self.async_step_otp()
        else:
            # Only fabricate a synthetic id on first setup - reauth already
            # carried the account's existing one (real or synthetic) into
            # self.data, and generating a new one here would needlessly orphan
            # the vehicle image cache on every reauth.
            if "customer_id" not in self.data:
                self.data.update({"customer_id": "MN-" + str(uuid4()).replace("-", "")[:16]})
            return await self.async_step_options()


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

        if self.source == SOURCE_RECONFIGURE:
            self._enable_remote_commands = True
            return await self.async_step_final()
        else:
            return await self.async_step_options()


    async def async_step_options(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="options", data_schema=OPTIONS_SCHEMA(self.data))

        self.data.update(user_input)
        return await self.async_step_final()


    async def async_step_final(self, user_input=None):
        unique_id = f"{str(self.data["customer_id"])}_{str(self.data["mobile_app"])}_{str(self.data["country_code"])}"

        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self.data, reload_even_if_entry_is_unchanged=False)
        if self.source == SOURCE_RECONFIGURE:
            if self._get_reconfigure_entry().unique_id != unique_id:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            if self._enable_remote_commands:
                self.data.update({FIELD_REMOTE_COMMANDS: True})
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=self.data, reload_even_if_entry_is_unchanged=False, unique_id=unique_id)

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self.data[FIELD_MOBILE_APP], data=self.data)


    async def async_step_reconfigure(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reconfigure", data_schema=RECONFIGURE_SCHEMA)

        await self.init_translations()
        # ConfigEntry.runtime_data is only a type annotation, not a real
        # attribute with a default: HA deletes it on unload and never sets it
        # before the first successful setup, so a plain `.runtime_data` here
        # can raise AttributeError instead of just being None.
        self.stellantis = getattr(self._get_reconfigure_entry(), "runtime_data", None)
        if self.stellantis is None:
            # Setup failed and is being retried (e.g. a Stellantis backend
            # outage), so there is nothing to reconfigure yet.
            return self.async_abort(reason=self.get_error_message("not_loaded"))
        self.data = dict(self.stellantis._entry.data)

        if user_input[FIELD_RECONFIGURE] == FIELD_REMOTE_COMMANDS:
            self.stellantis.disable_remote_commands()
            return await self.async_step_otp()
        elif user_input[FIELD_RECONFIGURE] == "oauth":
            return await self.async_step_oauth_mode()
        else:
            return await self.async_step_options()


    async def async_step_hassio(self, discovery_info: HassioServiceInfo):
        # A Supervisor add-on (e.g. "Stellantis Login Worker") announced a
        # local login service: {"host": <add-on hostname>, "port": <port>}.
        host = discovery_info.config.get("host")
        port = discovery_info.config.get("port")
        if not host or not port:
            return self.async_abort(reason="invalid_discovery_info")

        # One flow per add-on; "Ignore" on the discovery card sticks.
        await self.async_set_unique_id(discovery_info.uuid)
        self._abort_if_unique_id_configured()

        self._discovered_oauth_code_url = f"http://{host}:{port}"
        self._discovered_addon = discovery_info.name

        entries = self._async_current_entries(include_ignore=False)
        if entries and all(entry.data.get(FIELD_OAUTH_CODE_URL) == self._discovered_oauth_code_url for entry in entries):
            return self.async_abort(reason="already_configured")

        self.context["title_placeholders"] = {"addon": self._discovered_addon}
        return await self.async_step_hassio_confirm()


    async def async_step_hassio_confirm(self, user_input=None):
        placeholders = {"addon": self._discovered_addon, "url": self._discovered_oauth_code_url}
        if user_input is None:
            return self.async_show_form(step_id="hassio_confirm", description_placeholders=placeholders)

        # The login service is only used for (re)authentication, so existing
        # accounts just need the new URL in their entry data - no reload.
        entries = self._async_current_entries(include_ignore=False)
        if entries:
            for entry in entries:
                if entry.data.get(FIELD_OAUTH_CODE_URL) != self._discovered_oauth_code_url:
                    self.hass.config_entries.async_update_entry(entry, data={**entry.data, FIELD_OAUTH_CODE_URL: self._discovered_oauth_code_url})
            return self.async_abort(reason="login_service_updated", description_placeholders=placeholders)

        # No account yet: regular setup, with the add-on as login service.
        self.data.update({FIELD_OAUTH_CODE_URL: self._discovered_oauth_code_url})
        return await self.async_step_user()


    @log_call
    async def async_step_reauth(self, entry_data):
        self.data.update({FIELD_MOBILE_APP: entry_data[FIELD_MOBILE_APP], FIELD_COUNTRY_CODE: entry_data[FIELD_COUNTRY_CODE]})
        if FIELD_OAUTH_CODE_URL in entry_data:
            self.data.update({FIELD_OAUTH_CODE_URL: entry_data[FIELD_OAUTH_CODE_URL]})
        # Carried over so a plain reauth (just refreshing the OAuth token) can't
        # silently disable remote commands or replace the account's real
        # customer_id with a freshly generated one - both get merged back onto
        # the entry in async_step_final via data_updates.
        if FIELD_REMOTE_COMMANDS in entry_data:
            self.data.update({FIELD_REMOTE_COMMANDS: entry_data[FIELD_REMOTE_COMMANDS]})
        if "customer_id" in entry_data:
            self.data.update({"customer_id": entry_data["customer_id"]})
        return await self.async_step_reauth_confirm()


    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")

        return await self.async_step_oauth_mode()
