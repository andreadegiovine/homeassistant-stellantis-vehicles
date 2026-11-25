"""Regression: a PSA entry creates the same entities, with the same states, as before
the other clients were added (entity list taken from the integration at that time)."""
import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN, INTEGRATION_VERSION

CLIENT = "custom_components.stellantis_vehicles.client.psa.client.StellantisVehicles"
VIN = "VR3UHZKXZPT000001"
STATUS = {
    "updatedAt": "2026-11-25T10:00:00Z",
    "battery": {"voltage": 87, "createdAt": "2026-11-25T10:00:00Z"},
    "environment": {"air": {"temp": 12.5, "createdAt": "2026-11-25T10:00:00Z"}, "luminosity": {"day": True, "createdAt": "2026-11-25T10:00:00Z"}},
    "odometer": {"mileage": 23456.7, "createdAt": "2026-11-25T10:00:00Z"},
    "kinetic": {"speed": 0, "moving": False, "createdAt": "2026-11-25T10:00:00Z"},
    "ignition": {"type": "Stop", "createdAt": "2026-11-25T10:00:00Z"},
    "privacy": {"state": "None", "createdAt": "2026-11-25T10:00:00Z"},
    "energies": [{"type": "Electric", "level": 64, "autonomy": 210, "createdAt": "2026-11-25T10:00:00Z",
                  "extension": {"electric": {"battery": {"load": {"capacity": 46000, "residual": 29000}, "health": {"resistance": 98}},
                                              "charging": {"plugged": True, "status": "InProgress", "chargingMode": "Slow", "chargingRate": 11, "remainingTime": "PT2H10M", "nextDelayedTime": "PT22H30M", "type": "Full"}}}}],
    "energy": [{"type": "Electric", "updatedAt": "2026-11-25T10:00:00Z"}],
    "doorsState": {"lockedStates": ["Locked"], "createdAt": "2026-11-25T10:00:00Z",
                   "opening": [{"identifier": n, "state": "Closed"} for n in ("Driver", "Passenger", "RearLeft", "RearRight", "Trunk")]},
    "preconditioning": {"airConditioning": {"status": "Disabled", "createdAt": "2026-11-25T10:00:00Z", "programs": []}},
    "lastPosition": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [9.19, 45.46, 120]}, "properties": {"createdAt": "2026-11-25T10:00:00Z", "heading": 10}},
}

EXPECTED_ENTITIES = {
    "binary_sensor": ['alarm', 'battery_charging', 'battery_charging_limit', 'battery_plugged', 'belt_driver', 'belt_passenger', 'command_pending', 'daylight', 'door_driver', 'door_passenger', 'door_rear_left', 'door_rear_right', 'door_trunk', 'doors', 'engine', 'moving', 'preconditioning', 'privacy', 'remote_commands'],
    "button": ['charge_limit_off', 'charge_limit_on', 'charge_start', 'charge_stop', 'doors_lock', 'doors_unlock', 'horn', 'lights', 'preconditioning_start', 'preconditioning_stop', 'wakeup'],
    "device_tracker": ['vehicle'],
    "number": ['battery_charging_limit', 'refresh_interval'],
    "sensor": ['autonomy', 'battery', 'battery_capacity', 'battery_charging_end', 'battery_charging_rate', 'battery_charging_type', 'battery_health_capacity', 'battery_health_resistance', 'battery_residual', 'command_status', 'days_before_maintenance', 'driving_behavior', 'last_charge', 'last_trip', 'mileage', 'mileage_before_maintenance', 'service_battery_voltage', 'speed', 'temperature', 'type'],
    "switch": ['abrp_sync', 'battery_charging_limit', 'battery_values_correction'],
    "text": ['abrp_token'],
    "time": ['battery_charging_start'],
}


async def test_psa_entry_creates_the_same_entities_as_before(hass):
    hass.config.components.update({"frontend", "http", "webhook"})
    expires = (dt_util.utcnow() + timedelta(hours=1)).isoformat()
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, title="MyPeugeot", unique_id="AP-1_MyPeugeot_IT", data={
        "mobile_app": "MyPeugeot", "country_code": "IT", "customer_id": "AP-1", "remote_commands": True,
        "oauth": {"access_token": "a", "refresh_token": "r", "expires_in": expires},
        "mqtt": {"access_token": "m", "refresh_token": "mr", "expires_in": expires, "refresh_token_expires_at": expires},
        "notifications": False, "anonymize_logs": False, "mqtt_live_updates": True})
    entry.add_to_hass(hass)
    vehicles = [{"vehicle_id": "psa-id-1", "vin": VIN, "type": "Electric", "brand": "Peugeot", "links": {}}]

    async def integration_setup(hass, config):
        return True

    with patch(f"{CLIENT}.scheduled_tokens_refresh", AsyncMock()),          patch(f"{CLIENT}.get_user_vehicles", AsyncMock(return_value=vehicles)),          patch(f"{CLIENT}.get_vehicle_status", AsyncMock(side_effect=lambda vehicle: json.loads(json.dumps(STATUS)))),          patch(f"{CLIENT}.get_vehicle_maintenance", AsyncMock(return_value={})),          patch(f"{CLIENT}.get_vehicle_rights", AsyncMock(return_value={})),          patch(f"{CLIENT}.get_vehicle_last_trip", AsyncMock(return_value={})),          patch(f"{CLIENT}.connect_mqtt", AsyncMock()),          patch("custom_components.stellantis_vehicles.async_setup", integration_setup):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        created = {}
        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
            created.setdefault(entity.domain, []).append(entity.unique_id.removeprefix(f"{VIN}_"))
        assert {domain: sorted(keys) for domain, keys in created.items()} == EXPECTED_ENTITIES

        def state(key):
            domain, name = key.split(".")
            return hass.states.get(er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{VIN}_{name}")).state
        assert state("sensor.battery") == "64"
        assert state("sensor.mileage") == "23456.7"
        assert state("binary_sensor.battery_charging") == "on"
        assert state("binary_sensor.doors") == "off"
        # Commands need the MQTT connection, not opened here (as before).
        assert state("time.battery_charging_start") == "unavailable"
        assert state("button.wakeup") == "unavailable"
        # PSA keeps the limit managed by the integration (15-95%) and polls every minute.
        limit = hass.states.get(er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{VIN}_battery_charging_limit"))
        assert (limit.attributes["min"], limit.attributes["max"]) == (15, 95)
        assert state("number.refresh_interval") == "60.0"
        coordinator = entry.runtime_data.coordinators[0]
        assert coordinator.update_interval == timedelta(seconds=60)
        assert not coordinator.has_vehicle_charge_limit and not coordinator.builds_trips

        device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
        assert (device.manufacturer, device.model) == ("Peugeot", f"Electric - {VIN}")
        assert await hass.config_entries.async_unload(entry.entry_id)
