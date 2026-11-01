"""A command keeps blocking further ones until Stellantis sends its final answer."""
import asyncio
import json
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles import base
from custom_components.stellantis_vehicles.base import StellantisVehicleCoordinator
from custom_components.stellantis_vehicles.const import DOMAIN
from custom_components.stellantis_vehicles.stellantis import StellantisVehicles


async def test_901_keeps_command_pending(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    sv = StellantisVehicles(hass)
    sv._config = {"customer_id": "OV-AC1"}
    sv.send_mqtt_message = AsyncMock(return_value="action-1")
    coordinator = StellantisVehicleCoordinator(hass, {}, {"vin": "VIN1", "id": "1"}, sv, {}, entry)
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
        # Stellantis answers 300 about 2 minutes after the request: still pending until then.
        now[0] = sent_at + timedelta(seconds=127)
        assert coordinator.pending_action

        # Once the final answer arrives the command no longer blocks.
        await coordinator.update_command_history("action-1", "300")
        assert not coordinator.pending_action
