"""A Leapmotor config entry set up in a real Home Assistant instance, on a fake cloud."""
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN, INTEGRATION_VERSION
from custom_components.stellantis_vehicles.client.leapmotor.client import LeapmotorVehicles

from .leapmotor_fakes import FakeCloud, PIN, STATUS, VIN, make_certificate

APP_CERT = make_certificate()[:2]


@pytest.fixture
def cloud(hass):
    cloud = FakeCloud()

    def start_session(self):
        cloud.closed = False
        self._session = cloud

    async def integration_setup(hass, config):
        return True

    with patch.object(LeapmotorVehicles, "start_session", start_session), \
         patch("custom_components.stellantis_vehicles.client.leapmotor.client.async_ensure_app_certificate", return_value=APP_CERT), \
         patch("custom_components.stellantis_vehicles.async_setup", integration_setup):
        hass.config.components.update({"frontend", "http", "webhook"})
        yield cloud


def _entry(hass, pin=PIN):
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, title="Leapmotor", data={
        "client": "leapmotor", "mobile_app": "Leapmotor", "country_code": "", "customer_id": "LM-424242",
        "email": "user@example.com", "password": "secret", "pin_code": pin, "remote_commands": bool(pin),
        "device_id": "login-device", "notifications": True, "anonymize_logs": True,
    })
    entry.add_to_hass(hass)
    return entry


def _state(hass, platform, key):
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{VIN}_{key}")
    return hass.states.get(entity_id) if entity_id else None


async def test_entry_sets_up_with_the_shared_entities(hass, cloud):
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, "sensor", "battery").state == "76"
    assert float(_state(hass, "sensor", "autonomy").state) == 301
    assert float(_state(hass, "sensor", "mileage").state) == 12345
    assert _state(hass, "sensor", "type").state == "electric"
    assert _state(hass, "binary_sensor", "battery_charging").state == "on"
    assert _state(hass, "binary_sensor", "battery_plugged").state == "on"
    assert _state(hass, "binary_sensor", "doors").state == "off"
    assert _state(hass, "binary_sensor", "door_trunk").state == "on"
    assert _state(hass, "binary_sensor", "preconditioning").state == "on"
    tracker = _state(hass, "device_tracker", "vehicle")
    assert (tracker.attributes["latitude"], tracker.attributes["longitude"]) == (45.46, 9.19)

    # What Leapmotor has no equivalent for is not created at all.
    for platform, key in (("sensor", "oil_temperature"), ("sensor", "days_before_maintenance"), ("button", "wakeup"), ("button", "lights"),
                          ("button", "charge_start"), ("time", "battery_charging_start"), ("switch", "battery_values_correction")):
        assert _state(hass, platform, key) is None, key
    assert _state(hass, "button", "doors_lock") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert cloud.closed


async def test_vehicle_picture_is_saved_once_and_shown_by_the_tracker(hass, cloud, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "www").mkdir()
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    picture = tmp_path / "www" / DOMAIN / "LM-424242" / f"{VIN}.png"
    assert picture.is_file()
    assert _state(hass, "device_tracker", "vehicle").attributes["entity_picture"] == f"/local/{DOMAIN}/LM-424242/{VIN}.png"

    # A saved picture is not downloaded again.
    await entry.runtime_data.get_user_vehicles(force=True)
    assert cloud.endpoints().count("/vehicle/v1/carpicture/key") == 1


async def test_last_trip_is_built_from_the_statuses(hass, cloud):
    entry = _entry(hass)
    cloud.status = {**STATUS, "dumpEnergy": 30000}
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinators[0]

    def status(minutes, **signals):
        return {"outdoorTemp": 11, "dumpEnergy": signals.pop("energy"), "signal": {**STATUS["signal"], "1149": 0, "sts": STATUS["signal"]["sts"] + minutes * 60000, **signals}}

    for cloud.status in (
        status(1, energy=30000, **{"1258": 1, "1010": 3, "1319": 0}),
        status(2, energy=29000, **{"1258": 1, "1010": 3, "1319": 72, "1318": 12346}),
        status(11, energy=27000, **{"1258": 0, "1010": 0, "1319": 0, "1318": 12357}),
    ):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    trip = _state(hass, "sensor", "last_trip")
    assert float(trip.state) == 12
    assert trip.attributes["duration"] == "00:10:00"
    assert trip.attributes["start_mileage"] == "12345.0 km"
    assert trip.attributes["avg_speed"] == "72.0 km/h"
    assert trip.attributes["max_speed"] == "72.0 km/h"
    assert trip.attributes["electric_consumption"] == "3.0 kWh"
    assert trip.attributes["electric_avg_consumption"] == "25.0 kWh/100km"
    assert float(_state(hass, "sensor", "battery_residual").state) == 27


