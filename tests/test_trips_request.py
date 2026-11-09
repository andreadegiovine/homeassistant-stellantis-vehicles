"""Dates sent in the trips URL."""
from datetime import datetime
from unittest.mock import AsyncMock

from custom_components.stellantis_vehicles.stellantis import StellantisVehicles


async def test_last_trip_timestamps_has_no_plus(hass):
    await hass.config.async_set_time_zone("Europe/Paris")
    sv = StellantisVehicles(hass)
    sv.apply_query_params = lambda url, params, vehicle=None: "https://api/trips?client_id=x"
    sv.apply_dict_params = lambda d: dict(d)
    sv.make_http_request = AsyncMock(return_value={})
    await sv.get_vehicle_last_trip({"vin": "VIN1"})
    url = sv.make_http_request.call_args.args[0]
    timestamps = url.split("timestamps=")[1].split("&")[0]
    # An isoformat "+01:00" offset is sent unencoded and decoded as a space.
    assert "+" not in timestamps
    datetime.strptime(timestamps, "%Y-%m-%dT%H:%M:%SZ/")
