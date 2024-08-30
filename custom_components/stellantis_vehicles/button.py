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

        description = ButtonEntityDescription(
            name = "start_stop",
            key = "start_stop",
            translation_key = "start_stop",
            icon = "mdi:play-pause"
        )
        entities.extend([StellantisChargingStartStopButton(coordinator, description)])

        description = ButtonEntityDescription(
            name = "charging_full",
            key = "charging_full",
            translation_key = "charging_full",
            icon = "mdi:battery-charging-100"
        )
        entities.extend([StellantisChargingLimitButton(coordinator, description)])

    async_add_entities(entities)


class StellantisWakeUpButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_command(self.name, {"wakeUp": {"action": "WakeUp"}})

class StellantisDoorButton(StellantisBaseButton):
    async def async_press(self):
        current_status = self._coordinator._sensors["doors"]
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

class StellantisChargingStartStopButton(StellantisBaseButton):
    @property
    def available(self):
        return super().available and self._coordinator._sensors["battery_plugged"] and self._coordinator._sensors["battery_charging"] in ["InProgress", "Stopped"]

    async def async_press(self):
        current_status = self._coordinator._sensors["battery_charging"]
        new_status = True
        if current_status == "InProgress":
            new_status = False
        await self._coordinator.send_command(self.name, {"charging": {"immediate": new_status}})

class StellantisChargingLimitButton(StellantisBaseButton):
    async def async_press(self):
#         current_status = self._coordinator._sensors["battery_charging"]
#         new_status = True
#         if current_status == "InProgress":
#             new_status = False
        await self._coordinator.send_command(self.name, {"charging": {"preferences": {"type": "Partial"}}})