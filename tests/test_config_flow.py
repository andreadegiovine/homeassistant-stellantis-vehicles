"""Config flow of every client: new entries, reauthentication and reconfiguration."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN, INTEGRATION_VERSION

from . import uconnect_fakes as uc
from .leapmotor_fakes import FakeCloud as LeapmotorCloud, make_certificate

PSA_OAUTH = "custom_components.stellantis_vehicles.config_flow.StellantisOauth"


@pytest.fixture(autouse=True)
def no_setup(hass):
    """Entries are only created here: their setup is tested elsewhere."""
    hass.config.components.update({"frontend", "http", "webhook"})
    with patch("custom_components.stellantis_vehicles.async_setup_entry", AsyncMock(return_value=True)), \
         patch("custom_components.stellantis_vehicles.async_unload_entry", AsyncMock(return_value=True)):
        yield


@pytest.fixture
def uconnect(hass):
    cloud = uc.FakeCloud()
    with patch("custom_components.stellantis_vehicles.client.uconnect.client.Client", cloud.client_class):
        yield cloud


@pytest.fixture
def leapmotor(hass):
    from custom_components.stellantis_vehicles.client.leapmotor.client import LeapmotorVehicles
    cloud = LeapmotorCloud()

    def start_session(self):
        self._session = cloud

    with patch.object(LeapmotorVehicles, "start_session", start_session), \
         patch("custom_components.stellantis_vehicles.client.leapmotor.client.async_ensure_app_certificate", return_value=make_certificate()[:2]):
        yield cloud


async def _start(hass, mobile_app):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"mobile_app": mobile_app})


async def _configure(hass, result, data):
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


OPTIONS = {"notifications": True, "anonymize_logs": True}


async def test_every_app_is_offered(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    options = result["data_schema"].schema["mobile_app"].config["options"]
    assert options == ["MyPeugeot", "MyCitroen", "MyDS", "MyOpel", "MyVauxhall", "Leapmotor", "Uconnect"]


# -- PSA (unchanged flow) -------------------------------------------------------

async def test_psa_flow_creates_an_entry_without_a_client_key(hass):
    with patch(f"{PSA_OAUTH}.get_oauth_code", AsyncMock(return_value={"code": "abc"})) as code, \
         patch(f"{PSA_OAUTH}.get_access_token", AsyncMock(return_value={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})):
        result = await _start(hass, "MyPeugeot")
        assert result["step_id"] == "country"
        result = await _configure(hass, result, {"country_code": "IT"})
        assert result["step_id"] == "oauth_mode"
        result = await _configure(hass, result, {"oauth_manual_mode": False})
        assert result["step_id"] == "oauth_remote"
        result = await _configure(hass, result, {"email": "user@example.com", "password": "secret"})
        assert code.await_args.args[:2] == ("user@example.com", "secret")
        assert result["step_id"] == "get_access_token"
        result = await _configure(hass, result, {"remote_commands": False})
        assert result["step_id"] == "options"
        result = await _configure(hass, result, OPTIONS)
    assert result["type"] == "create_entry"
    data = result["data"]
    # PSA entries keep their layout: no client key, PSA is the default.
    assert "client" not in data
    assert (data["mobile_app"], data["country_code"], data["remote_commands"]) == ("MyPeugeot", "IT", False)
    assert data["oauth"]["access_token"] == "at" and data["customer_id"].startswith("MN-")


async def test_psa_reauth_asks_for_a_new_login(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, unique_id="AP-1_MyPeugeot_IT", data={
        "mobile_app": "MyPeugeot", "country_code": "IT", "customer_id": "AP-1", "remote_commands": True,
        "oauth": {"access_token": "a", "refresh_token": "r", "expires_in": (dt_util.utcnow() + timedelta(hours=1)).isoformat()}})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await _configure(hass, result, {})
    assert result["step_id"] == "oauth_mode"


async def test_psa_reconfigure_offers_its_menu(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, unique_id="AP-1_MyPeugeot_IT", data={"mobile_app": "MyPeugeot", "country_code": "IT", "customer_id": "AP-1"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    assert "reconfigure" in result["data_schema"].schema


# -- Uconnect -------------------------------------------------------------------

async def test_uconnect_flow_creates_an_entry(hass, uconnect):
    result = await _start(hass, "Uconnect")
    assert result["step_id"] == "uconnect"
    assert len(result["data_schema"].schema["uconnect_brand"].config["options"]) == 20

    result = await _configure(hass, result, {"uconnect_brand": "jeep_eu", "email": uc.EMAIL, "password": "wrong", "pin_code": uc.PIN})
    assert result["errors"] == {"base": "uconnect_login"}

    result = await _configure(hass, result, {"uconnect_brand": "jeep_eu", "email": f" {uc.EMAIL} ", "password": uc.PASSWORD, "pin_code": f" {uc.PIN} "})
    assert uconnect.brand.name == "JEEP_EU"
    assert result["step_id"] == "options"
    assert "mqtt_live_updates" not in [str(key) for key in result["data_schema"].schema]
    result = await _configure(hass, result, OPTIONS)
    assert result["type"] == "create_entry"
    data = result["data"]
    assert (data["client"], data["mobile_app"], data["uconnect_brand"], data["email"], data["pin_code"], data["remote_commands"]) == ("uconnect", "Uconnect", "jeep_eu", uc.EMAIL, uc.PIN, True)
    assert data["customer_id"] == f"UC-{uc.UID}"
    assert result["result"].unique_id == f"UC-{uc.UID}_Uconnect_"

    # The same account cannot be added twice.
    result = await _start(hass, "Uconnect")
    result = await _configure(hass, result, {"uconnect_brand": "jeep_eu", "email": uc.EMAIL, "password": uc.PASSWORD})
    result = await _configure(hass, result, OPTIONS)
    assert (result["type"], result["reason"]) == ("abort", "already_configured")


async def test_uconnect_without_pin_and_with_the_cloud_down(hass, uconnect):
    uconnect.down = True
    result = await _start(hass, "Uconnect")
    result = await _configure(hass, result, {"uconnect_brand": "fiat_us", "email": uc.EMAIL, "password": uc.PASSWORD})
    assert result["errors"] == {"base": "uconnect_connection"}
    # The brand chosen is kept in the form shown again.
    assert result["data_schema"]({"email": uc.EMAIL, "password": "x"})["uconnect_brand"] == "fiat_us"

    uconnect.down = False
    result = await _configure(hass, result, {"uconnect_brand": "fiat_us", "email": uc.EMAIL, "password": uc.PASSWORD})
    result = await _configure(hass, result, OPTIONS)
    assert (result["data"]["pin_code"], result["data"]["remote_commands"]) == ("", False)


def _uconnect_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, unique_id=f"UC-{uc.UID}_Uconnect_", data={
        "client": "uconnect", "mobile_app": "Uconnect", "country_code": "", "customer_id": f"UC-{uc.UID}",
        "uconnect_brand": "fiat_eu", "email": uc.EMAIL, "password": uc.PASSWORD, "pin_code": "", "remote_commands": False, **OPTIONS})
    entry.add_to_hass(hass)
    return entry


async def test_uconnect_reconfigure_adds_the_pin(hass, uconnect):
    entry = _uconnect_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "uconnect"
    defaults = result["data_schema"]({"password": uc.PASSWORD})
    assert (defaults["uconnect_brand"], defaults["email"]) == ("fiat_eu", uc.EMAIL)
    result = await _configure(hass, result, {"uconnect_brand": "fiat_eu", "email": uc.EMAIL, "password": uc.PASSWORD, "pin_code": uc.PIN})
    result = await _configure(hass, result, OPTIONS)
    assert (result["type"], result["reason"]) == ("abort", "reconfigure_successful")
    assert (entry.data["pin_code"], entry.data["remote_commands"]) == (uc.PIN, True)


async def test_uconnect_reauth(hass, uconnect):
    entry = _uconnect_entry(hass)
    uconnect.password = "new-password"
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "uconnect"
    result = await _configure(hass, result, {"uconnect_brand": "fiat_eu", "email": uc.EMAIL, "password": "new-password"})
    result = await _configure(hass, result, OPTIONS)
    assert (result["type"], result["reason"]) == ("abort", "reauth_successful")
    assert entry.data["password"] == "new-password"


# -- Leapmotor ------------------------------------------------------------------

async def test_leapmotor_reconfigure_keeps_the_device_id(hass, leapmotor):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, unique_id="LM-424242_Leapmotor_", data={
        "client": "leapmotor", "mobile_app": "Leapmotor", "country_code": "", "customer_id": "LM-424242",
        "email": "user@example.com", "password": "secret", "pin_code": "", "remote_commands": False, "device_id": "login-device", **OPTIONS})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "leapmotor"
    result = await _configure(hass, result, {"email": "user@example.com", "password": "secret", "pin_code": "1234"})
    result = await _configure(hass, result, OPTIONS)
    assert (result["type"], result["reason"]) == ("abort", "reconfigure_successful")
    assert (entry.data["pin_code"], entry.data["remote_commands"], entry.data["device_id"]) == ("1234", True, "login-device")
