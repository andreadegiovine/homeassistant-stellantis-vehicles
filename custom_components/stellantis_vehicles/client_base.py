"""What every vehicle cloud client shares: configuration, config-entry storage,
coordinators, notifications and task scheduling. Cloud-specific clients live
under ``client/`` and build on this."""
import asyncio
import logging
import os
from copy import deepcopy
from io import BytesIO
from typing import Any
from uuid import uuid4

import aiohttp
from PIL import Image, ImageOps

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import translation
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .base import StellantisVehicleCoordinator
from .utils import SENSITIVE_DATA_FILTER, replace_string_placeholders

from .const import (
    DOMAIN,
    FIELD_REMOTE_COMMANDS,
    FIELD_NOTIFICATIONS,
    ABRP_URL,
    ABRP_API_KEY,
    TRANSLATION_PLACEHOLDERS
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class BaseVehiclesClient:
    # Coordinator built for each vehicle of this client.
    coordinator_class = StellantisVehicleCoordinator

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._config = {}
        self._session = None
        self._entry = None
        self._coordinator_dict = {}
        self._vehicles = []
        self._shutting_down = False
        self._pending_tasks: set[asyncio.Task] = set()

        # Shared instance, already attached to the module loggers at import time.
        self.logger_filter = SENSITIVE_DATA_FILTER

    def start_session(self):
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def close_session(self):
        if not self._session or self._session.closed:
            return
        await self._session.close()
        self._session = None

    def save_config(self, data:dict[str, Any]) -> None:
        for key in data:
            # A copy: a value shared with entry.data that is changed in place is not seen by async_update_entry, which then does not save.
            self._config[key] = deepcopy(data[key])
            self._on_config_key_saved(key, data[key])
        # save_config() is the single choke point through which token
        # rotations and per-vehicle settings reach self._config. Refresh
        # the log filter's snapshot for this entry here, so it always masks the
        # current tokens - the token-refresh code no longer has to register each
        # rotated value by hand, which used to grow the filter without bound
        # (issue #414). No-op until set_entry() has run (config-flow phase).
        if self._entry is not None:
            self.logger_filter.set_entry_values(self._entry.entry_id, self._config)

    def _on_config_key_saved(self, key:str, value:Any) -> None:
        """ Hook: a configuration key was just saved. """

    def get_config(self, key):
        if key in self._config:
            return self._config[key]
        return None

    @property
    def remote_commands(self):
        return self.get_config(FIELD_REMOTE_COMMANDS) in [None, True]

    def disable_remote_commands(self):
        self.save_config({FIELD_REMOTE_COMMANDS: False})
        self.update_stored_config(FIELD_REMOTE_COMMANDS, False)

    def set_entry(self, entry:ConfigEntry) -> None:
        self._entry = entry
        self.logger_filter.set_entry_values(entry.entry_id, self._config)

    def update_stored_config(self, config, value):
        data = self._entry.data
        new_data = {}
        for key in data:
            new_data[key] = deepcopy(data[key])
        if config not in new_data:
            new_data[config] = None
        new_data[config] = value
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)

    def get_stored_config(self, config):
        if config in self._entry.data:
            return self._entry.data[config]
        return None

    def get_vehicles_stored_config(self):
        """Return the per-vehicle stored config sub-node, keyed by VIN."""
        return self.get_stored_config("vehicles") or {}

    def update_vehicle_stored_config(self, vin, key, value):
        vehicles = deepcopy(self.get_vehicles_stored_config())
        vehicles.setdefault(vin, {})[key] = value
        self.update_stored_config("vehicles", vehicles)
        # Through save_config() so the log filter's snapshot picks up the VIN.
        self.save_config({"vehicles": deepcopy(vehicles)})

    def get_vehicle_stored_config(self, vin, key):
        vehicle = self.get_vehicles_stored_config().get(vin)
        if vehicle and key in vehicle:
            return vehicle[key]
        return None

    def prune_stored_vehicle_configs(self, live_vins):
        """Drop per-vehicle stored config for vehicles no longer on the account."""
        vehicles = self.get_vehicles_stored_config()
        stale = [vin for vin in vehicles if vin not in live_vins]
        if not stale:
            return []
        new_vehicles = {vin: deepcopy(value) for vin, value in vehicles.items() if vin not in stale}
        self.update_stored_config("vehicles", new_vehicles)
        # Through save_config() so the log filter's snapshot drops the stale VINs.
        self.save_config({"vehicles": deepcopy(new_vehicles)})
        _LOGGER.info("Removed stored config for vehicles no longer on the account: %s", ", ".join(stale))
        return stale

    @property
    def coordinators(self) -> list[StellantisVehicleCoordinator]:
        return list(self._coordinator_dict.values())

    def async_get_coordinator_by_vin(self, vin):
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        return None

    async def async_get_coordinator(self, vehicle):
        vin = vehicle["vin"]
        if vin in self._coordinator_dict:
            return self._coordinator_dict[vin]
        translations = await translation.async_get_translations(self._hass, self._hass.config.language, "entity", {DOMAIN})
        coordinator = self.coordinator_class(self._hass, self._config, vehicle, self, translations, config_entry=self._entry)
        self._coordinator_dict[vin] = coordinator
        return coordinator

    async def resize_and_save_picture(self, url, vin, load=None):
        """ Save the vehicle picture under www once and return its local URL.

        ``load`` is an async function returning the image bytes, for a picture
        that is not served at a plain URL; it is only called if no picture is
        saved yet.
        """
        public_path = self._hass.config.path("www")
        customer_id = self.get_config("customer_id")
        if not os.path.isdir(public_path):
            _LOGGER.warning("Folder \"www\" not found in configuration folder")
            return url
        entry_path = f"{public_path}/{DOMAIN}/{customer_id}"
        if not os.path.isdir(entry_path):
            os.makedirs(entry_path, exist_ok=True)
        image_path = f"{entry_path}/{vin}.png"
        image_url = image_path.replace(public_path, "/local")
        if os.path.isfile(image_path):
            return image_url
        if load is not None:
            image_data = await load()
            if not image_data:
                return url
        else:
            session = async_get_clientsession(self._hass)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                image_data = await resp.read()

        def _resize_and_save() -> None:
            with Image.open(BytesIO(image_data)) as im:
                im = ImageOps.pad(im, (400, 400))
                im.save(image_path)

        await self._hass.async_add_executor_job(_resize_and_save)
        return image_url

    def do_async(self, async_func, delay=0, *, wait):
        """Schedule a coroutine on self._hass.loop from any thread.

        wait=True blocks for the result and is only safe from a thread
        other than the one running self._hass.loop (e.g. paho-mqtt's
        network thread) - called from that thread itself, this raises
        instead of deadlocking Home Assistant. wait=False just schedules
        the coroutine and returns None.
        """
        if self._shutting_down:
            # The config entry is being unloaded - drop the coroutine instead of
            # scheduling work that would resurrect the MQTT client or hit an
            # already closed aiohttp session.
            async_func.close()
            return None

        if wait:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is self._hass.loop:
                async_func.close()
                raise RuntimeError(
                    "do_async(wait=True) called from the Home Assistant event loop thread - this would deadlock"
                )

        async def delayed_execution():
            task = asyncio.current_task()
            self._pending_tasks.add(task)
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                if self._shutting_down:
                    async_func.close()
                    return None
                return await async_func
            except asyncio.CancelledError:
                async_func.close()
                raise
            finally:
                self._pending_tasks.discard(task)

        future = asyncio.run_coroutine_threadsafe(delayed_execution(), self._hass.loop)
        return future.result() if wait else None

    async def hass_notify(self, translation_key):
        """Create a persistent notification."""
        if self._entry is not None and not self.get_stored_config(FIELD_NOTIFICATIONS):
            return

        translations = await translation.async_get_translations(self._hass, self._hass.config.language, "common", {DOMAIN})
        notification_title = "Stellantis Vehicles"
        if translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None):
            notification_title = notification_title + " - " + str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_title", None))
        notification_message = str(translations.get(f"component.stellantis_vehicles.common.{translation_key}_message", None))

        notification_title = replace_string_placeholders(notification_title, TRANSLATION_PLACEHOLDERS)
        notification_message = replace_string_placeholders(notification_message, TRANSLATION_PLACEHOLDERS)

        persistent_notification.async_create(
            self._hass,
            notification_message,
            title=notification_title,
            notification_id=str(uuid4())
        )

    async def send_abrp_data(self, params:dict[str, Any]) -> None:
        """ Push telemetry to A Better Routeplanner. Never raises: ABRP is optional. """
        params["api_key"] = ABRP_API_KEY
        try:
            self.start_session()
            async with self._session.post(ABRP_URL, params=params, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                result = await resp.json()
            if not isinstance(result, dict) or result.get("status") != "ok":
                _LOGGER.warning("Unexpected ABRP response: %s", result)
        except Exception as e:
            _LOGGER.warning("Failed to send ABRP data: %s", e)
