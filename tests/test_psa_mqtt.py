"""The PSA MQTT channel: vehicle events, command responses, sending, token refresh."""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import paho.mqtt.client as mqtt
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util

from custom_components.stellantis_vehicles.const import DOMAIN
from custom_components.stellantis_vehicles.client.psa.const import (
    MQTT_EVENT_TOPIC,
    MQTT_REQ_TOPIC,
    MQTT_RESP_TOPIC,
)
from custom_components.stellantis_vehicles.client.psa.mqtt_event import event_content, parse_mqtt_event
from custom_components.stellantis_vehicles.exceptions import CommunicationError

from .psa_fakes import CUSTOMER_ID, VIN, FakeSession, Resp, make_client


# --- parse_mqtt_event ---

def test_event_is_normalized():
    event = parse_mqtt_event({
        "vin": VIN,
        "date": "2026-11-25T10:00:00Z",
        "obj_counter": 7,
        "reason": 3,
        "sev_state": 2,
        "charging_state": {
            "available": 1, "soc_batt": 80, "autonomy_zev": 250, "cable_detected": 0,
            "hmi_state": 1, "rate": 11, "remaining_time": 95,
            "program": {"hour": 23, "minute": 30},
        },
        "precond_state": {
            "available": 1, "asap": 0, "status": 1,
            "programs": {
                "program1": {"hour": 7, "minute": 15, "on": 1, "day": [1, 1, 1, 1, 1, 0, 0]},
                "program2": {"hour": 34, "minute": 0},
            },
        },
        "doors_state": {"doors_locking_state": 7, "doors_opening_state": [0, 1, 0, 0, 1]},
        "stolen_state": 0,
    })

    assert event["vin"] == VIN
    assert event["vehicle_on"] is True  # 2 = starting
    # cable_detected is inverted: 0 means a cable is plugged in.
    assert event["charging"]["plugged"] is True
    assert event["charging"]["in_progress"] is True
    assert event["charging"]["complete"] is False
    assert event["charging"]["delayed_start_time"] == {"hour": 23, "minute": 30}
    assert event["battery"] == {"level": 80, "autonomy_km": 250}
    # Hour 34 marks a timer slot that was never set.
    assert event["preconditioning"]["programs"] == {
        "program1": {"hour": 7, "minute": 15, "enabled": True, "days": [1, 1, 1, 1, 1, 0, 0]},
        "program2": None,
    }
    # 7 is the transient mid-lock step: already counted as locked.
    assert event["doors"]["locked"] is True
    assert event["doors"]["open"] == {"driver": False, "passenger": True, "rear_left": False, "rear_right": False, "trunk": True}
    assert event["doors"]["any_open"] is True
    assert event["security"]["stolen"] is False


def test_event_with_missing_sections_keeps_its_shape():
    event = parse_mqtt_event({"vin": VIN})
    assert event["vehicle_on"] is False
    assert event["charging"]["plugged"] is None
    assert event["charging"]["delayed_start_time"] is None
    assert event["preconditioning"]["programs"] == {}
    assert event["doors"]["locked"] is False
    assert event["doors"]["open"] == {}
    assert event["doors"]["any_open"] is False


def test_event_content_drops_the_per_event_bookkeeping():
    first = parse_mqtt_event({"vin": VIN, "date": "a", "obj_counter": 1, "reason": 0, "signal_quality": 3})
    second = parse_mqtt_event({"vin": VIN, "date": "b", "obj_counter": 2, "reason": 5, "signal_quality": 4})
    assert first != second
    assert event_content(first) == event_content(second)


# --- _on_mqtt_message ---

def _message(topic, payload):
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode(), qos=0)


def _client_with_coordinator(hass):
    client, entry = make_client(hass)
    coordinator = MagicMock()
    coordinator._vehicle = {"vin": VIN}
    coordinator._commands_history = {"action-1": {"service": "/Doors", "message": {"action": "lock"}}}
    coordinator.async_refresh = AsyncMock()
    coordinator.update_command_history = AsyncMock()
    client._coordinator_dict[VIN] = coordinator
    client.send_mqtt_message = AsyncMock()
    # Record the delay of what the paho thread hands to the event loop, instead
    # of running it; the AsyncMocks above record which call it was.
    scheduled = []

    def do_async(coroutine, delay=0, *, wait):
        assert wait is False  # never block the paho network thread
        scheduled.append(delay)
        coroutine.close()

    client.do_async = do_async
    client.hass_notify = AsyncMock()
    return client, coordinator, scheduled


def _response(**fields):
    return _message(MQTT_RESP_TOPIC + CUSTOMER_ID + "/VehCharge", {"correlation_id": "action-1", **fields})


