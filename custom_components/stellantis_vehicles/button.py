import logging

from homeassistant.components.button import ButtonEntityDescription
from .base import StellantisBaseButton

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
            name = "air_conditioning",
            key = "air_conditioning",
            translation_key = "air_conditioning",
            icon = "mdi:air-conditioner"
        )
        entities.extend([StellantisAirConditioningButton(coordinator, description)])

        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = ButtonEntityDescription(
                name = "charge_start_stop",
                key = "charge_start_stop",
                translation_key = "charge_start_stop",
                icon = "mdi:play-pause"
            )
            entities.extend([StellantisChargingStartStopButton(coordinator, description)])

    async_add_entities(entities)


class StellantisWakeUpButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_wakeup_command(self.name)

class StellantisDoorButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_doors_command(self.name)

class StellantisHornButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_horn_command(self.name)

class StellantisLightsButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_lights_command(self.name)

class StellantisChargingStartStopButton(StellantisBaseButton):
    @property
    def available(self):
        return super().available and "battery_plugged" in self._coordinator._sensors and self._coordinator._sensors["battery_plugged"] and self._coordinator._sensors["battery_charging"] in ["InProgress", "Stopped"]

    async def async_press(self):
        await self._coordinator.send_charge_command(self.name)

class StellantisAirConditioningButton(StellantisBaseButton):
    @property
    def available(self):
        if not self._coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            return False
        min_charge = 50
        if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID:
            min_charge = 20
        check_battery_level = "battery" in self._coordinator._sensors and self._coordinator._sensors["battery"] and int(self._coordinator._sensors["battery"]) >= min_charge
        check_battery_charging = "battery_charging" in self._coordinator._sensors and self._coordinator._sensors["battery_charging"] == "InProgress"
        return super().available and (check_battery_level or check_battery_charging)

    async def async_press(self):
        await self._coordinator.send_air_conditioning_command(self.name)