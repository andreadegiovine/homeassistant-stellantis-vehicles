"""Payload of the MQTT command requests."""
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