async def test_successful_command_updates_history_and_refreshes(hass):
    client, coordinator, scheduled = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(return_code="0"))
    coordinator.async_refresh.assert_called_once()
    assert 10 in scheduled  # refresh a little later, once the car has applied it
    coordinator.update_command_history.assert_called_once_with("action-1", "0")
    client.hass_notify.assert_not_called()


async def test_rejected_token_retries_the_command_once(hass):
    client, coordinator, scheduled = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(return_code="400"))
    client.send_mqtt_message.assert_called_once_with(
        "/Doors", {"action": "lock"}, {"vin": VIN}, force_token_refresh=True, action_id="action-1")
    assert coordinator._commands_history["action-1"]["retried"] is True
    coordinator.update_command_history.assert_not_called()

    # The retry fails the same way: give up and record the failure.
    client._on_mqtt_message(None, None, _response(return_code="400"))
    assert client.send_mqtt_message.call_count == 1
    coordinator.update_command_history.assert_called_once_with("action-1", "failed")
    client.hass_notify.assert_called_once_with("command_error")


async def test_service_not_in_subscription_is_reported_as_not_compatible(hass):
    client, coordinator, _ = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(
        return_code="400", reason="[authorization.denied.cvs.response.no.matching.service.key]"))
    coordinator.update_command_history.assert_called_once_with("action-1", "not_compatible")
    client.hass_notify.assert_called_once_with("command_error")


async def test_sleeping_vehicle_response_is_ignored(hass):
    client, coordinator, scheduled = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(process_code="901"))
    assert scheduled == []
    coordinator.async_refresh.assert_not_called()
    coordinator.update_command_history.assert_not_called()


async def test_response_is_routed_by_vin_when_present(hass):
    client, coordinator, _ = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(vin=VIN, correlation_id="other-action", return_code="0"))
    coordinator.update_command_history.assert_called_once_with("other-action", "0")


async def test_unknown_or_malformed_messages_do_not_raise(hass):
    client, coordinator, scheduled = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _response(correlation_id="unknown", return_code="0"))
    client._on_mqtt_message(None, None, SimpleNamespace(topic=MQTT_RESP_TOPIC + "x", payload=b"not json", qos=0))
    assert scheduled == []
    coordinator.update_command_history.assert_not_called()


async def test_vehicle_event_is_handed_to_the_coordinator(hass):
    client, coordinator, _ = _client_with_coordinator(hass)
    client._on_mqtt_message(None, None, _message(MQTT_EVENT_TOPIC + VIN, {"vin": VIN, "obj_counter": 3}))
    await hass.async_block_till_done()
    coordinator.apply_mqtt_event.assert_called_once()
    assert coordinator.apply_mqtt_event.call_args.args[0]["event_counter"] == 3


async def test_vehicle_event_is_dropped_while_unloading(hass):
    client, coordinator, _ = _client_with_coordinator(hass)
    client._shutting_down = True
    client._on_mqtt_message(None, None, _message(MQTT_EVENT_TOPIC + VIN, {"vin": VIN}))
    await hass.async_block_till_done()
    coordinator.apply_mqtt_event.assert_not_called()


# --- send_mqtt_message ---

def _connected_mqtt(rc=mqtt.MQTT_ERR_SUCCESS):
    fake = MagicMock()
    fake.is_connected.return_value = True
    fake.publish.return_value = SimpleNamespace(rc=rc)
    return fake


def _with_mqtt_tokens(hass, session=None, **config):
    mqtt_config = {
        "access_token": "mqtt-access-0",
        "refresh_token": "mqtt-refresh-0",
        "expires_in": (dt_util.utcnow() + timedelta(hours=1)).isoformat(),
        "refresh_token_expires_at": (dt_util.utcnow() + timedelta(days=2)).isoformat(),
    }
    mqtt_config.update(config)
    return make_client(hass, session, mqtt=mqtt_config)


async def test_command_is_published_to_the_customer_topic(hass):
    client, _ = _with_mqtt_tokens(hass)
    client._mqtt = _connected_mqtt()
    action_id = await client.send_mqtt_message("/Doors", {"action": "lock"}, {"vin": VIN})

    topic, payload = client._mqtt.publish.call_args.args
    assert topic == MQTT_REQ_TOPIC + CUSTOMER_ID + "/Doors"
    payload = json.loads(payload)
    assert payload["vin"] == VIN
    assert payload["correlation_id"] == action_id
    assert payload["access_token"] == "mqtt-access-0"
    assert payload["req_parameters"] == {"action": "lock"}


