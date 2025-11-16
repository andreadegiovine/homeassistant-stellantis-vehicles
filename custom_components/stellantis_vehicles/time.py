import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.time import TimeEntityDescription
from .base import StellantisBaseTime

from .const import (
    DOMAIN,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass:HomeAssistant, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID] and stellantis.remote_commands:
            description = TimeEntityDescription(
                name = "battery_charging_start",
                key = "battery_charging_start",
                translation_key = "battery_charging_start",
                icon = "mdi:battery-clock"
            )
            entities.extend([StellantisBatteryChargingStart(coordinator, description)])

    async_add_entities(entities)


class StellantisBatteryChargingStart(StellantisBaseTime):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._value_map = ["energies", {"type":"Electric"}, "extension", "electric", "charging", "nextDelayedTime"]
        self._updated_at_map = ["energies", {"type":"Electric"}, "createdAt"]

    @property
    def available(self):
        return self.available_command

    async def async_set_value(self, value):
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = value
        await self._coordinator.send_charge_command(self.name, True)
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        if self.value_was_updated():
            self._attr_extra_state_attributes["updated_at"] = self.get_updated_at_from_map(self._updated_at_map)
            self._attr_native_value = self.get_value(self._value_map)
