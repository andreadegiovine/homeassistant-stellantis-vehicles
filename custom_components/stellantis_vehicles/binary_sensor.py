import logging

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from .base import StellantisBaseBinarySensor

from .const import (
    DOMAIN,
    BINARY_SENSORS_DEFAULT
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)

        for key in BINARY_SENSORS_DEFAULT:
            default_value = BINARY_SENSORS_DEFAULT.get(key, {})
            if default_value.get("data_map", None) and default_value.get("on_value", None):
                description = BinarySensorEntityDescription(
                    name = key,
                    key = key,
                    translation_key = key,
                    icon = default_value.get("icon", None),
                    device_class = default_value.get("device_class", None)
                )
                entities.extend([StellantisBaseBinarySensor(coordinator, description, default_value.get("data_map", None), default_value.get("on_value", None))])

#         await coordinator.async_request_refresh()

    async_add_entities(entities)