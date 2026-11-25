"""A fake py-uconnect client for the tests: the integration only goes through py_uconnect.Client."""
from datetime import UTC, datetime

from py_uconnect import AuthenticationError, CommandTimeoutError, Location, PinAuthenticationError, Vehicle

EMAIL, PASSWORD, PIN = "user@example.com", "secret", "1234"
VIN_EV = "ZFAEFAC39MX000001"
VIN_ICE = "1C4PJMDX0MD000002"
UID = "gigya-uid-1"
AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


def ev_vehicle(**changes) -> Vehicle:
    vehicle = Vehicle(
        vin=VIN_EV, make="FIAT", model="500e", fuel_type="E", region="EMEA", privacy_mode="INACTIVE",
        odometer=12000.0, odometer_unit="km", state_of_charge=80.0, distance_to_empty=250.0, distance_to_empty_unit="km",
        plugged_in=True, charging=True, charging_level=2, time_to_fully_charge_l2=95,
        days_to_service=120, distance_to_service=8000.0, distance_to_service_unit="km",
        ignition_on=False, hvac_on=False,
        door_driver_locked=True, door_passenger_locked=True, door_rear_left_locked=True, door_rear_right_locked=True,
        location=Location(latitude=45.46, longitude=9.19, updated=AT),
        enabled_services=["RDL", "RDU", "HBLF", "ROLIGHTS", "ROPRECOND", "ROPRECOND_OFF", "CNOW2", "DEEPREFRESH2", "VF"],
        timestamp_info=AT, timestamp_status=AT,
    )
    vehicle.supported_commands = ["RDL", "RDU", "HBLF", "ROLIGHTS", "ROPRECOND", "ROPRECOND_OFF", "VF", "DEEPREFRESH", "CNOW"]
    for key, value in changes.items():
        setattr(vehicle, key, value)
    return vehicle


def ice_vehicle(**changes) -> Vehicle:
    vehicle = Vehicle(
        vin=VIN_ICE, make="JEEP", model="Compass", fuel_type="G", region="NAFTA",
        odometer=10000.0, odometer_unit="mi", distance_to_empty=300.0, distance_to_empty_unit="mi", fuel_amount=55.0,
        ignition_on=False, door_driver_locked=False, door_passenger_locked=True,
        enabled_services=["RDL", "RDU", "ROHVACON", "ROHVACOFF"],
        timestamp_info=AT, timestamp_status=AT,
    )
    vehicle.supported_commands = ["RDL", "RDU", "ROHVACON", "ROHVACOFF"]
    for key, value in changes.items():
        setattr(vehicle, key, value)
    return vehicle


class FakeApi:
    def __init__(self, cloud):
        self._cloud = cloud
        self.uid = None
        self.pin = cloud.last_pin

    async def login(self):
        self._cloud.check_credentials()
        self.uid = UID


class FakeCloud:
    """Plays the Uconnect cloud; ``client_class`` is what replaces py_uconnect.Client."""

    def __init__(self):
        self.vehicles = {VIN_EV: ev_vehicle(), VIN_ICE: ice_vehicle()}
        self.password = PASSWORD
        self.pin = PIN
        self.refreshes = 0
        self.commands = []
        self.outcome = True          # True, False or "timeout"
        self.last_pin = None
        self.clients = []
        self.down = False

    def check_credentials(self):
        if self.down:
            from py_uconnect import UconnectConnectionError
            raise UconnectConnectionError("down")
        if self._credentials != (EMAIL, self.password):
            raise AuthenticationError("accounts.login failed: Invalid LoginID (403042)")

    @property
    def client_class(self):
        cloud = self

        class FakeClient:
            def __init__(self, email, password, pin, brand, *, session=None, timeout=30):
                cloud._credentials = (email, password)
                cloud.last_pin = pin
                cloud.brand = brand
                cloud.clients.append(self)
                self.api = FakeApi(cloud)
                self.pin = pin
                self.vehicles = {}

            async def refresh(self):
                cloud.check_credentials()
                self.api.uid = UID
                cloud.refreshes += 1
                self.vehicles = dict(cloud.vehicles)
                return self.vehicles

            async def command(self, vin, cmd, params=None):
                if self.pin != cloud.pin:
                    raise PinAuthenticationError("PIN authentication failed")
                cloud.commands.append((vin, cmd.name, params))
                return f"cid-{len(cloud.commands)}"

            async def wait_for_operation(self, vin, correlation_id, timeout=60, interval=2):
                if cloud.outcome == "timeout":
                    raise CommandTimeoutError(f"no result for operation {correlation_id}")
                return cloud.outcome

            async def close(self):
                pass

        return FakeClient
