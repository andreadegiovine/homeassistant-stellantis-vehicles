import logging

from homeassistant.components.button import ButtonEntityDescription
from .base import StellantisBaseButton

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

        description = ButtonEntityDescription(
            name = "wakeup",
            key = "wakeup",
            translation_key = "wakeup",
            icon = "mdi:sleep"
        )
        entities.extend([StellantisWakeUpButton(coordinator, description)])

        description = ButtonEntityDescription(
            name = "doors",
            key = "doors",
            translation_key = "doors",
            icon = "mdi:car-door-lock"
        )
        entities.extend([StellantisDoorButton(coordinator, description)])

        description = ButtonEntityDescription(
            name = "horn",
            key = "horn",
            translation_key = "horn",
            icon = "mdi:bullhorn"
        )
        entities.extend([StellantisHornButton(coordinator, description)])

        description = ButtonEntityDescription(
            name = "lights",
            key = "lights",
            translation_key = "lights",
            icon = "mdi:car-parking-lights"
        )
        entities.extend([StellantisLightsButton(coordinator, description)])

    async_add_entities(entities)


class StellantisWakeUpButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_command(self.name, {"wakeUp": {"action": "WakeUp"}})

class StellantisDoorButton(StellantisBaseButton):
    async def async_press(self):
        current_status = self._coordinator._data["alarm"]["status"]["activation"]
        new_status = "Unlocked"
        if current_status == "Deactive":
            new_status = "Locked"
        await self._coordinator.send_command(self.name, {"door": {"state": new_status}})

class StellantisHornButton(StellantisBaseButton):
    async def async_press(self):
        new_status = "Activated"
        if "horn_status" in self._data and self._data["horn_status"] == "Activated":
            new_status = "Unactivated"
        self._data["horn_status"] = new_status
        await self._coordinator.send_command(self.name, {"horn": {"state": new_status}})

class StellantisLightsButton(StellantisBaseButton):
    async def async_press(self):
        new_status = True
        if "lights_status" in self._data and self._data["lights_status"] == True:
            new_status = False
        self._data["lights_status"] = new_status
        await self._coordinator.send_command(self.name, {"lights": {"on": new_status}})