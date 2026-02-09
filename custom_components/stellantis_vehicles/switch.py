import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory

from .base import StellantisBaseSwitch

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
        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            if stellantis.remote_commands:
                description = SwitchEntityDescription(
                    name = "battery_charging_limit",
                    key = "battery_charging_limit",
                    translation_key = "battery_charging_limit",
                    icon = "mdi:battery-charging-60",
                    entity_category = EntityCategory.CONFIG
                )
                entities.extend([StellantisBatteryChargingLimitSwitch(coordinator, description)])

            description = SwitchEntityDescription(
                name = "abrp_sync",
                key = "abrp_sync",
                translation_key = "abrp_sync",
                icon = "mdi:source-branch-sync",
                entity_category = EntityCategory.CONFIG
            )
            entities.extend([StellantisAbrpSyncSwitch(coordinator, description)])

            description = SwitchEntityDescription(
                name = "battery_values_correction",
                key = "battery_values_correction",
                translation_key = "battery_values_correction",
                icon = "mdi:auto-fix",
                entity_category = EntityCategory.CONFIG
            )
            entities.extend([StellantisBaseSwitch(coordinator, description)])

        description = SwitchEntityDescription(
            name = "notifications",
            key = "notifications",
            translation_key = "notifications",
            icon = "mdi:message-alert",
            entity_category = EntityCategory.CONFIG
        )
        entities.extend([StellantisBaseSwitch(coordinator, description)])

    async_add_entities(entities)


class StellantisBatteryChargingLimitSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and self._coordinator._sensors.get("number_battery_charging_limit", False)

class StellantisAbrpSyncSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and self._coordinator._sensors.get("text_abrp_token") and len(self._coordinator._sensors.get("text_abrp_token")) == 36