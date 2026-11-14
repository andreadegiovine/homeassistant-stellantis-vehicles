"""Translate a Leapmotor vehicle status into the status layout the shared
entities read (the one of the PSA API), so the same sensors serve both clouds.

Leapmotor reports numbered signals whose meaning was documented by the
MIT-licensed kerniger/leapmotor-ha project (Copyright (c) 2026 kerniger); the
charging heuristics below come from the real-vehicle findings recorded there.
"""
from datetime import UTC, datetime
from typing import Any

# Named fields some models (T03) report instead of the numbered signals.
_NAMED_FIELDS = {
    "soc": "1204",
    "chargeRemainTime": "1200",
    "batteryCurrent": "1178",
    "batteryVoltage": "1177",
    "expectedMileage": "3260",
    "speed": "1319",
    "totalMileage": "1318",
    "gearStatus": "1010",
    "latitude": "3725",
    "longitude": "3724",
    "acSwitch": "1938",
}
_NAMED_FLAGS = {
    "driverDoorLockStatus": "1298",
    "lbcmDriverDoorStatus": "1277",
    "rbcmDriverDoorStatus": "1278",
    "lbcmLeftRearDoorStatus": "1279",
    "rbcmRightRearDoorStatus": "1280",
    "bbcmBackDoorStatus": "1281",
    "bcmKeyPositionOn3": "1258",
}
_DOORS = {"Driver": "1277", "Passenger": "1278", "RearLeft": "1279", "RearRight": "1280", "Trunk": "1281"}
# Signals only range-extender (REEV) vehicles report: fuel level, fuel range.
_FUEL_SIGNALS = ("3235", "3259")


def _int(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_on(raw: Any) -> bool | None:
    value = _float(raw)
    return None if value is None else value != 0


def status_signals(status: dict[str, Any]) -> dict[str, Any]:
    """The numbered signals of a status, completed from the named fields."""
    raw = status.get("signal")
    signals = dict(raw) if isinstance(raw, dict) else {}
    for name, signal in _NAMED_FIELDS.items():
        if status.get(name) is not None:
            signals.setdefault(signal, status[name])
    for name, signal in _NAMED_FLAGS.items():
        if status.get(name) is not None:
            signals.setdefault(signal, 1 if status[name] else 0)
    if status.get("chargeState") is not None:
        charge_state = _int(status["chargeState"])
        signals.setdefault("1149", charge_state)
        signals.setdefault("47", 1 if charge_state in (1, 2) else 0)
    timestamp = status.get("collectTimeMs") if status.get("collectTimeMs") is not None else status.get("collectTime")
    if timestamp is not None:
        signals.setdefault("sts", timestamp)
    return signals


def has_fuel(status: dict[str, Any]) -> bool:
    """Whether the status is the one of a range-extender vehicle."""
    signals = status_signals(status)
    return any(signals.get(signal) is not None for signal in _FUEL_SIGNALS)


def _timestamp(signals: dict[str, Any]) -> str | None:
    """Vehicle-side time of the status as an ISO string (epoch seconds or milliseconds)."""
    value = _float(signals.get("sts"))
    if not value or value <= 0:
        return None
    if value > 1e11:
        value /= 1000
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _cannot_charge(signals: dict[str, Any]) -> bool:
    """Driving, or physically ready to: a cable cannot be charging the vehicle."""
    speed = _float(signals.get("1319"))
    return _int(signals.get("1010")) in (1, 2, 3) or (speed is not None and speed > 0) or _is_on(signals.get("1258")) is True


def _charging_power_kw(signals: dict[str, Any]) -> float | None:
    current, voltage = _float(signals.get("1178")), _float(signals.get("1177"))
    if current is None or voltage is None:
        return None
    if abs(current) < 1.0:
        return 0.0
    power = abs(current * voltage) / 1000.0
    # Between 1 and 3 A some models idle and others charge slowly.
    if abs(current) < 3.0 and _int(signals.get("1200")) is None and power < 1.0:
        return None
    return round(power, 3)


def _is_plugged(signals: dict[str, Any]) -> bool | None:
    if _cannot_charge(signals):
        return False
    connection = _int(signals.get("1149"))
    if connection is not None:
        # 3 shows up during a charge on REEVs, 4 is plugged and waiting for
        # the schedule, 5 is seen while driving.
        return connection in (1, 2, 3, 4)
    return _is_on(signals.get("47"))


def _is_charging(signals: dict[str, Any]) -> bool:
    if _is_plugged(signals) is False:
        return False
    connection = _int(signals.get("1149"))
    remaining = _int(signals.get("1200"))
    current = _float(signals.get("1178"))
    power = _charging_power_kw(signals)
    if current is not None:
        if abs(current) < 1.0:
            # A slow AC charge can bypass the pack current signal.
            return connection == 2 and remaining is not None and remaining > 0
        if abs(current) < 3.0:
            return remaining is not None and (remaining > 0 or (power is not None and power >= 1.0))
        return remaining is not None or (power is not None and power >= 1.0)
    if power is not None:
        return power >= 1.0 and remaining is not None
    return connection == 2


def _charging_section(signals: dict[str, Any]) -> dict[str, Any]:
    plugged = _is_plugged(signals)
    charging = _is_charging(signals)
    section: dict[str, Any] = {"plugged": plugged}
    if charging:
        section["status"] = "InProgress"
        remaining = _int(signals.get("1200"))
        # The shared sensor parses hours as a time of day.
        if remaining and remaining < 24 * 60:
            section["remainingTime"] = f"PT{remaining // 60}H{remaining % 60}M"
        dc_cable = _is_on(signals.get("1197"))
        if dc_cable is not None:
            section["chargingMode"] = "Quick" if dc_cable else "Slow"
    elif plugged:
        section["status"] = "Finished" if _is_on(signals.get("3736")) else "Stopped"
    elif plugged is False:
        section["status"] = "Disconnected"
    return section


def _position(signals: dict[str, Any], created_at: str | None) -> dict[str, Any] | None:
    # 2/3 keep the hemisphere sign, the other variants are absolute values.
    longitude = next((_float(signals.get(key)) for key in ("2", "3724", "2191") if _float(signals.get(key)) is not None), None)
    latitude = next((_float(signals.get(key)) for key in ("3", "3725", "2190") if _float(signals.get(key)) is not None), None)
    if longitude is None or latitude is None or (longitude == 0 and latitude == 0):
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {"createdAt": created_at},
    }


