"""Vehicle coordinator of the Leapmotor client: remote commands over the cloud API."""
import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from ...base import StellantisVehicleCoordinator
from ...const import DOMAIN
from ...exceptions import CommunicationError
from ...utils import SENSITIVE_DATA_FILTER

from .const import (
    SUPPORTED_ENTITIES,
    COMMAND_LOCK,
    COMMAND_UNLOCK,
    COMMAND_FIND_CAR,
    COMMAND_CLIMATE_ON,
    COMMAND_CLIMATE_OFF,
    COMMAND_CLIMATE_OFF_T03
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class LeapmotorVehicleCoordinator(StellantisVehicleCoordinator):
    def supports(self, platform: str, key: str) -> bool:
        return key in SUPPORTED_ENTITIES.get(platform, ())

    async def _send_remote_command(self, service: str, message: Any) -> str | None:
        """ Send the command; its result is then followed in the background. """
        try:
            control = await self._stellantis.send_remote_command(self._vehicle, service, message)
        except CommunicationError as err:
            # Shown to the user as is: a refused PIN, an offline vehicle...
            raise HomeAssistantError(
                translation_domain = DOMAIN,
                translation_key = "command_refused",
                translation_placeholders = {"reason": str(err)}
            ) from err
        action_id = str(control.get("remoteCtlId") or f"leapmotor-{id(control)}")
        self.config_entry.async_create_background_task(self.hass, self._follow_remote_command(action_id, control), f"{DOMAIN} remote command result")
        return action_id

    async def _follow_remote_command(self, action_id: str, control: dict[str, Any]) -> None:
        """ Record the outcome of a sent command in its history, then refresh the status. """
        try:
            done = await self._stellantis.wait_remote_command(control)
            update = "0" if done else "300"
        except Exception as err:
            _LOGGER.warning("Could not read the result of a remote command for vehicle %s: %s", self._vehicle["vin"], err)
            update = "failed"
        await self.update_command_history(action_id, update)
        if update == "0":
            await self.async_request_refresh()

    async def send_doors_command(self, button_name, action):
        await self.send_command(button_name, *(COMMAND_LOCK if action == "lock" else COMMAND_UNLOCK))

    async def send_horn_command(self, button_name):
        """ The closest Leapmotor has: "find my car" sounds the horn and flashes the lights. """
        await self.send_command(button_name, *COMMAND_FIND_CAR)

    async def send_preconditioning_command(self, button_name, action):
        if action == "activate":
            command = COMMAND_CLIMATE_ON
        elif str(self._vehicle.get("car_type") or "").upper() == "T03":
            command = COMMAND_CLIMATE_OFF_T03
        else:
            command = COMMAND_CLIMATE_OFF
        await self.send_command(button_name, *command)
