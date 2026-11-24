"""Leapmotor statuses translated into the layout the shared entities read."""
from copy import deepcopy

from custom_components.stellantis_vehicles.client.leapmotor.status import has_fuel, normalize_status

from .leapmotor_fakes import STATUS


def _signals(**changes):
    status = deepcopy(STATUS)
    status["signal"].update(changes)
    return status


def test_charging_parked_vehicle():
    data = normalize_status(STATUS)
    assert data["updatedAt"] == "2026-11-14T10:00:00+00:00"
    assert data["odometer"]["mileage"] == 12345
    assert data["kinetic"] == {"speed": 0, "moving": False, "createdAt": data["updatedAt"]}
    assert data["ignition"]["type"] == "Stop"
    assert data["environment"]["air"]["temp"] == 11
    electric = data["energies"][0]
    assert (electric["type"], electric["level"], electric["autonomy"]) == ("Electric", 76, 301)
    assert electric["extension"]["electric"]["charging"] == {"plugged": True, "status": "InProgress", "remainingTime": "PT1H35M", "chargingMode": "Slow"}
    assert data["doorsState"]["lockedStates"] == ["Locked"]
    assert {"identifier": "Trunk", "state": "Open"} in data["doorsState"]["opening"]
    assert {"identifier": "Driver", "state": "Closed"} in data["doorsState"]["opening"]
    assert data["preconditioning"]["airConditioning"]["status"] == "Enabled"
    assert data["lastPosition"]["geometry"]["coordinates"] == [9.19, 45.46]
    assert len(data["energies"]) == 1 and not has_fuel(STATUS)


def test_unplugged_and_driving():
    data = normalize_status(_signals(**{"1149": 0, "1178": 30, "1200": None, "1319": 52, "1010": 3, "1258": 1, "1298": 0}))
    assert data["energies"][0]["extension"]["electric"]["charging"] == {"plugged": False, "status": "Disconnected"}
    assert data["kinetic"]["moving"] is True
    assert data["ignition"]["type"] == "StartUp"
    assert data["doorsState"]["lockedStates"] == ["Unlocked"]


def test_plugged_but_idle_is_not_charging():
    charging = normalize_status(_signals(**{"1178": 0.2, "1200": 0}))["energies"][0]["extension"]["electric"]["charging"]
    assert charging == {"plugged": True, "status": "Stopped"}
    charging = normalize_status(_signals(**{"1178": 0.2, "1200": 0, "3736": 1}))["energies"][0]["extension"]["electric"]["charging"]
    assert charging["status"] == "Finished"


def test_range_extender_reports_fuel():
    status = _signals(**{"3235": 40, "3259": 610})
    assert has_fuel(status)
    assert normalize_status(status)["energies"][1] == {"type": "Fuel", "level": 40, "autonomy": 610, "createdAt": "2026-11-14T10:00:00+00:00"}


def test_named_fields_of_older_models():
    data = normalize_status({"soc": 55, "expectedMileage": 140, "totalMileage": 900, "chargeState": 0, "driverDoorLockStatus": True, "collectTime": 1794650400})
    assert data["energies"][0]["level"] == 55
    assert data["energies"][0]["extension"]["electric"]["charging"]["plugged"] is False
    assert data["doorsState"]["lockedStates"] == ["Locked"]
    assert data["updatedAt"] == "2026-11-14T10:00:00+00:00"


def test_available_energy_is_the_battery_residual():
    status = {**STATUS, "dumpEnergy": 31250}
    assert normalize_status(status)["energies"][0]["extension"]["electric"]["battery"] == {"load": {"residual": 31250}}
    assert "battery" not in normalize_status(STATUS)["energies"][0]["extension"]["electric"]


def test_status_without_signals_is_no_data():
    assert normalize_status({}) == {}
