"""The Leapmotor (international) cloud client."""
import logging
from typing import Any
from uuid import uuid4

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from ...client_base import BaseVehiclesClient
from ...interfaces import VehiclesClient
from ...utils import SENSITIVE_DATA_FILTER, log_call
from .api import LeapmotorApi, LeapmotorAuthError, LeapmotorCertificateError
from .certificate import async_ensure_app_certificate
from .coordinator import LeapmotorVehicleCoordinator
from .status import has_fuel, normalize_status

from ...const import (
    FIELD_REMOTE_COMMANDS,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

from .const import (
    MOBILE_APP,
    FIELD_PIN_CODE,
    FIELD_DEVICE_ID
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class LeapmotorVehicles(BaseVehiclesClient, VehiclesClient):
    coordinator_class = LeapmotorVehicleCoordinator

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self._api: LeapmotorApi | None = None
        # Kept out of the configuration, which is logged and exported.
        self._secrets: dict[str, Any] = {}

    def save_config(self, data: dict[str, Any]) -> None:
        data = dict(data)
        for key in (CONF_PASSWORD, FIELD_PIN_CODE):
            if key in data:
                self._secrets[key] = data.pop(key)
                self.logger_filter.add_custom_value(self._secrets[key])
        super().save_config(data)

    def _session_getter(self):
        self.start_session()
        return self._session

    async def _get_api(self) -> LeapmotorApi:
        if self._api is None:
            try:
                certificate = await async_ensure_app_certificate(self._hass)
            except LeapmotorCertificateError as err:
                _LOGGER.error("Leapmotor app certificate not available: %s", err)
                raise
            self._api = LeapmotorApi(
                self._session_getter,
                self.get_config(CONF_EMAIL),
                self._secrets.get(CONF_PASSWORD),
                self.get_config(FIELD_DEVICE_ID) or uuid4().hex,
                *certificate
            )
        return self._api

    async def async_login(self) -> str:
        """ Log in and return the account id; raises on refused credentials. """
        api = await self._get_api()
        await api.ensure_login()
        return api.user_id

    async def async_start(self) -> None:
        """ Nothing to keep alive: the session is opened by the first request. """

    async def async_shutdown(self) -> None:
        self._shutting_down = True
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        await self.close_session()
        if self._entry is not None:
            self.logger_filter.remove_entry_values(self._entry.entry_id)

    @property
    def remote_commands(self) -> bool:
        """ Remote commands need the vehicle PIN. """
        return self.get_config(FIELD_REMOTE_COMMANDS) is not False and bool(self._secrets.get(FIELD_PIN_CODE))

    @property
    def commands_available(self) -> bool:
        return self.remote_commands

    def diagnostics(self) -> dict[str, Any]:
        return {
            "leapmotor": {
                "logged_in": bool(self._api and self._api.logged_in),
                "remote_commands": self.remote_commands,
                "last_requests": dict(self._api.last_results) if self._api else {},
            },
        }

    async def _call(self, method: str, *args):
        """ Run an API call; refused credentials start a reauthentication. """
        api = await self._get_api()
        try:
            return await getattr(api, method)(*args)
        except LeapmotorAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

    @log_call
    async def get_user_vehicles(self, force=False):
        if force:
            self._vehicles = []
        if not self._vehicles:
            vehicles = []
            for item in await self._call("vehicles"):
                vehicle = {
                    "vin": str(item["vin"]),
                    "vehicle_id": str(item["carId"]) if item.get("carId") is not None else None,
                    "car_type": str(item.get("carType") or ""),
                    "shared": bool(item.get("shared")),
                    "brand": MOBILE_APP,
                    "type": VEHICLE_TYPE_ELECTRIC,
                }
                # A range extender only shows in the status: it reports fuel.
                try:
                    if has_fuel(await self._status(vehicle)):
                        vehicle["type"] = VEHICLE_TYPE_HYBRID
                except ConfigEntryAuthFailed:
                    raise
                except Exception as err:
                    _LOGGER.debug("Could not read the status of a vehicle to tell its engine type: %s", err)
                try:
                    picture = await self.resize_and_save_picture(None, vehicle["vin"], lambda vin=vehicle["vin"]: self._call("picture", vin))
                    if picture:
                        vehicle["picture"] = picture
                except ConfigEntryAuthFailed:
                    raise
                except Exception as err:
                    _LOGGER.warning("Unable to download and save the vehicle picture: %s", err)
                vehicles.append(vehicle)
            ids = {value for vehicle in vehicles for value in (vehicle["vin"], vehicle["vehicle_id"]) if value}
            if self._entry is not None:
                self.logger_filter.set_entry_extra_values(self._entry.entry_id, ids)
            else:
                for value in ids:
                    self.logger_filter.add_custom_value(value)
            self._vehicles = vehicles
        return self._vehicles

    async def _status(self, vehicle: dict[str, Any]) -> dict[str, Any]:
        return await self._call("status", vehicle["vin"], vehicle.get("car_type"), vehicle.get("vehicle_id") if vehicle.get("shared") else None)

    @log_call
    async def get_vehicle_status(self, vehicle):
        return normalize_status(await self._status(vehicle))

    async def send_remote_command(self, vehicle: dict[str, Any], command_id: str, command_content: str) -> dict[str, Any]:
        """ Send a remote command; returns what wait_remote_command needs to follow it. """
        return await self._call("remote_control", vehicle["vin"], command_id, command_content, str(self._secrets.get(FIELD_PIN_CODE)))

    async def wait_remote_command(self, control: dict[str, Any]) -> bool:
        return await self._call("wait_remote_control", control)
