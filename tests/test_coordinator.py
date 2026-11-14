"""The PSA coordinator on top of the shared coordinator hooks."""
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN
from custom_components.stellantis_vehicles.client.psa.coordinator import PsaVehicleCoordinator

VEHICLE = {"vin": "VR3TESTVIN0000001", "type": "Electric"}


def _make(hass, status, maintenance=None):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    client = MagicMock()
    client.get_vehicle_status = AsyncMock(return_value=status)
    client.get_vehicle_maintenance = AsyncMock(return_value=maintenance or {})
    client.get_vehicle_last_trip = AsyncMock(return_value={})
    client.send_mqtt_message = AsyncMock(return_value="action-1")
    return PsaVehicleCoordinator(hass, {}, VEHICLE, client, {}, config_entry=entry), client


async def test_update_merges_maintenance_and_stops_polling_it_when_empty(hass):
    status = {"updatedAt": "2026-11-14T10:00:00Z", "ignition": {"type": "Stop"}}
    coordinator, client = _make(hass, status, {"mileageBeforeMaintenance": 1200, "daysBeforeMaintenance": 30, "updatedAt": "x"})
    data = await coordinator._async_update_data()
    assert data["maintenance"]["mileageBeforeMaintenance"] == 1200

    client.get_vehicle_maintenance.return_value = {}
    client.get_vehicle_status.return_value = {"updatedAt": "2026-11-14T10:01:00Z"}
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert client.get_vehicle_maintenance.await_count == 2


async def test_entities_of_other_clients_are_not_created_for_psa(hass):
    coordinator, _ = _make(hass, {})
    assert coordinator.supports("switch", "abrp_sync")
    assert not coordinator.supports("switch", "battery_preheating")
    assert not coordinator.has_vehicle_charge_limit


async def test_mqtt_lock_change_overlays_rest_data(hass):
    status = {"updatedAt": "2026-11-14T10:00:00Z", "doorsState": {"lockedStates": ["Unlocked"], "createdAt": "2026-11-14T10:00:00Z"}}
    coordinator, _ = _make(hass, status)
    coordinator.data = await coordinator._async_update_data()

    # The first event only sets the baseline; a later change wins over REST.
    coordinator.apply_mqtt_event({"timestamp": "2026-11-14T10:00:30Z", "event_counter": 1, "doors": {"locking_state_code": 3}})
    assert coordinator.data["doorsState"]["lockedStates"] == ["Unlocked"]
    coordinator.apply_mqtt_event({"timestamp": "2026-11-14T10:01:00Z", "event_counter": 2, "doors": {"locking_state_code": 1}})
    assert coordinator.data["doorsState"]["lockedStates"] == ["Locked"]
    assert coordinator.diagnostics()["mqtt_state"]["event_counter"] == 2


async def test_command_goes_through_the_client_and_blocks_the_next_one(hass):
    coordinator, client = _make(hass, {"updatedAt": "2026-11-14T10:00:00Z"})
    await coordinator.send_doors_command("Lock", "lock")
    client.send_mqtt_message.assert_awaited_once_with("/Doors", {"action": "lock"}, VEHICLE)
    assert coordinator.pending_action
    await coordinator.update_command_history("action-1", "0")
    assert not coordinator.pending_action
