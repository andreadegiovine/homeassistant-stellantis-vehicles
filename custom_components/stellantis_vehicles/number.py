import logging

from homeassistant.const import ( PERCENTAGE, UnitOfTime )
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.number.const import NumberMode
from .base import StellantisBaseNumber

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
            description = NumberEntityDescription(
                name = "battery_charging_limit",
                key = "battery_charging_limit",
                translation_key = "battery_charging_limit",
                icon = "mdi:battery-charging-60",
                unit_of_measurement = PERCENTAGE,
                native_min_value = 20,
                native_max_value = 90,
                native_step = 1,
                mode = NumberMode.SLIDER
            )
            entities.extend([StellantisBaseNumber(coordinator, description)])

        description = NumberEntityDescription(
            name = "refresh_interval",
            key = "refresh_interval",
            translation_key = "refresh_interval",
            icon = "mdi:sync",
            unit_of_measurement = UnitOfTime.SECONDS,
            native_min_value = 30,
            native_max_value = 3600,
            native_step = 5,
            mode = NumberMode.BOX
        )
        entities.extend([StellantisBaseNumber(coordinator, description)])

    async_add_entities(entities)