def normalize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Build the shared status layout from the ``data`` of a Leapmotor status response.

    Returns {} for a status without signals, which the coordinator treats as
    "no data" and keeps the last known values.
    """
    signals = status_signals(status)
    if not signals:
        return {}
    created_at = _timestamp(signals)
    result: dict[str, Any] = {"createdAt": created_at}
    if created_at:
        result["updatedAt"] = created_at

    if signals.get("1318") is not None:
        result["odometer"] = {"mileage": _float(signals["1318"]), "createdAt": created_at}

    speed = _float(signals.get("1319"))
    gear = _int(signals.get("1010"))
    if speed is not None or gear is not None:
        result["kinetic"] = {"speed": speed, "moving": bool((speed or 0) > 0 or gear in (1, 3)), "createdAt": created_at}

    ready = _is_on(signals.get("1258"))
    if ready is not None:
        result["ignition"] = {"type": "StartUp" if ready else "Stop", "createdAt": created_at}

    outdoor_temp = _float(status.get("outdoorTemp"))
    if outdoor_temp is not None:
        result["environment"] = {"air": {"temp": outdoor_temp, "createdAt": created_at}}

    electric: dict[str, Any] = {
        "type": "Electric",
        "level": _float(signals.get("1204")),
        "autonomy": _float(signals.get("3260")),
        "createdAt": created_at,
        "extension": {"electric": {"charging": _charging_section(signals)}},
    }
    result["energies"] = [electric]
    result["energy"] = [{"type": "Electric", "updatedAt": created_at}]
    if has_fuel(status):
        result["energies"].append({"type": "Fuel", "level": _float(signals.get("3235")), "autonomy": _float(signals.get("3259")), "createdAt": created_at})
        result["energy"].append({"type": "Fuel", "updatedAt": created_at})

    doors: dict[str, Any] = {"createdAt": created_at}
    locked = _int(signals.get("1298"))
    if locked in (0, 1):
        doors["lockedStates"] = ["Locked" if locked == 1 else "Unlocked"]
    opening = [
        {"identifier": identifier, "state": "Open" if _is_on(signals[signal]) else "Closed"}
        for identifier, signal in _DOORS.items() if signals.get(signal) is not None
    ]
    if opening:
        doors["opening"] = opening
    if len(doors) > 1:
        result["doorsState"] = doors

    climate = _is_on(signals.get("1938"))
    if climate is not None:
        result["preconditioning"] = {"airConditioning": {"status": "Enabled" if climate else "Disabled", "createdAt": created_at}}

    position = _position(signals, created_at)
    if position:
        result["lastPosition"] = position

    return result
