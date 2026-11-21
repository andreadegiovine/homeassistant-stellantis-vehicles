"""command_error notifications replace each other and are dismissed after an hour."""
from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.stellantis_vehicles.client_base import BaseVehiclesClient


async def test_command_error_uses_one_id_and_is_dismissed_an_hour_after_the_last_error(hass):
    client = BaseVehiclesClient(hass)
    with patch("custom_components.stellantis_vehicles.client_base.persistent_notification") as notification:
        await client.hass_notify("command_error")
        await client.hass_notify("command_error")

        ids = [c.kwargs["notification_id"] for c in notification.async_create.call_args_list]
        assert ids == ["stellantis_vehicles_command_error"] * 2
        notification.async_dismiss.assert_not_called()

        # The first timer was cancelled, so only one hour after the *second* error it fires.
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3599))
        await hass.async_block_till_done()
        notification.async_dismiss.assert_not_called()

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3601))
        await hass.async_block_till_done()
        notification.async_dismiss.assert_called_once_with(hass, "stellantis_vehicles_command_error")


async def test_other_notifications_keep_random_ids(hass):
    client = BaseVehiclesClient(hass)
    with patch("custom_components.stellantis_vehicles.client_base.persistent_notification") as notification:
        await client.hass_notify("otp_error")
        await client.hass_notify("otp_error")
        ids = [c.kwargs["notification_id"] for c in notification.async_create.call_args_list]
        assert ids[0] != ids[1]
        assert not ids[0].startswith("stellantis_vehicles_command_error")
