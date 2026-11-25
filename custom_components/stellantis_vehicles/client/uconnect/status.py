"""Translate a py-uconnect Vehicle into the status layout the shared entities
read (the one of the PSA API), so the same sensors serve every cloud."""
from datetime import datetime
from typing import Any

from py_uconnect import Vehicle

from ...const import VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID, VEHICLE_TYPE_THERMIC
from .const import FUEL_TYPE_ELECTRIC, KM_PER_MILE


def vehicle_type(vehicle: Vehicle) -> str:
    """Electric, hybrid (a battery and a tank) or thermic."""
    if vehicle.fuel_type == FUEL_TYPE_ELECTRIC:
        return VEHICLE_TYPE_ELECTRIC
    if vehicle.state_of_charge is not None or vehicle.plugged_in is not None:
        return VEHICLE_TYPE_HYBRID
    return VEHICLE_TYPE_THERMIC


def _km(value: float | None, unit: str | None) -> float | None:
    """A distance in km: vehicles sold in miles countries report miles."""
    if value is None:
        return None
    if unit and unit.strip().lower().startswith("mi"):
        return round(value * KM_PER_MILE, 1)
    return value


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _remaining_time(vehicle: Vehicle) -> str | None:
    """Time to a full charge at the level the vehicle charges at, as the duration the shared sensor parses."""
    minutes = {
        1: vehicle.time_to_fully_charge_l1,
        2: vehicle.time_to_fully_charge_l2,
        3: vehicle.time_to_fully_charge_l3,
    }.get(vehicle.charging_level or 0)
    # The shared sensor parses hours as a time of day.
    if not minutes or minutes >= 24 * 60:
        return None
    return f"PT{minutes // 60}H{minutes % 60}M"


def _charging(vehicle: Vehicle) -> dict[str, Any]:
    section: dict[str, Any] = {"plugged": vehicle.plugged_in}
    if vehicle.charging:
        section["status"] = "InProgress"
        if remaining := _remaining_time(vehicle):
            section["remainingTime"] = remaining
        if vehicle.charging_level:
            # Level 3 is DC fast charging.
            section["chargingMode"] = "Quick" if vehicle.charging_level == 3 else "Slow"
    elif vehicle.plugged_in:
        section["status"] = "Stopped"
    elif vehicle.plugged_in is False:
        section["status"] = "Disconnected"
    return section


def normalize_status(vehicle: Vehicle) -> dict[str, Any]:
    """Build the shared status layout; {} when the vehicle reported nothing yet."""
    moments = [m for m in (vehicle.timestamp_info, vehicle.timestamp_status) if m]
    if not moments and vehicle.odometer is None and vehicle.location is None:
        return {}
    info_at = _iso(vehicle.timestamp_info)
    status_at = _iso(vehicle.timestamp_status) or info_at
    result: dict[str, Any] = {"updatedAt": _iso(max(moments)) if moments else None}

    mileage = _km(vehicle.odometer, vehicle.odometer_unit)
    if mileage is not None:
        result["odometer"] = {"mileage": mileage, "createdAt": info_at}

    if vehicle.ignition_on is not None or vehicle.ev_running is not None:
        running = bool(vehicle.ignition_on or vehicle.ev_running)
        result["ignition"] = {"type": "StartUp" if running else "Stop", "createdAt": status_at}

    kind = vehicle_type(vehicle)
    energies, energy = [], []
    if kind in (VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID):
        if kind == VEHICLE_TYPE_ELECTRIC:
            autonomy = vehicle.distance_to_empty
        elif vehicle.range_total is not None and vehicle.range_gas is not None:
            autonomy = max(vehicle.range_total - vehicle.range_gas, 0)
        else:
            autonomy = None
        energies.append({
            "type": "Electric",
            "level": vehicle.state_of_charge,
            "autonomy": _km(autonomy, vehicle.distance_to_empty_unit),
            "createdAt": info_at,
            "extension": {"electric": {"charging": _charging(vehicle)}},
        })
        energy.append({"type": "Electric", "updatedAt": info_at})
    if kind in (VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID):
        fuel_range = vehicle.range_gas if kind == VEHICLE_TYPE_HYBRID else vehicle.distance_to_empty
        energies.append({
            "type": "Fuel",
            "level": vehicle.fuel_amount,
            "autonomy": _km(fuel_range, vehicle.range_gas_unit or vehicle.distance_to_empty_unit),
            "createdAt": info_at,
        })
        energy.append({"type": "Fuel", "updatedAt": info_at})
    result["energies"] = energies
    result["energy"] = energy

    if vehicle.distance_to_service is not None or vehicle.days_to_service is not None:
        result["maintenance"] = {
            "mileageBeforeMaintenance": _km(vehicle.distance_to_service, vehicle.distance_to_service_unit),
            "daysBeforeMaintenance": vehicle.days_to_service,
            "updatedAt": info_at,
        }

    doors = [vehicle.door_driver_locked, vehicle.door_passenger_locked, vehicle.door_rear_left_locked, vehicle.door_rear_right_locked]
    known = [locked for locked in doors if locked is not None]
    if known:
        result["doorsState"] = {"lockedStates": ["Locked" if all(known) else "Unlocked"], "createdAt": status_at}

    if vehicle.hvac_on is not None:
        result["preconditioning"] = {"airConditioning": {"status": "Enabled" if vehicle.hvac_on else "Disabled", "createdAt": status_at}}

    if vehicle.privacy_mode:
        result["privacy"] = {"state": "Full" if vehicle.privacy_mode.upper() == "ACTIVE" else "None", "createdAt": info_at}

    location = vehicle.location
    if location and location.latitude is not None and location.longitude is not None:
        coordinates = [location.longitude, location.latitude]
        if location.altitude is not None:
            coordinates.append(location.altitude)
        result["lastPosition"] = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coordinates},
            "properties": {"createdAt": _iso(location.updated)},
        }

    return result
