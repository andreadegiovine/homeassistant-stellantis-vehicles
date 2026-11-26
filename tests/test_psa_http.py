"""The PSA REST client: HTTP error mapping and the vehicle data endpoints."""
import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.stellantis_vehicles.exceptions import CommunicationError

from .psa_fakes import VIN, FakeSession, Resp, make_client

URL = "https://api.example/v4/user/vehicles"


# --- make_http_request: how each Stellantis answer is turned into a result ---

@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"message": "Not Found", "code": 40400}),     # no status for this vehicle yet
        (500, {"message": "CVS error/user-vins", "code": 50038}),  # transient VIN-list failure
    ],
)
async def test_known_transient_errors_return_an_empty_result(hass, status, body):
    client, _ = make_client(hass, FakeSession(Resp(status, body)))
    assert await client.make_http_request(URL) == {}


@pytest.mark.parametrize(
    ("status", "body", "raised", "message"),
    [
        (500, {"message": "Connection module", "code": 50000}, CommunicationError, "Connection module - 50000"),
        (400, {"error": "invalid_grant", "error_description": "grant is invalid"}, ConfigEntryAuthFailed, "invalid_grant - grant is invalid"),
        (503, {"httpMessage": "Service Unavailable", "moreInformation": "try later"}, CommunicationError, "Service Unavailable - try later"),
        (502, None, CommunicationError, "HTTP 502"),
        (418, {}, CommunicationError, "Unexpected HTTP status 418"),
    ],
)
async def test_error_responses_raise_with_the_server_message(hass, status, body, raised, message):
    session = FakeSession(Resp(status, body))
    client, _ = make_client(hass, session)
    with pytest.raises(raised, match=message):
        await client.make_http_request(URL)
    # A failed request drops the session so the next one starts clean.
    assert session.closed


@pytest.mark.parametrize("error", [asyncio.TimeoutError(), aiohttp.ClientConnectionError("reset")])
async def test_network_failures_become_communication_errors(hass, error):
    session = FakeSession(error)
    client, _ = make_client(hass, session)
    with pytest.raises(CommunicationError):
        await client.make_http_request(URL)
    assert session.closed


async def test_delete_ignores_the_response_body(hass):
    client, _ = make_client(hass, FakeSession(Resp(204, {"ignored": True})))
    assert await client.make_http_request(URL, "DELETE") == {}


async def test_401_without_a_working_refresh_is_a_communication_error(hass):
    client, _ = make_client(hass, FakeSession(Resp(401, {})))
    client.refresh_oauth_token_request = AsyncMock(side_effect=CommunicationError("token endpoint down"))
    with pytest.raises(CommunicationError, match="HTTP 401"):
        await client.make_http_request(URL, headers={"Authorization": "Bearer access-0"})
    client.refresh_oauth_token_request.assert_awaited_once_with("access-0")


# --- get_user_vehicles ---

def _vehicle(vin=VIN, vehicle_id="vid-1", pictures=("https://pictures.example/car.png",)):
    return {
        "id": vehicle_id,
        "vin": vin,
        "motorization": "Electric",
        "brand": "Peugeot",
        "pictures": list(pictures),
        "_links": {"maintenance": {"href": "https://api.example/maintenance"}},
    }


async def test_vehicles_are_parsed_and_cached(hass):
    session = FakeSession(Resp(200, {"_embedded": {"vehicles": [_vehicle()]}}))
    client, _ = make_client(hass, session)
    client.resize_and_save_picture = AsyncMock(return_value="/local/car.png")

    vehicles = await client.get_user_vehicles()
    assert vehicles == [{
        "vehicle_id": "vid-1",
        "vin": VIN,
        "type": "Electric",
        "brand": "Peugeot",
        "links": {"maintenance": {"href": "https://api.example/maintenance"}},
        "picture": "/local/car.png",
    }]
    # The request carries the account's client_id, not a raw placeholder.
    assert "{#" not in session.requests[0]["url"]
    assert "client_id=" in session.requests[0]["url"]

    # Cached: no second request unless forced.
    assert await client.get_user_vehicles() is vehicles
    assert len(session.requests) == 1


async def test_force_refetches_the_vehicle_list(hass):
    session = FakeSession(
        Resp(200, {"_embedded": {"vehicles": [_vehicle()]}}),
        Resp(200, {"_embedded": {"vehicles": []}}),
    )
    client, _ = make_client(hass, session)
    client.resize_and_save_picture = AsyncMock(return_value=None)
    assert len(await client.get_user_vehicles()) == 1
    assert await client.get_user_vehicles(force=True) == []


