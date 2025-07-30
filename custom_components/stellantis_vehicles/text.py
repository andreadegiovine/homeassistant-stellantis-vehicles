import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.text import TextEntityDescription
from .base import StellantisBaseText

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
            description = TextEntityDescription(
                name = "abrp_token",
                key = "abrp_token",
                translation_key = "abrp_token",
                icon = "mdi:source-branch"
            )
            entities.extend([StellantisBaseText(coordinator, description)])

    async_add_entities(entities)