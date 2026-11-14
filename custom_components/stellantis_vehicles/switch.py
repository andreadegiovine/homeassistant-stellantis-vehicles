import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory

from .base import StellantisBaseEntity, StellantisBaseSwitch

from .const import (
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)

# Serialize command calls so a bulk action can't flood the Stellantis cloud.
PARALLEL_UPDATES = 1

async def async_setup_entry(hass:HomeAssistant, entry, async_add_entities) -> None:
    stellantis = entry.runtime_data
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
            name = "battery_preheating",
            key = "battery_preheating",
            translation_key = "battery_preheating",
            icon = "mdi:heat-wave"
        )
        if stellantis.remote_commands and coordinator.supports("switch", "battery_preheating"):
            entities.extend([StellantisBatteryPreheatingSwitch(coordinator, description)])

    async_add_entities([entity for entity in entities if entity._coordinator.supports("switch", entity._key)])


class StellantisBatteryChargingLimitSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and self._coordinator._sensors.get("number_battery_charging_limit", False) and self._coordinator._sensors.get("battery_charging_limit", None) != "Partial"


class StellantisAbrpSyncSwitch(StellantisBaseSwitch):
    @property
    def available(self):
        return super().available and self._coordinator._sensors.get("text_abrp_token") and len(self._coordinator._sensors.get("text_abrp_token")) == 36

class StellantisBatteryPreheatingSwitch(StellantisBaseEntity, SwitchEntity):
    """ Battery preheating: a remote command, its state comes from the vehicle. """

    @property
    def available(self):
        return self.available_command

    @property
    def is_on(self):
        status = (self._coordinator.data or {}).get("batteryPreheating", {}).get("status")
        return None if status is None else status == "Enabled"

    async def async_turn_on(self, **kwargs) -> None:
        await self._coordinator.send_battery_preheating_command(self.name, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._coordinator.send_battery_preheating_command(self.name, False)

    def coordinator_update(self):
        return True
