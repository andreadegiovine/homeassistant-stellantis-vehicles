"""Diagnostics support for Stellantis Vehicles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .base import StellantisVehicleCoordinator
from .const import (
    FIELD_ANONYMIZE_LOGS,
    FIELD_COUNTRY_CODE,
    FIELD_MOBILE_APP,
    FIELD_NOTIFICATIONS,
    FIELD_REMOTE_COMMANDS,
)

# Keys whose value is a secret or personal data. async_redact_data walks nested
# dicts/lists and replaces every matching value with "**REDACTED**", so only this
# list needs maintaining. It overlaps with SensitiveDataFilter.MASKED_ENTRY_KEYS
# in utils.py; the extra entries here cover the raw API payload (GPS position,
# VIN) that never reaches the log filter.
TO_REDACT = {
    "access_token",
    "refresh_token",
    "id_token",
    "oauth_code",
    "code",
    "code_verifier",
    "code_challenge",
    "customer_id",
    "pin",
    "email",
    "password",
    "vin",
    "vehicle_id",
    "text_abrp_token",
    "lastPosition",
    "coordinates",
    "latitude",
    "longitude",
    # HAL navigation block: its "href" URLs embed the opaque PSA vehicle id as a
    # path segment, which async_redact_data cannot reach inside the string.
    "_links",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    stellantis = entry.runtime_data

    oauth_config = stellantis.get_config("oauth") or {}
    mqtt_config = stellantis.get_config("mqtt") or {}

    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            # Structure only - the values may still hold tokens on entries that
            # have not been migrated to the nested "oauth"/"mqtt" layout yet.
            "data_keys": sorted(entry.data),
        },
        "config": {
            "keys": sorted(stellantis._config),  # noqa: SLF001
            "mobile_app": stellantis.get_config(FIELD_MOBILE_APP),
            "country_code": stellantis.get_config(FIELD_COUNTRY_CODE),
            "remote_commands": stellantis.get_config(FIELD_REMOTE_COMMANDS),
            "anonymize_logs": stellantis.get_config(FIELD_ANONYMIZE_LOGS),
            "notifications": stellantis.get_config(FIELD_NOTIFICATIONS),
        },
        "oauth": {
            # "expires_in" holds the ISO timestamp of the expiry moment.
            "token_expires_at": oauth_config.get("expires_in"),
            "refresh_scheduled": stellantis._oauth_token_scheduled is not None,  # noqa: SLF001
        },
        "mqtt": {
            "enabled": stellantis.remote_commands,
            "connected": bool(
                stellantis._mqtt is not None and stellantis._mqtt.is_connected()  # noqa: SLF001
            ),
            "token_expires_at": mqtt_config.get("expires_in"),
            "refresh_token_expires_at": mqtt_config.get("refresh_token_expires_at"),
            "refresh_scheduled": stellantis._mqtt_token_scheduled is not None,  # noqa: SLF001
            "request_pending_reconnect": stellantis._mqtt_last_request is not None,  # noqa: SLF001
        },
        "vehicles": [
            _coordinator_diagnostics(coordinator)
            for coordinator in stellantis._coordinator_dict.values()  # noqa: SLF001
        ],
    }


def _scrub_substrings(value: Any, secrets: list[str]) -> Any:
    """Replace known secret values wherever they appear inside a string.

    async_redact_data only masks whole values by key; the raw API payload also
    carries the VIN and the PSA vehicle id embedded in URLs and free-text
    fields, so those get scrubbed as substrings here.
    """
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "**REDACTED**")
        return value
    if isinstance(value, dict):
        return {key: _scrub_substrings(val, secrets) for key, val in value.items()}
    if isinstance(value, list):
        return [_scrub_substrings(item, secrets) for item in value]
    return value


def _coordinator_diagnostics(
    coordinator: StellantisVehicleCoordinator,
) -> dict[str, Any]:
    """Return the redacted runtime state of a single vehicle coordinator."""
    vin = coordinator._vehicle.get("vin") or ""  # noqa: SLF001
    # Substrings to scrub from the raw payload; guard the length so a short or
    # empty id can never blank out unrelated text.
    secrets = [
        value
        for value in (vin, coordinator._vehicle.get("vehicle_id") or "")  # noqa: SLF001
        if len(value) >= 8
    ]
    return {
        # Keep the first 8 characters (WMI + descriptor section: manufacturer and
        # model) and the last 3 (tail of the serial, enough to line a report up
        # with a vehicle); the middle digits that identify the individual car
        # stay masked.
        "vin": (
            f"{vin[:8]}{'*' * (len(vin) - 11)}{vin[-3:]}"
            if len(vin) > 11
            else vin or None
        ),
        "type": coordinator._vehicle.get("type"),  # noqa: SLF001
        "brand": coordinator._vehicle.get("brand"),  # noqa: SLF001
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval is not None
            else None
        ),
        "last_update_success": coordinator.last_update_success,
        # Error of the last failed refresh - the first thing to check for
        # "entities unavailable". Truncated; a token in an API URL is only
        # masked here when the user has anonymized logs enabled.
        "last_exception": (
            repr(coordinator.last_exception)[:500]
            if coordinator.last_exception is not None
            else None
        ),
        "empty_status_count": coordinator._empty_status_count,  # noqa: SLF001
        "vehicle_removed": coordinator._vehicle_removed,  # noqa: SLF001
        "disabled_commands": coordinator._disabled_commands,  # noqa: SLF001
        "commands_history": coordinator.command_history,
        "pending_programs": getattr(coordinator, "_pending_programs", None),
        "sensors": _scrub_substrings(
            async_redact_data(coordinator._sensors, TO_REDACT), secrets  # noqa: SLF001
        ),
        "raw_status": _scrub_substrings(
            async_redact_data(coordinator._data, TO_REDACT), secrets  # noqa: SLF001
        ),
    }
