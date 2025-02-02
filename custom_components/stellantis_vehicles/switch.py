import logging

from homeassistant.components.switch import SwitchEntityDescription
from .base import StellantisBaseSwitch

from .const import (
    DOMAIN,
    VEHICLE_TYPE_ELECTRIC
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator.vehicle_type == VEHICLE_TYPE_ELECTRIC:
            description = SwitchEntityDescription(
                name = "battery_charging_limit",
                key = "battery_charging_limit",
                translation_key = "battery_charging_limit",
                icon = "mdi:battery-charging-60"
            )
            entities.extend([StellantisBatteryChargingLimitSwitch(coordinator, description)])

    async_add_entities(entities)


class StellantisBatteryChargingLimitSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and "number_battery_charging_limit" in self._coordinator._sensors and self._coordinator._sensors["number_battery_charging_limit"]