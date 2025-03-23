import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.switch import SwitchEntityDescription
from .base import StellantisBaseSwitch
from .stellantis import StellantisVehicles

from .const import (
    DOMAIN,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry:ConfigEntry, async_add_entities) -> None:
    stellantis:StellantisVehicles = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = SwitchEntityDescription(
                name = "battery_charging_limit",
                key = "battery_charging_limit",
                translation_key = "battery_charging_limit",
                icon = "mdi:battery-charging-60"
            )
            entities.extend([StellantisBatteryChargingLimitSwitch(coordinator, description)])

            description = SwitchEntityDescription(
                name = "abrp_sync",
                key = "abrp_sync",
                translation_key = "abrp_sync",
                icon = "mdi:source-branch-sync"
            )
            entities.extend([StellantisAbrpSyncSwitch(coordinator, description)])

    async_add_entities(entities)


class StellantisBatteryChargingLimitSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and "number_battery_charging_limit" in self._coordinator._sensors and self._coordinator._sensors["number_battery_charging_limit"]


class StellantisAbrpSyncSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and "text_abrp_token" in self._coordinator._sensors and len(self._coordinator._sensors["text_abrp_token"]) == 36