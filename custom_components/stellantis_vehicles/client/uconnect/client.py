"""The Uconnect (ex FCA: Fiat, Jeep, Alfa Romeo, ...) cloud client, built on py-uconnect."""
import asyncio
import logging
import time
from typing import Any

from py_uconnect import (
    BRANDS,
    COMMANDS_BY_NAME,
    AuthenticationError,
    Client,
    CommandTimeoutError,
    PinAuthenticationError,
    UconnectError,
)

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...client_base import BaseVehiclesClient
from ...exceptions import CommunicationError
from ...interfaces import VehiclesClient
from ...utils import SENSITIVE_DATA_FILTER, log_call
from .coordinator import UconnectVehicleCoordinator
from .status import normalize_status, vehicle_type

from ...const import FIELD_REMOTE_COMMANDS

from .const import (
    MOBILE_APP,
    FIELD_BRAND,
    FIELD_PIN_CODE,
    STATUS_CACHE_SECONDS,
    COMMAND_TIMEOUT
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class UconnectVehicles(BaseVehiclesClient, VehiclesClient):
    coordinator_class = UconnectVehicleCoordinator

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self._client: Client | None = None
        # Kept out of the configuration, which is logged and exported.
        self._secrets: dict[str, Any] = {}
        self._refresh_lock = asyncio.Lock()
        self._refreshed_at: float | None = None

    def save_config(self, data: dict[str, Any]) -> None:
        data = dict(data)
        for key in (CONF_PASSWORD, FIELD_PIN_CODE):
            if key in data:
                self._secrets[key] = data.pop(key)
                self.logger_filter.add_custom_value(self._secrets[key])
        super().save_config(data)

    @property
    def _brand(self):
        return BRANDS[str(self.get_config(FIELD_BRAND)).upper()]

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client(
                self.get_config(CONF_EMAIL),
                self._secrets.get(CONF_PASSWORD),
                self._secrets.get(FIELD_PIN_CODE) or None,
                self._brand,
                session=async_get_clientsession(self._hass),
            )
        return self._client

    async def _call(self, call):
        """ Await a library call, translating its errors.

        Refused credentials start a reauthentication; a refused PIN or any
        other cloud error is a communication error (the PIN only matters for
        commands, and a wrong one must not lock the whole entry).
        """
        try:
            return await call
        except PinAuthenticationError as err:
            raise CommunicationError(f"PIN rejected: {err}") from err
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UconnectError as err:
            raise CommunicationError(str(err)) from err

    async def async_login(self) -> str:
        """ Log in and return the account id; raises the library's errors as they are. """
        client = self._get_client()
        await client.api.login()
        return client.api.uid

    async def async_start(self) -> None:
        """ Nothing to keep alive: the library logs in and renews its credentials itself. """

    async def async_shutdown(self) -> None:
        self._shutting_down = True
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        if self._client is not None:
            # The Home Assistant session is shared: the client leaves it open.
            await self._client.close()
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
        api = self._client.api if self._client else None
        return {
            "uconnect": {
                "brand": self.get_config(FIELD_BRAND),
                "logged_in": bool(api and api.uid),
                "remote_commands": self.remote_commands,
                "last_refresh_age_seconds": round(time.monotonic() - self._refreshed_at) if self._refreshed_at else None,
            },
        }

    async def _refresh(self, force: bool = False) -> None:
        """ Load every vehicle of the account; a recent load is reused (one call serves every vehicle). """
        async with self._refresh_lock:
            if not force and self._refreshed_at is not None and time.monotonic() - self._refreshed_at < STATUS_CACHE_SECONDS:
                return
            await self._call(self._get_client().refresh())
            self._refreshed_at = time.monotonic()

    @log_call
    async def get_user_vehicles(self, force=False):
        if force:
            self._vehicles = []
        if not self._vehicles:
            await self._refresh(force=True)
            vehicles = []
            for vehicle in self._get_client().vehicles.values():
                data = {
                    "vin": vehicle.vin,
                    "vehicle_id": None,
                    "type": vehicle_type(vehicle),
                    "brand": vehicle.make.title() if vehicle.make else MOBILE_APP,
                    "model": vehicle.model,
                    "region": vehicle.region,
                    "sdp": vehicle.sdp,
                    "fuel_type": vehicle.fuel_type,
                    "commands": list(vehicle.supported_commands),
                    "services": list(vehicle.enabled_services),
                }
                if vehicle.image_url:
                    try:
                        data["picture"] = await self.resize_and_save_picture(vehicle.image_url, vehicle.vin)
                    except Exception as err:
                        _LOGGER.warning("Unable to download and save the vehicle picture: %s", err)
                vehicles.append(data)
            vins = {vehicle["vin"] for vehicle in vehicles}
            if self._entry is not None:
                self.logger_filter.set_entry_extra_values(self._entry.entry_id, vins)
            else:
                for vin in vins:
                    self.logger_filter.add_custom_value(vin)
            self._vehicles = vehicles
        return self._vehicles

    @log_call
    async def get_vehicle_status(self, vehicle):
        await self._refresh()
        current = self._get_client().vehicles.get(vehicle["vin"])
        return normalize_status(current) if current else {}

    async def send_remote_command(self, vin: str, command: str, params: dict[str, Any] | None = None) -> str:
        """ Send a remote command; returns its correlation id for wait_remote_command. """
        return await self._call(self._get_client().command(vin, COMMANDS_BY_NAME[command], params))

    async def wait_remote_command(self, vin: str, correlation_id: str) -> bool:
        """ Whether the vehicle carried the command out; False if it did not report back in time. """
        try:
            return await self._call(self._get_client().wait_for_operation(vin, correlation_id, timeout=COMMAND_TIMEOUT))
        except CommunicationError as err:
            if isinstance(err.__cause__, CommandTimeoutError):
                return False
            raise