async def test_failed_publish_returns_no_action_id(hass):
    client, _ = _with_mqtt_tokens(hass)
    client._mqtt = _connected_mqtt(rc=mqtt.MQTT_ERR_NO_CONN)
    assert await client.send_mqtt_message("/Doors", {"action": "lock"}, {"vin": VIN}) is None


async def test_command_without_a_connection_raises(hass):
    client, _ = _with_mqtt_tokens(hass)
    client.connect_mqtt = AsyncMock(return_value=False)
    with pytest.raises(CommunicationError):
        await client.send_mqtt_message("/Doors", {"action": "lock"}, {"vin": VIN})
    client.connect_mqtt.assert_awaited_once()


async def test_command_auth_failure_disables_remote_commands(hass):
    client, entry = _with_mqtt_tokens(hass)
    client.scheduled_mqtt_token_refresh = AsyncMock(side_effect=ConfigEntryAuthFailed("otp"))
    with pytest.raises(ConfigEntryAuthFailed):
        await client.send_mqtt_message("/Doors", {"action": "lock"}, {"vin": VIN})
    assert client.remote_commands is False
    assert entry.data["remote_commands"] is False


# --- MQTT token refresh ---

async def test_expired_refresh_token_falls_back_to_refreshing_the_access_token(hass):
    session = FakeSession(
        Resp(400, {"error": "invalid_grant", "error_description": "otp rejected"}),
        Resp(200, {"access_token": "mqtt-access-1", "expires_in": 600}),
    )
    client, entry = _with_mqtt_tokens(hass, session, refresh_token_expires_at=(dt_util.utcnow() - timedelta(minutes=1)).isoformat())
    client.get_otp_code = AsyncMock(return_value="123456")
    client._mqtt = MagicMock()

    await client.refresh_mqtt_token_request()

    assert session.requests[0]["json"] == {"grant_type": "password", "password": "123456"}
    assert session.requests[1]["json"] == {"grant_type": "refresh_token", "refresh_token": "mqtt-refresh-0"}
    assert entry.data["mqtt"]["access_token"] == "mqtt-access-1"
    # No new refresh token was issued, so the old one is kept.
    assert entry.data["mqtt"]["refresh_token"] == "mqtt-refresh-0"
    # paho reconnects with the credentials it was given: they must be the new ones.
    client._mqtt.username_pw_set.assert_called_with("IMA_OAUTH_ACCESS_TOKEN", "mqtt-access-1")


async def test_new_refresh_token_is_stored_with_its_expiry(hass):
    session = FakeSession(Resp(200, {"access_token": "mqtt-access-1", "refresh_token": "mqtt-refresh-1", "expires_in": 600}))
    client, entry = _with_mqtt_tokens(hass, session, refresh_token_expires_at=(dt_util.utcnow() - timedelta(minutes=1)).isoformat())
    client.get_otp_code = AsyncMock(return_value="123456")

    await client.refresh_mqtt_token_request()
    stored = entry.data["mqtt"]
    assert stored["refresh_token"] == "mqtt-refresh-1"
    assert dt_util.parse_datetime(stored["refresh_token_expires_at"]) > dt_util.utcnow() + timedelta(days=2)


async def test_token_response_without_access_token_changes_nothing(hass):
    session = FakeSession(Resp(200, {"error": "nope"}))
    client, entry = _with_mqtt_tokens(hass, session)
    await client.refresh_mqtt_token_request()
    assert entry.data["mqtt"]["access_token"] == "mqtt-access-0"


async def test_scheduled_refresh_auth_failure_disables_commands_and_starts_reauth(hass):
    client, entry = _with_mqtt_tokens(hass, expires_in=dt_util.utcnow().isoformat())
    client.refresh_mqtt_token_request = AsyncMock(side_effect=ConfigEntryAuthFailed("OTP file not found"))

    await client.scheduled_mqtt_token_refresh()
    await hass.async_block_till_done()

    assert entry.data["remote_commands"] is False
    assert client._mqtt_token_scheduled is None
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_scheduled_refresh_network_failure_retries_with_backoff(hass):
    client, _ = _with_mqtt_tokens(hass, expires_in=dt_util.utcnow().isoformat())
    client.refresh_mqtt_token_request = AsyncMock(side_effect=CommunicationError("down"))

    await client.scheduled_mqtt_token_refresh()
    assert client._mqtt_token_retry == 1
    assert client._mqtt_token_scheduled is not None
    client.reset_scheduled_tokens()


async def test_scheduled_refresh_is_skipped_without_remote_commands(hass):
    client, _ = make_client(hass, remote_commands=False)
    client.refresh_mqtt_token_request = AsyncMock()
    await client.scheduled_mqtt_token_refresh(force=True)
    client.refresh_mqtt_token_request.assert_not_awaited()
    assert client._mqtt_token_scheduled is None
