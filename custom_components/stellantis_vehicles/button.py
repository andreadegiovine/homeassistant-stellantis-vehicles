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
            name = "charge_start_stop",
            key = "charge_start_stop",
            translation_key = "charge_start_stop",
            icon = "mdi:play-pause"
        )
        entities.extend([StellantisChargingStartStopButton(coordinator, description)])

#         description = ButtonEntityDescription(
#             name = "charge_full",
#             key = "charge_full",
#             translation_key = "charge_full",
#             icon = "mdi:battery-charging-100"
#         )
#         entities.extend([StellantisChargingLimitButton(coordinator, description)])

    async_add_entities(entities)


class StellantisWakeUpButton(StellantisBaseButton):
    async def async_press(self):
# ------ WEB API COMMAND VERSION
#         await self._coordinator.send_command(self.name, {"wakeUp": {"action": "WakeUp"}})
        await self._coordinator.send_command(self.name, "/VehCharge/state", {"action": "state"})

class StellantisDoorButton(StellantisBaseButton):
    async def async_press(self):
        current_status = self._coordinator._sensors["doors"]
# ------ WEB API COMMAND VERSION
#         new_status = "Unlocked"
#         if current_status == "Deactive":
#             new_status = "Locked"
#         await self._coordinator.send_command(self.name, {"door": {"state": new_status}})
        new_status = "unlock"
        if current_status == "Deactive":
            new_status = "lock"
        await self._coordinator.send_command(self.name, "/Doors", {"action": new_status})

class StellantisHornButton(StellantisBaseButton):
    async def async_press(self):
# ------ WEB API COMMAND VERSION
#         new_status = "Activated"
#         if "horn_status" in self._data and self._data["horn_status"] == "Activated":
#             new_status = "Unactivated"
#         self._data["horn_status"] = new_status
#         await self._coordinator.send_command(self.name, {"horn": {"state": new_status}})
        await self._coordinator.send_command(self.name, "/Horn", {"nb_horn": "2", "action": "activate"})

class StellantisLightsButton(StellantisBaseButton):
    async def async_press(self):
# ------ WEB API COMMAND VERSION
#         new_status = True
#         if "lights_status" in self._data and self._data["lights_status"] == True:
#             new_status = False
#         self._data["lights_status"] = new_status
#         await self._coordinator.send_command(self.name, {"lights": {"on": new_status}})
        await self._coordinator.send_command(self.name, "/Lights", {"duration": "10", "action": "activate"})

class StellantisChargingStartStopButton(StellantisBaseButton):
    @property
    def available(self):
        return super().available and self._coordinator._sensors["battery_plugged"] and self._coordinator._sensors["battery_charging"] in ["InProgress", "Stopped"]

    async def async_press(self):
# ------ WEB API COMMAND VERSION
#         current_status = self._coordinator._sensors["battery_charging"]
#         new_status = True
#         if current_status == "InProgress":
#             new_status = False
#         await self._coordinator.send_command(self.name, {"charging": {"immediate": new_status}})
        current_hour = self._data["energies"][0]["extension"]["electric"]["charging"]["nextDelayedTime"]
        regex = 'PT'
        if current_hour.find("H") != -1:
            regex = regex + "%HH"
        if current_hour.find("M") != -1:
            regex = regex + "%MM"
        if current_hour.find("S") != -1:
            regex = regex + "%SS"
        date = datetime.strptime(current_hour,regex)

        current_status = self._coordinator._sensors["battery_charging"]
        charge_type = "immediate"
        if current_status == "InProgress":
            charge_type = "delayed"
        await self._coordinator.send_command(self.name, "/VehCharge", {"program": {"hour": date.hour, "minute": date.minute}, "type": charge_type})

# class StellantisChargingLimitButton(StellantisBaseButton):
#     async def async_press(self):
# #         current_status = self._coordinator._sensors["battery_charging"]
# #         new_status = True
# #         if current_status == "InProgress":
# #             new_status = False
#         await self._coordinator.send_command(self.name, {"charging": {"preferences": {"type": "Partial"}}})