async def test_lock_button_sends_the_command_and_records_its_result(hass, cloud):
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{VIN}_doors_lock")

    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert ("/vehicle/v1/app/remote/ctl", "110") in [(endpoint, params.get("cmdId")) for endpoint, params in cloud.calls]
    coordinator = entry.runtime_data.coordinators[0]
    assert coordinator.pending_action
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not coordinator.pending_action
    assert list(coordinator.command_history.values())[0].endswith("Complete")


PLAN = {"isEnable": 0, "percent": 90, "circulation": 0, "cycles": "1,2,3,4,5,6,7", "endTime": "07:00", "recharge": 0, "beginTime": "22:00"}


async def _set_limit(hass, value):
    number = er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{VIN}_battery_charging_limit")
    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": value}, blocking=True)
    return number


async def test_charge_limit_is_read_from_the_vehicle_and_written_with_its_plan(hass, cloud):
    cloud.status = {**STATUS, "config": {"3": PLAN}}
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(_state(hass, "number", "battery_charging_limit").state) == 90
    assert _state(hass, "number", "battery_charging_limit").attributes["max"] == 100

    number = await _set_limit(hass, 80)
    command = next(params for endpoint, params in cloud.calls if endpoint == "/vehicle/v1/app/remote/ctl")
    assert command["cmdId"] == "190"
    # Only the limit changes; the schedule is written back as it was.
    assert command["cmdContent"] == '{"chargeEnable":0,"chargesoc":80,"circulation":0,"cycles":"1,2,3,4,5,6,7","endtime":"07:00","recharge":0,"starttime":"22:00"}'
    assert "/vehicle/v1/app/remote/ctl/getAppointment" not in cloud.endpoints()
    # Shown at once, until the vehicle reports it itself.
    assert float(hass.states.get(number).state) == 80
    # The vehicle has not sent a newer status yet: the sent value stays.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert float(hass.states.get(number).state) == 80
    # Then the vehicle reports its own value again.
    cloud.status = {**STATUS, "config": {"3": {**PLAN, "percent": 75}}, "signal": {**STATUS["signal"], "sts": STATUS["signal"]["sts"] + 60000}}
    await entry.runtime_data.coordinators[0].async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(number).state) == 75


async def test_charge_limit_takes_the_rest_of_the_plan_from_the_cloud_when_the_status_lacks_it(hass, cloud):
    cloud.status = {**STATUS, "chargesocSetting": 70}
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(_state(hass, "number", "battery_charging_limit").state) == 70

    await _set_limit(hass, 85)
    command = next(params for endpoint, params in cloud.calls if endpoint == "/vehicle/v1/app/remote/ctl")
    assert command["cmdContent"] == '{"chargeEnable":1,"chargesoc":85,"circulation":1,"cycles":"1,2,3","endtime":"06:00","recharge":0,"starttime":"23:00"}'


async def test_charge_limit_is_not_written_without_a_complete_plan(hass, cloud):
    cloud.stored_plan = None
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await _set_limit(hass, 85)
    assert "/vehicle/v1/app/remote/ctl" not in cloud.endpoints()


async def test_battery_preheating_switch(hass, cloud):
    cloud.status = {**STATUS, "signal": {**STATUS["signal"], "1186": 0}}
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{VIN}_battery_preheating")
    assert hass.states.get(switch).state == "off"

    cloud.status = {**STATUS, "signal": {**STATUS["signal"], "1186": 4, "sts": STATUS["signal"]["sts"] + 60000}}
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    command = next(params for endpoint, params in cloud.calls if endpoint == "/vehicle/v1/app/remote/ctl")
    assert (command["cmdId"], command["cmdContent"]) == ("160", '{"value":"ptcon"}')
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(switch).state == "on"


async def test_without_pin_the_vehicle_is_read_only(hass, cloud):
    entry = _entry(hass, pin="")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, "sensor", "battery").state == "76"
    assert er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{VIN}_doors_lock") is None


async def test_refused_password_starts_a_reauthentication(hass, cloud):
    cloud.password = "changed"
    entry = _entry(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_secrets_stay_out_of_the_client_configuration(hass, cloud):
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    config = entry.runtime_data._config
    assert "password" not in config and "pin_code" not in config


async def test_config_flow_creates_a_leapmotor_entry(hass, cloud):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mobile_app": "Leapmotor"})
    assert result["step_id"] == "leapmotor"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com", "password": "wrong"})
    assert result["errors"] == {"base": "leapmotor_login"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com", "password": "secret", "pin_code": PIN})
    assert result["step_id"] == "options"
    # Leapmotor has no live MQTT channel to offer.
    assert "mqtt_live_updates" not in [str(key) for key in result["data_schema"].schema]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"notifications": True, "anonymize_logs": True})
    assert result["type"] == "create_entry"
    data = result["data"]
    assert (data["client"], data["customer_id"], data["remote_commands"]) == ("leapmotor", "LM-424242", True)
    assert len(data["device_id"]) == 32
    await hass.async_block_till_done()
    assert result["result"].state is ConfigEntryState.LOADED
