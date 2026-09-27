"""Normalize Stellantis RemoteServices vehicle events received over MQTT."""
from typing import Any

from .const import FDS_FEATURE_CODES

# parse_mqtt_event() keys that change on every event by design, not with the
# vehicle state.
_BOOKKEEPING_KEYS = {"timestamp", "event_counter", "event_reason_code", "signal_quality"}


# Stellantis uses hour 34 (and similar out-of-range values) as an "unset" marker
# for timer slots that were never configured.
def _parse_mqtt_timer(program:dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a single precond/charge timer program, or None if unset."""
    if not program:
        return None
    hour = program.get("hour")
    minute = program.get("minute")
    if hour is None or not 0 <= hour <= 23:
        return None
    timer = {
        "hour": hour,
        "minute": minute if minute is not None else 0,
    }
    if "on" in program:
        timer["enabled"] = bool(program.get("on"))
    if "day" in program:
        # Weekday mask, Stellantis order (index 0 = Monday).
        timer["days"] = program.get("day")
    return timer


def _parse_mqtt_features(codes:list[str] | None) -> dict[str, bool]:
    """Map raw "fds" feature codes to named capability flags.

    A code being present means the vehicle reports that capability as
    enabled. Codes not found in FDS_FEATURE_CODES are kept under their raw
    code so nothing is silently dropped while the mapping is filled in.
    """
    if not codes:
        return {}
    return {FDS_FEATURE_CODES.get(code, code): True for code in codes}


def parse_mqtt_event(payload:dict[str, Any]) -> dict[str, Any]:
    """Normalize a Stellantis RemoteServices vehicle event (MQTT_EVENT_TOPIC).

    Turns the raw push payload into a stable, self-describing structure for
    the coordinator (see apply_mqtt_event). Missing sections yield None/falsy
    values instead of raising, so downstream code can always rely on the
    shape. Raw enum codes whose meaning is not yet confirmed are passed
    through unchanged with a ``_code`` suffix.

    Field meanings come from ~13,500 real events of one vehicle (2026-08-25
    to 2026-09-26), checked against the REST status reported at the same
    timestamp where REST has an equivalent. Each message is a full state
    snapshot, not a delta, and messages can arrive out of order; this
    function does not handle that, see the caller.
    """
    charging = payload.get("charging_state") or {}
    precond = payload.get("precond_state") or {}
    doors = payload.get("doors_state") or {}
    opening_state = doors.get("doors_opening_state") or []
    locking_state = doors.get("doors_locking_state")
    hmi_state = charging.get("hmi_state")
    cable_detected = charging.get("cable_detected")
    sev_state = payload.get("sev_state")

    return {
        "vin": payload.get("vin"),
        "timestamp": payload.get("date"),
        # Increasing counter + trigger code for the event stream itself.
        # reason: 0 session-start snapshot (always counter 1), 2 ignition,
        # 3/4 charging, 5 doors, 6 electrical network state; 1 is rare.
        "event_counter": payload.get("obj_counter"),
        "event_reason_code": payload.get("reason"),
        "signal_quality": payload.get("signal_quality"),
        # 0 off, 3 briefly while switching on, 5 high-voltage network active;
        # drops back to 0 minutes after switch-off and stays 0 while charging.
        "electric_network_state_code": payload.get("etat_res_elec"),
        # sev_state: 0 = off, 1 = on/ready, 2 = starting (lasts up to ~5s).
        # 88 of 96 on-cycles went 0 -> 1 -> 2 -> 1 -> 0, the rest skipped a step.
        "vehicle_on": sev_state in (1, 2),
        "vehicle_on_code": sev_state,
        "last_off_at": payload.get("sev_stop_date"),
        # Lags behind REST and spikes, so entities keep using REST for these.
        "battery": {
            "level": charging.get("soc_batt"),
            "autonomy_km": charging.get("autonomy_zev"),
        },
        "charging": {
            "available": bool(charging.get("available")),
            # cable_detected is inverted: 0 = plugged, 1 = unplugged. Checked
            # against REST plugged while charging, plugged after charge
            # complete, and unplugged.
            "plugged": None if cable_detected is None else cable_detected == 0,
            "cable_detected_code": cable_detected,
            # Same values as REST chargingRate and remainingTime (in minutes),
            # but remaining_time is not capped at 10h30. Both read 0 until
            # measured and go stale once charging stops.
            "rate": charging.get("rate"),
            "remaining_time_min": charging.get("remaining_time"),
            # 0 = REST chargingMode "Slow", 2 = "No"; others not seen yet.
            "mode_code": charging.get("mode"),
            "type_code": charging.get("type"),
            "hmi_state_code": hmi_state,
            "in_progress": hmi_state == 1,
            "complete": hmi_state == 3,
            # Stored start time for delayed charging (same as REST
            # nextDelayedTime), reported even when no delayed charge is set up.
            "delayed_start_time": _parse_mqtt_timer(charging.get("program")),
        },
        "preconditioning": {
            "available": bool(precond.get("available")),
            "asap": bool(precond.get("asap")),
            # 0/1/2 = REST airConditioning Disabled/Enabled/Finished.
            "status_code": precond.get("status"),
            "programs": {
                name: _parse_mqtt_timer(program)
                for name, program in (precond.get("programs") or {}).items()
            },
        },
        "doors": {
            # 1/7 = locked (7 is the transient mid-lock step), 0/3 = unlocked
            # (0 is the transient mid-unlock step) - treat both as their
            # settled state rather than exposing 4 separate values.
            "locked": locking_state in (1, 7),
            "locking_state_code": locking_state,
            "opening_state": opening_state,
            # Indices 0-4 matched against REST doorsState.opening at the same
            # timestamp. 5 was never set; 6 follows the driver's door with a
            # short lag and has no REST counterpart, so both stay unmapped.
            "open": {
                name: bool(opening_state[index])
                for index, name in enumerate(("driver", "passenger", "rear_left", "rear_right", "trunk"))
                if index < len(opening_state)
            },
            "any_open": any(opening_state),
        },
        "security": {
            "stolen": bool(payload.get("stolen_state")),
        },
        "privacy": {
            "customer": payload.get("privacy_customer"),
            "applicable": payload.get("privacy_applicable"),
            "applicable_max": payload.get("privacy_applicable_max"),
        },
        # Supported remote-service feature codes reported by the vehicle,
        # mapped to named flags (see FDS_FEATURE_CODES).
        "features": _parse_mqtt_features(payload.get("fds")),
    }


def event_content(event:dict[str, Any]) -> dict[str, Any]:
    """The parsed event's vehicle state, without the per-event bookkeeping fields."""
    return {k: v for k, v in event.items() if k not in _BOOKKEEPING_KEYS}
