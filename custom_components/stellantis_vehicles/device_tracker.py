import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityDescription
from .base import StellantisBaseDevice
from .stellantis import StellantisVehicles

from .const import (
    DOMAIN,
    SENSORS_DEFAULT
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    stellantis: StellantisVehicles = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        default_value = SENSORS_DEFAULT.get("vehicle", {})
        description = EntityDescription(
            name = "vehicle",
            key = "vehicle",
            translation_key = "vehicle",
            icon = default_value.get("icon", None),
            entity_category = None
        )
        entities.extend([StellantisBaseDevice(coordinator, description)])

#         await coordinator.async_request_refresh()

    async_add_entities(entities)