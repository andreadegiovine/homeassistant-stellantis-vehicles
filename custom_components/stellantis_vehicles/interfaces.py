"""Contracts shared by every vehicle cloud client.

The integration root only holds what is common to all clients (entities,
coordinator, config flow glue, utilities). Everything specific to one cloud
lives in its own package under ``client/`` and implements ``VehiclesClient``.
"""
from abc import ABC, abstractmethod
from typing import Any

from homeassistant.config_entries import ConfigEntry


class VehiclesClient(ABC):
    """What the shared code needs from a vehicle cloud client."""

    @abstractmethod
    def save_config(self, data: dict[str, Any]) -> None:
        """Merge values into the client's runtime configuration."""

    @abstractmethod
    def get_config(self, key: str) -> Any:
        """Return a runtime configuration value, or None."""

    @abstractmethod
    def set_entry(self, entry: ConfigEntry) -> None:
        """Bind the client to its config entry."""

    @abstractmethod
    async def async_start(self) -> None:
        """Start whatever keeps the session alive (token refresh, live channel)."""

    @abstractmethod
    async def async_shutdown(self) -> None:
        """Tear down everything created for the config entry."""

    @abstractmethod
    async def close_session(self) -> None:
        """Close the HTTP session."""

    @property
    @abstractmethod
    def remote_commands(self) -> bool:
        """Whether remote commands are enabled for this entry."""

    @property
    @abstractmethod
    def commands_available(self) -> bool:
        """Whether a remote command can be sent right now."""

    @property
    @abstractmethod
    def coordinators(self) -> list:
        """The vehicle coordinators created so far."""

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """Client-specific, secret-free sections of the diagnostics download."""

    @abstractmethod
    async def send_abrp_data(self, params: dict[str, Any]) -> None:
        """Push telemetry to A Better Routeplanner."""

    @abstractmethod
    async def get_user_vehicles(self, force: bool = False) -> list[dict[str, Any]]:
        """Return the vehicles of the account, each with at least a ``vin``."""

    @abstractmethod
    async def get_vehicle_status(self, vehicle: dict[str, Any]) -> dict[str, Any]:
        """Return the current status of a vehicle."""

    @abstractmethod
    async def async_get_coordinator(self, vehicle: dict[str, Any]):
        """Return the (cached) data coordinator of a vehicle."""

    @abstractmethod
    def get_vehicle_stored_config(self, vin: str, key: str) -> Any:
        """Return a per-vehicle value stored in the config entry."""

    @abstractmethod
    def update_vehicle_stored_config(self, vin: str, key: str, value: Any) -> None:
        """Store a per-vehicle value in the config entry."""

    @abstractmethod
    def prune_stored_vehicle_configs(self, live_vins: set[str]) -> list[str]:
        """Drop stored config of vehicles no longer on the account."""

    @abstractmethod
    async def hass_notify(self, translation_key: str) -> None:
        """Create a persistent notification."""
