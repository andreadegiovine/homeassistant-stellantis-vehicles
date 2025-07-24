import logging
from datetime import timedelta

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.exceptions import ConfigEntryAuthFailed

from .base import ( StellantisBaseButton, StellantisBaseActionButton )
from .utils import get_datetime

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
            name = "doors_lock",
            key = "doors_lock",
            translation_key = "doors_lock",
            icon = "mdi:car-door-lock"
        )
        entities.extend([StellantisDoorButton(coordinator, description, "lock")])

        description = ButtonEntityDescription(
            name = "doors_unlock",
            key = "doors_unlock",
            translation_key = "doors_unlock",
            icon = "mdi:car-door-lock-open"
        )
        entities.extend([StellantisDoorButton(coordinator, description, "unlock")])

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
            name = "preconditioning_start",
            key = "preconditioning_start",
            translation_key = "preconditioning_start",
            icon = "mdi:air-conditioner"
        )
        entities.extend([StellantisPreconditioningButton(coordinator, description, "activate")])

        description = ButtonEntityDescription(
            name = "preconditioning_stop",
            key = "preconditioning_stop",
            translation_key = "preconditioning_stop",
            icon = "mdi:air-conditioner"
        )
        entities.extend([StellantisPreconditioningButton(coordinator, description, "deactivate")])

        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = ButtonEntityDescription(
                name = "charge_start",
                key = "charge_start",
                translation_key = "charge_start",
                icon = "mdi:play"
            )
            entities.extend([StellantisChargingStartStopButton(coordinator, description, "immediate")])

            description = ButtonEntityDescription(
                name = "charge_stop",
                key = "charge_stop",
                translation_key = "charge_stop",
                icon = "mdi:pause"
            )
            entities.extend([StellantisChargingStartStopButton(coordinator, description, "delayed")])

    async_add_entities(entities)


class StellantisWakeUpButton(StellantisBaseButton):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description)
        self.is_scheduled = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self.scheduled_press()

    async def scheduled_press(self, now=None):
        if self.is_scheduled is not None:
            self.is_scheduled()
            self.is_scheduled = None
            try:
                await self.async_press()
            except ConfigEntryAuthFailed as e:
                _LOGGER.error("Authentication failed during scheduled press: %s", str(e))
                # Optionally, add recovery logic here
            except Exception as e:
                _LOGGER.error("Unexpected error during scheduled press: %s", str(e))
                raise
        next_run = get_datetime() + timedelta(hours=12)
        self.is_scheduled = async_track_point_in_time(self._coordinator._hass, self.scheduled_press, next_run)

    async def async_press(self):
        await self._coordinator.send_wakeup_command(self.name)

class StellantisDoorButton(StellantisBaseActionButton):
    async def async_press(self):
        await self._coordinator.send_doors_command(self.name, self._action)

class StellantisHornButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_horn_command(self.name)

class StellantisLightsButton(StellantisBaseButton):
    async def async_press(self):
        await self._coordinator.send_lights_command(self.name)

class StellantisChargingStartStopButton(StellantisBaseActionButton):
    @property
    def available(self):
        charging_inprogress_stopped = self._coordinator._sensors.get("battery_charging") in ["InProgress", "Stopped"]
        charging_finished = self._coordinator._sensors.get("battery_charging") == "Finished"
        current_battery = self._coordinator._sensors.get("battery")
        return super().available and self._coordinator._sensors.get("time_battery_charging_start") and (charging_inprogress_stopped or (charging_finished and current_battery and int(float(current_battery)) < 100))

    async def async_press(self):
        await self._coordinator.send_charge_command(self.name, False, self._action)

class StellantisPreconditioningButton(StellantisBaseActionButton):
    @property
    def available(self):
        if self._coordinator.vehicle_type not in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            return False

        doors_locked = self._coordinator._sensors.get("doors") == None or "Locked" in self._coordinator._sensors.get("doors")

        min_charge = 1
        # Waiting the min value from https://github.com/andreadegiovine/homeassistant-stellantis-vehicles/issues/226
        # min_charge = 50
        # if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID:
        #     min_charge = 20
        check_battery_level = self._coordinator._sensors.get("battery") and int(float(self._coordinator._sensors.get("battery"))) >= min_charge
        check_battery_charging = self._coordinator._sensors.get("battery_charging") == "InProgress"

        return super().available and doors_locked and (check_battery_level or check_battery_charging)

    async def async_press(self):
        await self._coordinator.send_preconditioning_command(self.name, self._action)