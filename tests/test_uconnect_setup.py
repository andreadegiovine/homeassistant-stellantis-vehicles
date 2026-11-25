"""A Uconnect config entry set up in a real Home Assistant instance, on a fake py-uconnect."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN, INTEGRATION_VERSION

from .uconnect_fakes import EMAIL, PASSWORD, PIN, VIN_EV, VIN_ICE, FakeCloud


@pytest.fixture
def cloud(hass):
    cloud = FakeCloud()

    async def integration_setup(hass, config):
        return True

    with patch("custom_components.stellantis_vehicles.client.uconnect.client.Client", cloud.client_class), \
         patch("custom_components.stellantis_vehicles.async_setup", integration_setup):
        hass.config.components.update({"frontend", "http", "webhook"})
        yield cloud


def _entry(hass, pin=PIN):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, title="Uconnect", unique_id="UC-gigya-uid-1_Uconnect_", data={
        "client": "uconnect", "mobile_app": "Uconnect", "country_code": "", "customer_id": "UC-gigya-uid-1",
        "uconnect_brand": "fiat_eu", "email": EMAIL, "password": PASSWORD, "pin_code": pin, "remote_commands": bool(pin),
        "notifications": True, "anonymize_logs": True,
    })
    entry.add_to_hass(hass)
    return entry


def _entity_id(hass, platform, vin, key):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{vin}_{key}")


def _state(hass, platform, vin, key):
    entity_id = _entity_id(hass, platform, vin, key)
    return hass.states.get(entity_id) if entity_id else None


async def _setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entry_sets_up_both_vehicles_with_one_account_refresh(hass, cloud):
    entry = _entry(hass)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert cloud.brand.name == "FIAT_EU"
    # The account refresh serves every vehicle: listing plus two first polls.
    assert cloud.refreshes == 1

    assert _state(hass, "sensor", VIN_EV, "battery").state == "80"
    assert float(_state(hass, "sensor", VIN_EV, "autonomy").state) == 250
    assert _state(hass, "sensor", VIN_EV, "type").state == "electric"
    assert _state(hass, "binary_sensor", VIN_EV, "battery_charging").state == "on"
    assert _state(hass, "binary_sensor", VIN_EV, "doors").state == "off"
    assert float(_state(hass, "sensor", VIN_ICE, "mileage").state) == 16093.4
    assert _state(hass, "sensor", VIN_ICE, "type").state == "thermic"
    assert _state(hass, "binary_sensor", VIN_ICE, "doors").state == "on"
    tracker = _state(hass, "device_tracker", VIN_EV, "vehicle")
    assert (tracker.attributes["latitude"], tracker.attributes["longitude"]) == (45.46, 9.19)

    # Polled every 5 minutes, and that is the refresh interval offered.
    coordinator = next(c for c in entry.runtime_data.coordinators if c._vehicle["vin"] == VIN_EV)
    assert coordinator.update_interval == timedelta(minutes=5)
    assert float(_state(hass, "number", VIN_EV, "refresh_interval").state) == 300

    # Command entities follow each vehicle's services.
    for key in ("wakeup", "doors_lock", "horn", "lights", "preconditioning_start", "charge_start"):
        assert _state(hass, "button", VIN_EV, key) is not None, key
    assert _state(hass, "button", VIN_ICE, "doors_lock") is not None
    assert _state(hass, "button", VIN_ICE, "preconditioning_start") is not None
    for key in ("wakeup", "horn", "lights", "charge_start"):
        assert _state(hass, "button", VIN_ICE, key) is None, key
    # Nothing without a Uconnect equivalent.
    for platform, key in (("button", "charge_stop"), ("button", "charge_limit_on"), ("number", "battery_charging_limit"),
                          ("time", "battery_charging_start"), ("switch", "battery_preheating"), ("sensor", "speed"),
                          ("sensor", "service_battery_voltage"), ("binary_sensor", "door_trunk")):
        assert _state(hass, platform, VIN_EV, key) is None, key

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_command_is_sent_and_its_result_recorded(hass, cloud):
    entry = _entry(hass)
    await _setup(hass, entry)
    await hass.services.async_call("button", "press", {"entity_id": _entity_id(hass, "button", VIN_EV, "doors_lock")}, blocking=True)
    assert cloud.commands == [(VIN_EV, "RDL", None)]
    coordinator = next(c for c in entry.runtime_data.coordinators if c._vehicle["vin"] == VIN_EV)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert list(coordinator.command_history.values())[0].endswith("Complete")

    # The climate of a vehicle without preconditioning goes through HVAC.
    await hass.services.async_call("button", "press", {"entity_id": _entity_id(hass, "button", VIN_ICE, "preconditioning_start")}, blocking=True)
    assert cloud.commands[-1] == (VIN_ICE, "ROHVACON", None)


async def test_command_not_confirmed_in_time_is_a_timeout(hass, cloud):
    cloud.outcome = "timeout"
    entry = _entry(hass)
    await _setup(hass, entry)
    await hass.services.async_call("button", "press", {"entity_id": _entity_id(hass, "button", VIN_EV, "horn")}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = next(c for c in entry.runtime_data.coordinators if c._vehicle["vin"] == VIN_EV)
    assert list(coordinator.command_history.values())[0].endswith("Timeout")


async def test_wrong_pin_refuses_the_command_without_reauthentication(hass, cloud):
    entry = _entry(hass, pin="0000")
    await _setup(hass, entry)
    with pytest.raises(HomeAssistantError, match="PIN"):
        await hass.services.async_call("button", "press", {"entity_id": _entity_id(hass, "button", VIN_EV, "doors_unlock")}, blocking=True)
    assert not cloud.commands
    assert not any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_charge_start_only_when_plugged_and_not_charging(hass, cloud):
    cloud.vehicles[VIN_EV].charging = False
    entry = _entry(hass)
    await _setup(hass, entry)
    button = _entity_id(hass, "button", VIN_EV, "charge_start")
    assert hass.states.get(button).state != "unavailable"
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert cloud.commands[-1] == (VIN_EV, "CNOW", None)

    cloud.vehicles[VIN_EV].plugged_in = False
    cloud.vehicles[VIN_EV].timestamp_info = cloud.vehicles[VIN_EV].timestamp_info + timedelta(minutes=5)
    entry.runtime_data._refreshed_at = None
    coordinator = next(c for c in entry.runtime_data.coordinators if c._vehicle["vin"] == VIN_EV)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(button).state == "unavailable"


async def test_without_pin_the_vehicles_are_read_only(hass, cloud):
    entry = _entry(hass, pin="")
    await _setup(hass, entry)
    assert _state(hass, "sensor", VIN_EV, "battery").state == "80"
    assert _state(hass, "button", VIN_EV, "doors_lock") is None
    assert cloud.last_pin is None


async def test_refused_password_starts_a_reauthentication(hass, cloud):
    cloud.password = "changed"
    entry = _entry(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_vehicle_picture_and_secrets(hass, cloud):
    cloud.vehicles[VIN_EV].image_url = "https://example.com/500e.png"
    entry = _entry(hass)
    with patch("custom_components.stellantis_vehicles.client_base.BaseVehiclesClient.resize_and_save_picture", AsyncMock(return_value="/local/x.png")) as save:
        await _setup(hass, entry)
    save.assert_awaited_once_with("https://example.com/500e.png", VIN_EV)
    assert _state(hass, "device_tracker", VIN_EV, "vehicle").attributes["entity_picture"] == "/local/x.png"
    config = entry.runtime_data._config
    assert "password" not in config and "pin_code" not in config
    diagnostics = entry.runtime_data.diagnostics()["uconnect"]
    assert diagnostics["brand"] == "fiat_eu" and diagnostics["logged_in"]
