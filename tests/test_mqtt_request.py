"""Payload of the MQTT command requests."""
import asyncio
import json
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import paho.mqtt.client as mqtt

from custom_components.stellantis_vehicles.stellantis import StellantisVehicles


async def test_req_date_is_utc(hass):
    await hass.config.async_set_time_zone("Europe/Paris")
    sv = StellantisVehicles(hass)
    sv._config = {"customer_id": "OV-AC1", "mqtt": {"access_token": "tok"}}
    sv.scheduled_mqtt_token_refresh = AsyncMock()
    sv._mqtt = MagicMock()
    sv._mqtt.is_connected.return_value = True
    sv._mqtt.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_SUCCESS)

    before = datetime.now(UTC).replace(microsecond=0)
    await sv.send_mqtt_message("/VehCharge/state", {"action": "state"}, {"vin": "VIN1"})
    after = datetime.now(UTC)

    topic, payload = sv._mqtt.publish.call_args.args[:2]
    assert topic == "psa/RemoteServices/from/cid/OV-AC1/VehCharge/state"
    data = json.loads(payload)
    req_date = datetime.strptime(data["req_date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before <= req_date <= after
    assert data["req_parameters"] == {"action": "state"}


async def test_901_keeps_command_pending(hass):
    from datetime import timedelta
    from unittest.mock import patch
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.stellantis_vehicles import base
    from custom_components.stellantis_vehicles.base import StellantisVehicleCoordinator
    from custom_components.stellantis_vehicles.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    sv = StellantisVehicles(hass)
    sv._config = {"customer_id": "OV-AC1"}
    sv.send_mqtt_message = AsyncMock(return_value="action-1")
    coordinator = StellantisVehicleCoordinator(hass, {}, {"vin": "VIN1", "id": "1"}, sv, {}, entry)
    sv._coordinator_dict = {"VIN1": coordinator}
    sv.async_get_coordinator_by_vin = lambda vin: coordinator

    sent_at = datetime(2026, 11, 1, 17, 32, 53, tzinfo=UTC)
    now = [sent_at]
    with patch.object(base, "get_datetime", lambda date=None: date or now[0]):
        await coordinator.send_command("wakeup", "/VehCharge/state", {"action": "state"})
        for code in ("900", "901"):
            msg = MagicMock(topic="psa/RemoteServices/to/cid/OV-AC1/VehCharge/state/ProcessManagement", qos=0)
            msg.payload = json.dumps({"vin": "VIN1", "correlation_id": "action-1", "process_code": code}).encode()
            # Called from paho's network thread in real life.
            await hass.async_add_executor_job(sv._on_mqtt_message, None, None, msg)
        for _ in range(5):
            await asyncio.sleep(0)
        await hass.async_block_till_done()

        assert [u["info"] for u in coordinator._commands_history["action-1"]["updates"]] == ["900", "901"]
        # Stellantis answers 300 about 2 minutes later: still pending until then.
        now[0] = sent_at + timedelta(seconds=127)
        assert coordinator.pending_action


async def test_last_trip_timestamps_has_no_plus(hass):
    sv = StellantisVehicles(hass)
    sv.apply_query_params = lambda url, params, vehicle=None: "https://api/trips?client_id=x"
    sv.apply_dict_params = lambda d: dict(d)
    sv.make_http_request = AsyncMock(return_value={})
    await sv.get_vehicle_last_trip({"vin": "VIN1"})
    url = sv.make_http_request.call_args.args[0]
    timestamps = url.split("timestamps=")[1].split("&")[0]
    assert "+" not in timestamps
    datetime.strptime(timestamps, "%Y-%m-%dT%H:%M:%SZ/")
