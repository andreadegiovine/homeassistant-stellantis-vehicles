import logging
import voluptuous as vol
from aiohttp import web_response
from datetime import ( datetime, timedelta )
import urllib.parse

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant import config_entries
from homeassistant.helpers.selector import selector

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    MOBILE_APPS
)

from .stellantis import StellantisOauth
from homeassistant.helpers.network import get_url
from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_remove_panel

from pathlib import Path

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA_1 = vol.Schema({
    vol.Required(FIELD_MOBILE_APP): selector({ "select": { "options": list(MOBILE_APPS), "mode": "dropdown", "translation_key": FIELD_MOBILE_APP } }),
})

OAUTH_URL = '/stellantis-vehicles/oauth'
OAUTH_NAME = 'stellantis_vehicles:oauth'

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
        self.data = dict()
        self.stellantis = None
        self.stellantis_oauth_panel_exist = False
        self.vehicles = {}

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA_1
            )

        self.data.update(user_input)
        await self.async_set_unique_id(self.data["mobile_app"].lower())
        self._abort_if_unique_id_configured()
        return await self.async_step_oauth(user_input)

    async def async_step_oauth(self, user_input=None):
        self.data.update(user_input)
        self.hass.http.register_view(StellantisOauthView)
        self.stellantis = StellantisOauth(self.hass)
        self.stellantis.set_mobile_app(self.data["mobile_app"])
        oauth_panel_url = get_url(self.hass, prefer_external=True, prefer_cloud=True) + OAUTH_URL + "?url=" + urllib.parse.quote(self.stellantis.get_oauth_url()) + "&flow_id=" + self.flow_id
        return self.async_external_step(step_id="get_token", url=oauth_panel_url)

    async def async_step_get_token(self, request=None):
        self.stellantis.save_config({"oauth_code": request.query["oauth_code"]})

        try:
            token_request = await self.stellantis.get_access_token()
        except Exception as e:
            return self.async_external_step_done(next_step_id="user")

        self.data.update({
            "access_token": token_request["access_token"],
            "refresh_token": token_request["refresh_token"],
            "expires_in": (datetime.now() + timedelta(0, int(token_request["expires_in"]))).isoformat()
        })

        return self.async_external_step_done(next_step_id="final")


    async def async_step_final(self, user_input=None):
        return self.async_create_entry(title=self.data["mobile_app"], data=self.data)


class StellantisOauthView(HomeAssistantView):
    url = OAUTH_URL
    name = OAUTH_NAME
    requires_auth = False

    async def get(self, request):
        hass = request.app[KEY_HASS]

        url = get_url(hass, prefer_external=True, prefer_cloud=True)
        content = f"<script>window.location.replace('{url}');</script>"

        if "flow_id" in request.query:
            if "url" in request.query:
                url = request.query["url"]
                flow_id = request.query["flow_id"]
                content = f"""<h1>Connect your account</h1>
                             <ul>
                                 <li>Go to <a href="{url}" target="_blank">Stellantis login</a>;</li>
                                 <li>Complete the login procedure there too until you see "LOGIN SUCCESSFUL";</li>
                                 <li>Open your browser's DevTools (F12) and then the click on "Network" tab;</li>
                                 <li>Hit the final "OK" button, under "LOGIN SUCCESSFUL";</li>
                                 <li>Find in the network tab: xxxx://oauth2redirect....?code=<copy this part>&scope=openid...;</li>
                             </ul>
                             <form action="" method="get">
                                 <input type="hidden" name="flow_id" value="{flow_id}">
                                 <input type="text" name="oauth_code" required>
                                 <button type="submit">Confirm</button>
                             </form>"""
            if "oauth_code" in request.query:
                await hass.config_entries.flow.async_configure(
                    flow_id=request.query["flow_id"], user_input=request
                )
                content = "<script>window.close()</script>"

        return web_response.Response(
            headers={"content-type": "text/html"},
            text=content,
        )