async def test_vehicle_without_a_usable_picture_is_still_listed(hass):
    session = FakeSession(Resp(200, {"_embedded": {"vehicles": [_vehicle(pictures=())]}}))
    client, _ = make_client(hass, session)
    vehicles = await client.get_user_vehicles()
    assert [v["vin"] for v in vehicles] == [VIN]
    assert "picture" not in vehicles[0]


@pytest.mark.parametrize("body", [{}, None, ["not", "a", "dict"]])
async def test_empty_or_invalid_vehicle_list_is_a_communication_error(hass, body):
    client, _ = make_client(hass, FakeSession(Resp(200, body)))
    with pytest.raises(CommunicationError):
        await client.get_user_vehicles()


# --- trips and maintenance ---

def _trips(self_token, last_token=None):
    links = {"self": {"href": f"https://api.example/trips?pageToken={self_token}"}}
    if last_token is not None:
        links["last"] = {"href": f"https://api.example/trips?pageToken={last_token}"}
    return {"_links": links, "_embedded": {"trips": [{"id": self_token}]}}


async def test_last_trip_follows_the_pagination_to_the_last_page(hass):
    session = FakeSession(Resp(200, _trips("p1", "p3")), Resp(200, _trips("p3", "p3")))
    client, _ = make_client(hass, session)
    vehicle = {"vin": VIN, "vehicle_id": "vid-1"}

    result = await client.get_vehicle_last_trip(vehicle)
    assert result["_embedded"]["trips"] == [{"id": "p3"}]
    assert "vid-1/trips" in session.requests[0]["url"]
    assert session.requests[1]["url"].endswith("&pageToken=p3")


async def test_last_trip_stops_when_the_last_page_points_to_itself(hass):
    # A server that keeps answering with the same "last" token must not loop.
    session = FakeSession(Resp(200, _trips("p1", "p2")), Resp(200, _trips("p1", "p2")))
    client, _ = make_client(hass, session)
    await client.get_vehicle_last_trip({"vin": VIN, "vehicle_id": "vid-1"})
    assert len(session.requests) == 2


async def test_trips_since_a_date_and_page(hass):
    from datetime import datetime, timezone

    session = FakeSession(Resp(200, {"_embedded": {"trips": []}}))
    client, _ = make_client(hass, session)
    since = datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)
    await client.get_vehicle_trips({"vin": VIN, "vehicle_id": "vid-1"}, since=since, page_token="abc")
    url = session.requests[0]["url"]
    assert "&timestamps=2026-11-01T08:30:00+00:00/" in url
    assert url.endswith("&pageToken=abc")


async def test_maintenance_without_a_link_makes_no_request(hass):
    session = FakeSession()
    client, _ = make_client(hass, session)
    assert await client.get_vehicle_maintenance({"vin": VIN, "links": {}}) == {}
    assert await client.get_vehicle_maintenance(None) == {}
    assert session.requests == []


async def test_maintenance_uses_the_vehicle_link(hass):
    session = FakeSession(Resp(200, {"mileageBeforeMaintenance": 1200}))
    client, _ = make_client(hass, session)
    vehicle = {"vin": VIN, "links": {"maintenance": {"href": "https://api.example/maintenance"}}}
    assert await client.get_vehicle_maintenance(vehicle) == {"mileageBeforeMaintenance": 1200}
    assert session.requests[0]["url"].startswith("https://api.example/maintenance?client_id=")


async def test_vehicle_status_skips_mqtt_when_remote_commands_are_off(hass):
    session = FakeSession(Resp(200, {"updatedAt": "2026-11-25T10:00:00Z"}))
    client, _ = make_client(hass, session, remote_commands=False)
    client.connect_mqtt = AsyncMock()
    status = await client.get_vehicle_status({"vin": VIN, "vehicle_id": "vid-1"})
    assert status == {"updatedAt": "2026-11-25T10:00:00Z"}
    client.connect_mqtt.assert_not_awaited()
    assert "vid-1/status" in session.requests[0]["url"]


# --- ABRP ---

async def test_abrp_failures_never_raise(hass):
    client, _ = make_client(hass, FakeSession(Resp(500, {"message": "down", "code": 1})))
    await client.send_abrp_data({"token": "user-token", "tlm": "{}"})


async def test_abrp_sends_the_api_key(hass):
    session = FakeSession(Resp(200, {"status": "ok"}))
    client, _ = make_client(hass, session)
    await client.send_abrp_data({"token": "user-token"})
    assert session.requests[0]["params"]["api_key"]
    assert session.requests[0]["params"]["token"] == "user-token"
