import logging

from homeassistant.core import HomeAssistant
from homeassistant.const import ( PERCENTAGE, UnitOfTime, UnitOfEnergy )
from homeassistant.components.number import NumberMode, NumberEntityDescription
from homeassistant.const import EntityCategory

from .base import StellantisBaseNumber

from .const import (
    DOMAIN,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID,
    UPDATE_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass:HomeAssistant, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID] and stellantis.remote_commands:
            description = NumberEntityDescription(
                name = "battery_charging_limit",
                key = "battery_charging_limit",
                translation_key = "battery_charging_limit",
                icon = "mdi:battery-charging-60",
                unit_of_measurement = PERCENTAGE,
                native_min_value = 15,
                native_max_value = 95,
                native_step = 1,
                mode = NumberMode.SLIDER,
                entity_category = EntityCategory.CONFIG
            )
            entities.extend([StellantisBaseNumber(coordinator, description)])

        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = NumberEntityDescription(
                name = "kwh_cost",
                key = "kwh_cost",
                translation_key = "kwh_cost",
                icon = "mdi:cash",
                native_min_value = 0,
                native_step = 0.001,
                mode = NumberMode.BOX,
                entity_category = EntityCategory.CONFIG
            )
            entities.extend([StellantisKwhCostNumber(coordinator, description, 0)])

        description = NumberEntityDescription(
            name = "refresh_interval",
            key = "refresh_interval",
            translation_key = "refresh_interval",
            icon = "mdi:sync",
            unit_of_measurement = UnitOfTime.SECONDS,
            native_min_value = 30,
            native_max_value = 3600,
            native_step = 5,
            mode = NumberMode.BOX,
            entity_category = EntityCategory.CONFIG
        )
        entities.extend([StellantisBaseNumber(coordinator, description, UPDATE_INTERVAL)])

    async_add_entities(entities)


class StellantisKwhCostNumber(StellantisBaseNumber):
    @property
    def native_unit_of_measurement(self):
        """ Native value unit of measurement. """
        return f"{self._coordinator.currency_code}/{UnitOfEnergy.KILO_WATT_HOUR}"
