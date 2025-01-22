import logging

from homeassistant.helpers.entity import EntityDescription
from .base import StellantisBaseDevice

from .const import (
    DOMAIN,
    SENSORS_DEFAULT
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
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