"""Vehicle coordinator of the Uconnect client: remote commands through py-uconnect."""
import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from ...base import StellantisVehicleCoordinator
from ...const import DOMAIN
from ...exceptions import CommunicationError
from ...utils import SENSITIVE_DATA_FILTER, rate_limit

from .const import (
    UPDATE_INTERVAL,
    SUPPORTED_ENTITIES,
    COMMAND_ENTITIES,
    COMMAND_DOORS_LOCK,
    COMMAND_DOORS_UNLOCK,
    COMMAND_LIGHTS_HORN,
    COMMAND_LIGHTS,
    COMMAND_PRECOND_ON,
    COMMAND_PRECOND_OFF,
    COMMAND_HVAC_ON,
    COMMAND_HVAC_OFF,
    COMMAND_DEEP_REFRESH,
    COMMAND_CHARGE
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class UconnectVehicleCoordinator(StellantisVehicleCoordinator):
    default_update_interval = UPDATE_INTERVAL
    # The trips the Uconnect cloud keeps are not read yet.
    builds_trips = True

    @property
    def _commands(self) -> set[str]:
        """ Remote commands the vehicle supports (its enabled services). """
        return set(self._vehicle.get("commands") or ())

    def supports(self, platform: str, key: str) -> bool:
        needed = COMMAND_ENTITIES.get((platform, key))
        if needed is not None:
            return any(command in self._commands for command in needed)
        return key in SUPPORTED_ENTITIES.get(platform, ())

    def command_available(self, key: str) -> bool | None:
        if key == "charge_start":
            # Charging can start once the vehicle is plugged and not charging yet.
            # Read from the status itself: the entities holding these values
            # may not exist yet when the button is added.
            electric = next((energy for energy in (self.data or {}).get("energies") or [] if energy.get("type") == "Electric"), {})
            charging = ((electric.get("extension") or {}).get("electric") or {}).get("charging") or {}
            return bool(charging.get("plugged")) and charging.get("status") != "InProgress"
        if key in ("preconditioning_start", "preconditioning_stop"):
            # The vehicle decides: there is no known battery threshold.
            return True
        return None

    def diagnostics(self) -> dict[str, Any]:
        return {key: self._vehicle.get(key) for key in ("model", "region", "sdp", "fuel_type", "commands", "services")}

    async def _send_remote_command(self, service: str, message: Any) -> str | None:
        """ Send the command; its outcome is followed in the background (see _command_result_waiter). """
        vin = self._vehicle["vin"]
        try:
            correlation_id = await self._stellantis.send_remote_command(vin, service, message)
        except CommunicationError as err:
            # Shown to the user as is: a refused PIN, an unsupported command...
            raise HomeAssistantError(
                translation_domain = DOMAIN,
                translation_key = "command_refused",
                translation_placeholders = {"reason": str(err)}
            ) from err
        return correlation_id

    def _command_result_waiter(self, action_id: str):
        return self._stellantis.wait_remote_command(self._vehicle["vin"], action_id)

    def _first_supported(self, *commands: str) -> str:
        return next((command for command in commands if command in self._commands), commands[0])

    async def send_doors_command(self, button_name, action):
        await self.send_command(button_name, COMMAND_DOORS_LOCK if action == "lock" else COMMAND_DOORS_UNLOCK, None)

    async def send_horn_command(self, button_name):
        """ The horn sounds with the lights flashing, as in the official apps. """
        await self.send_command(button_name, COMMAND_LIGHTS_HORN, None)

    async def send_lights_command(self, button_name):
        await self.send_command(button_name, COMMAND_LIGHTS, None)

    async def send_preconditioning_command(self, button_name, action):
        if action == "activate":
            command = self._first_supported(COMMAND_PRECOND_ON, COMMAND_HVAC_ON)
        else:
            command = self._first_supported(COMMAND_PRECOND_OFF, COMMAND_HVAC_OFF)
        await self.send_command(button_name, command, None)

    @rate_limit(6, 1200) # 6 per 20 min, as for the PSA wakeup
    async def send_wakeup_command(self, button_name):
        """ Deep refresh: the vehicle sends a fresh status to the cloud. """
        await self.send_command(button_name, COMMAND_DEEP_REFRESH, None)

    async def send_charge_command(self, button_name, update_only_time = False, action = "immediate"):
        """ Start charging now: Uconnect has no charging start time to set. """
        if update_only_time or action != "immediate":
            raise NotImplementedError
        await self.send_command(button_name, COMMAND_CHARGE, None)
