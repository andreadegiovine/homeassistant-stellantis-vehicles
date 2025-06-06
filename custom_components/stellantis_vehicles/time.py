import logging

from homeassistant.components.time import TimeEntityDescription
from .base import StellantisBaseTime
from .utils import ( timestring_to_datetime )

from .const import (
    DOMAIN,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = TimeEntityDescription(
                name = "battery_charging_start",
                key = "battery_charging_start",
                translation_key = "battery_charging_start",
                icon = "mdi:battery-clock"
            )
            entities.extend([StellantisBatteryChargingStart(coordinator, description)])

    async_add_entities(entities)


class StellantisBatteryChargingStart(StellantisBaseTime):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description)
        self._data_map = ["energies", 0, "extension", "electric", "charging", "nextDelayedTime"]

    @property
    def available(self):
        return self.available_command

    async def async_set_value(self, value):
        self._attr_native_value = value
        self._coordinator._sensors[self._key] = value
        await self._coordinator.send_charge_command(self.name, True)
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        self._attr_native_value = self.get_value(self._data_map)