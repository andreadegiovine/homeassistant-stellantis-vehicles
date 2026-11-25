"""py-uconnect vehicles translated into the layout the shared entities read."""
from custom_components.stellantis_vehicles.client.uconnect.status import normalize_status, vehicle_type

from .uconnect_fakes import ev_vehicle, ice_vehicle


def test_electric_vehicle_charging():
    vehicle = ev_vehicle()
    assert vehicle_type(vehicle) == "Electric"
    data = normalize_status(vehicle)
    assert data["updatedAt"] == "2026-11-25T10:00:00+00:00"
    assert data["odometer"]["mileage"] == 12000
    assert data["ignition"]["type"] == "Stop"
    electric = data["energies"][0]
    assert (electric["type"], electric["level"], electric["autonomy"]) == ("Electric", 80, 250)
    assert electric["extension"]["electric"]["charging"] == {"plugged": True, "status": "InProgress", "remainingTime": "PT1H35M", "chargingMode": "Slow"}
    assert len(data["energies"]) == 1
    assert data["maintenance"] == {"mileageBeforeMaintenance": 8000, "daysBeforeMaintenance": 120, "updatedAt": "2026-11-25T10:00:00+00:00"}
    assert data["doorsState"]["lockedStates"] == ["Locked"]
    assert data["preconditioning"]["airConditioning"]["status"] == "Disabled"
    assert data["privacy"]["state"] == "None"
    assert data["lastPosition"]["geometry"]["coordinates"] == [9.19, 45.46]


def test_charging_states():
    def charging(**changes):
        return normalize_status(ev_vehicle(**changes))["energies"][0]["extension"]["electric"]["charging"]
    assert charging(charging=False) == {"plugged": True, "status": "Stopped"}
    assert charging(charging=False, plugged_in=False) == {"plugged": False, "status": "Disconnected"}
    # Level 3 is DC fast charging; a remaining time over a day is not shown.
    assert charging(charging_level=3, time_to_fully_charge_l3=40)["chargingMode"] == "Quick"
    assert "remainingTime" not in charging(time_to_fully_charge_l2=2000)


def test_thermic_vehicle_in_miles():
    vehicle = ice_vehicle()
    assert vehicle_type(vehicle) == "Thermic"
    data = normalize_status(vehicle)
    assert data["odometer"]["mileage"] == 16093.4
    assert data["energies"] == [{"type": "Fuel", "level": 55, "autonomy": 482.8, "createdAt": "2026-11-25T10:00:00+00:00"}]
    # One door unlocked is the vehicle unlocked; unknown doors are ignored.
    assert data["doorsState"]["lockedStates"] == ["Unlocked"]
    assert "lastPosition" not in data and "preconditioning" not in data


def test_plug_in_hybrid():
    vehicle = ice_vehicle(fuel_type="G", state_of_charge=40.0, plugged_in=False, charging=False, range_total=500.0, range_gas=450.0, range_gas_unit="km", distance_to_empty_unit="km")
    assert vehicle_type(vehicle) == "Hybrid"
    electric, fuel = normalize_status(vehicle)["energies"]
    assert (electric["level"], electric["autonomy"]) == (40, 50)
    assert (fuel["level"], fuel["autonomy"]) == (55, 450)


def test_privacy_and_running():
    data = normalize_status(ev_vehicle(privacy_mode="ACTIVE", ev_running=True, hvac_on=True))
    assert data["privacy"]["state"] == "Full"
    assert data["ignition"]["type"] == "StartUp"
    assert data["preconditioning"]["airConditioning"]["status"] == "Enabled"


def test_vehicle_without_data():
    vehicle = ev_vehicle(timestamp_info=None, timestamp_status=None, odometer=None, location=None)
    assert normalize_status(vehicle) == {}
