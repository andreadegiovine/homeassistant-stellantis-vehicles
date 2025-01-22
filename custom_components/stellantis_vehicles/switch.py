import logging

from homeassistant.components.switch import SwitchEntityDescription
from .base import StellantisBaseSwitch

from .const import (
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        if coordinator._data["service"]["type"] == "Electric":
            description = SwitchEntityDescription(
                name = "battery_charging_limit",
                key = "battery_charging_limit",
                translation_key = "battery_charging_limit",
                icon = "mdi:battery-charging-60"
            )
            entities.extend([StellantisBaseSwitch(coordinator, description)])

    async_add_entities(entities)