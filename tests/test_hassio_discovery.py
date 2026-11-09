"""Supervisor discovery of a local login service add-on.

An add-on that provides the worker's HTTP contract announces itself with
``POST /discovery``; Home Assistant hands the payload to ``async_step_hassio``.
The URL must end up in the config so the remote login form is pre-filled.
"""
import pytest

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.stellantis_vehicles.const import DOMAIN, FIELD_OAUTH_CODE_URL
from custom_components.stellantis_vehicles.discovery import login_service_url


def _info(config):
    return HassioServiceInfo(config=config, name="Stellantis Login Worker",
                             slug="stellantis_login_worker", uuid="0123456789abcdef")


@pytest.mark.parametrize("config,expected", [
    ({"host": "abc-stellantis_login_worker", "port": 3000}, "http://abc-stellantis_login_worker:3000"),
    ({"host": "192.168.10.10", "port": "8909"}, "http://192.168.10.10:8909"),
    ({"host": "worker"}, "http://worker"),
    ({"host": "worker", "port": 3000, "path": "/oauth-code"}, "http://worker:3000/oauth-code"),
    ({"host": "https://worker", "port": 3000}, None),
    ({"host": "worker/path", "port": 3000}, None),
    ({"host": "worker", "port": 70000}, None),
    ({"host": "worker", "port": "abc"}, None),
    ({"host": "", "port": 3000}, None),
    ({"port": 3000}, None),
    (None, None),
])
def test_login_service_url(config, expected):
    assert login_service_url(config) == expected


async def test_discovery_prefills_the_login_service_url(hass):
    # The manifest depends on frontend/http/webhook; mark them loaded instead of
    # standing up the real components (hass_frontend is not installed in tests).
    hass.config.components.update({"frontend", "http", "webhook"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=_info({"host": "abc-stellantis_login_worker", "port": 3000,
                    "addon": "Stellantis Login Worker"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mobile_app": "MyPeugeot"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "country"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"country_code": "DE"})
    assert result["step_id"] == "oauth_mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"oauth_manual_mode": False})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "oauth_remote"

    # Keys without a default carry a non-callable Undefined marker.
    defaults = {}
    for key in result["data_schema"].schema:
        try:
            defaults[key] = key.default()
        except TypeError:
            continue
    assert defaults[FIELD_OAUTH_CODE_URL] == "http://abc-stellantis_login_worker:3000"


async def test_invalid_discovery_aborts(hass):
    hass.config.components.update({"frontend", "http", "webhook"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_HASSIO},
        data=_info({"port": 3000}),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery_info"
