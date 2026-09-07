import logging
import shutil
import os

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry, device_registry as dr
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .stellantis import StellantisVehicles
from .config_flow import StellantisVehiclesConfigFlow

from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    INTEGRATION_IS_BETA,
    PLATFORMS,
    OTP_FILENAME,
    FIELD_NOTIFICATIONS,
    UPDATE_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry):

    stellantis = StellantisVehicles(hass)
    stellantis.save_config(config.data)
    stellantis.set_entry(config)
    await stellantis.scheduled_tokens_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config.entry_id] = stellantis

    try:
        vehicles = await stellantis.get_user_vehicles()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        # Home Assistant does not call async_unload_entry when async_setup_entry
        # raises, so drop this attempt's state (pending tasks, scheduled
        # token-refresh jobs, aiohttp session) before bubbling up. Raising
        # ConfigEntryNotReady makes Home Assistant retry with backoff instead of
        # leaving a loaded but empty entry behind a misleading "no vehicles" notice.
        await stellantis.async_shutdown()
        hass.data[DOMAIN].pop(config.entry_id, None)
        raise ConfigEntryNotReady(f"Could not fetch the vehicle list: {err}") from err

    if vehicles:
        stellantis.prune_stored_vehicle_configs({vehicle["vin"] for vehicle in vehicles})

        # Build every coordinator and run its first refresh BEFORE forwarding the
        # platforms - the standard Home Assistant setup order. A failing first
        # refresh then raises ConfigEntryNotReady / ConfigEntryAuthFailed while no
        # platform or entity is set up yet, so Home Assistant retries the whole
        # entry cleanly. Entities are also created already holding the data from
        # the first poll, instead of briefly existing with an empty coordinator.
        try:
            for index, vehicle in enumerate(vehicles):
                coordinator = await stellantis.async_get_coordinator(vehicle)
                await coordinator.async_config_entry_first_refresh()
                if index and len(vehicles) > 1:
                    # Spread the periodic polls of multiple vehicles across the
                    # interval instead of hitting the API for all of them at once.
                    coordinator.stagger_first_poll(index * UPDATE_INTERVAL / len(vehicles))
        except Exception:
            # First refresh failed (ConfigEntryNotReady / ConfigEntryAuthFailed /
            # ...). Home Assistant does not call async_unload_entry when
            # async_setup_entry raises, so drop this attempt's state here: the
            # retry then starts from a clean slate and the MQTT client, pending
            # tasks, scheduled token-refresh jobs and aiohttp session from this
            # attempt do not leak.
            await stellantis.async_shutdown()
            hass.data[DOMAIN].pop(config.entry_id, None)
            raise

        await hass.config_entries.async_forward_entry_setups(config, PLATFORMS)
    else:
        _LOGGER.warning("No vehicles found for this account")
        await stellantis.hass_notify("no_vehicles_found")
        await stellantis.close_session()

    url = f"/stellantis_vehicles/{INTEGRATION_VERSION}/stellantis-vehicle-card.js"
    if url not in hass.data["frontend_extra_module_url"].urls:
        file_path = os.path.join(os.path.dirname(__file__), "frontend", "stellantis-vehicle-card.js")
        await hass.http.async_register_static_paths([StaticPathConfig(url, str(file_path), False)])
        add_extra_js_url(hass, url)

    return True


async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    stellantis = hass.data[DOMAIN][config.entry_id]

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        await stellantis.async_shutdown()
        hass.data[DOMAIN].pop(config.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config: ConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a device only when its vehicle is no longer on the account.

    Without this the UI offers no way to remove a vehicle's device, so the
    device and its (now unavailable) entities linger after the vehicle is
    unpaired. A device for a vehicle still returned by the account cannot be
    deleted - it would just be recreated on the next refresh.
    """
    stellantis = hass.data.get(DOMAIN, {}).get(config.entry_id)
    if stellantis is None:
        return True
    try:
        known_vins = {
            vehicle["vin"] for vehicle in await stellantis.get_user_vehicles()
        }
    except Exception as err:  # noqa: BLE001 - never block manual cleanup on an API error
        _LOGGER.warning("Could not verify account vehicles before device removal: %s", err)
        known_vins = set()
    return not any(
        identifier[0] == DOMAIN and identifier[1] in known_vins
        for identifier in device.identifiers
    )


async def async_remove_entry(hass: HomeAssistant, config: ConfigEntry) -> None:
    if not hass.config_entries.async_loaded_entries(DOMAIN):

        # Remove stale repairs (if any) - just in case this integration will use
        # the issue registry in the future
        issue_registry.async_delete_issue(hass, DOMAIN, DOMAIN)

        # Remove any remaining disabled or ignored entries
        for _entry in hass.config_entries.async_entries(DOMAIN):
            hass.async_create_task(hass.config_entries.async_remove(_entry.entry_id))

        # Generate path to storage folder and OTP file
        hass_config_path = hass.config.path()
        storage_path = os.path.join(hass_config_path, ".storage", DOMAIN)
        otp_file_path = os.path.join(storage_path, OTP_FILENAME)
        otp_file_path = otp_file_path.replace("{#customer_id#}", config.unique_id)
        entry_image_path = os.path.join(hass_config_path, "www", DOMAIN, config.unique_id)
        image_path = os.path.join(hass_config_path, "www", DOMAIN)

        def cleanup_files():
            # Run the blocking filesystem work on an executor thread so it never
            # stalls the event loop - matches the async_migrate_entry steps.

            # Remove OTP file if it exists
            if os.path.isfile(otp_file_path):
                _LOGGER.debug("Deleting OTP file: %s", otp_file_path)
                os.remove(otp_file_path)

            # Remove storage folder if empty
            if os.path.exists(storage_path) and os.path.isdir(storage_path) and not os.listdir(storage_path):
                _LOGGER.debug("Deleting empty Stellantis storage folder: %s", storage_path)
                shutil.rmtree(storage_path)

            # Remove Stellantis image folder of this entry
            if os.path.exists(entry_image_path) and os.path.isdir(entry_image_path):
                _LOGGER.debug("Deleting Stellantis entry image folder: %s", entry_image_path)
                shutil.rmtree(entry_image_path)

            # Remove Stellantis image folder if empty
            if os.path.exists(image_path) and os.path.isdir(image_path) and not os.listdir(image_path):
                _LOGGER.debug("Deleting Stellantis image folder: %s", image_path)
                shutil.rmtree(image_path)

        await hass.async_add_executor_job(cleanup_files)


async def async_migrate_entry(hass: HomeAssistant, config: ConfigEntry):

    target_version = 1
    target_minor_version = 2    # Migrate config prior 1.2 to 1.2 - unique_id and file structure
    if config.version == target_version and config.minor_version < target_minor_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        # update unique_id with customer_id - used to be data[FIELD_MOBILE_APP].lower()+str(self.data["access_token"][:5])
        new_unique_id = config.data.get("customer_id")
        if config.unique_id != new_unique_id:
            _LOGGER.debug("Migrating unique_id from %s to %s", config.unique_id, new_unique_id)
            hass.config_entries.async_update_entry(config, unique_id=new_unique_id)
        # Migrate to new file structure - generate path to storage folder and move OTP file
        hass_config_path = hass.config.path()
        old_otp_file_path = os.path.join(hass_config_path, ".storage/stellantis_vehicles_otp.pickle")

        def migrate_otp_file():
            # Run the blocking filesystem work on an executor thread so it never
            # stalls the event loop - matches the later migration steps.
            if not os.path.isfile(old_otp_file_path):
                return
            new_storage_path = os.path.join(hass_config_path, ".storage", DOMAIN)
            new_otp_file_path = os.path.join(new_storage_path, OTP_FILENAME)
            new_otp_file_path = new_otp_file_path.replace("{#customer_id#}", new_unique_id)
            if not os.path.isdir(new_storage_path):
                os.mkdir(new_storage_path)
            if not os.path.isfile(new_otp_file_path):
                _LOGGER.debug("Migrating OTP file to new storage path from %s to %s", old_otp_file_path, new_otp_file_path)
                os.rename(old_otp_file_path, new_otp_file_path)
            else:
                os.remove(old_otp_file_path)

        await hass.async_add_executor_job(migrate_otp_file)
        # Update config entry object
        hass.config_entries.async_update_entry(config, version=target_version, minor_version=target_minor_version)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    target_version = 1
    target_minor_version = 3
    if config.version == target_version and config.minor_version < target_minor_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        public_path = hass.config.path("www")
        old_image_path = f"{public_path}/stellantis-vehicles"

        def remove_old_image_folder():
            # Run the blocking filesystem work on an executor thread so it never
            # stalls the event loop - matches the later migration steps.
            if os.path.isdir(old_image_path):
                _LOGGER.debug("Deleting Stellantis old image folder: %s", old_image_path)
                shutil.rmtree(old_image_path)

        await hass.async_add_executor_job(remove_old_image_folder)
        hass.config_entries.async_update_entry(config, version=target_version, minor_version=target_minor_version)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    target_version = 1
    target_minor_version = 4
    if config.version == target_version and config.minor_version < target_minor_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        data = dict(config.data)
        data["oauth"] = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_in": data["expires_in"]
        }
        data.pop("access_token", None)
        data.pop("refresh_token", None)
        data.pop("expires_in", None)
        hass.config_entries.async_update_entry(config, data=data, version=target_version, minor_version=target_minor_version)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    target_version = 1
    target_minor_version = 5
    if config.version == target_version and config.minor_version < target_minor_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        data = dict(config.data)

        def update_data(data):
            public_path = hass.config.path("www")
            customer_id = data["customer_id"]
            entry_path = f"{public_path}/{DOMAIN}/{customer_id}"
            if os.path.isdir(entry_path):
                for vin in os.listdir(entry_path):
                    vin_path = os.path.join(entry_path, vin)
                    if os.path.isfile(vin_path):
                        vin = os.path.splitext(vin)[0]
                        data[vin] = {}
                        if "text_abrp_token" in data:
                            data[vin]["text_abrp_token"] = data["text_abrp_token"]
                        if "number_battery_charging_limit" in data:
                            data[vin]["number_battery_charging_limit"] = data["number_battery_charging_limit"]
                        if "number_refresh_interval" in data:
                            data[vin]["number_refresh_interval"] = data["number_refresh_interval"]
                        if "switch_battery_charging_limit" in data:
                            data[vin]["switch_battery_charging_limit"] = data["switch_battery_charging_limit"]
                        if "switch_abrp_sync" in data:
                            data[vin]["switch_abrp_sync"] = data["switch_abrp_sync"]
                        if "switch_battery_values_correction" in data:
                            data[vin]["switch_battery_values_correction"] = data["switch_battery_values_correction"]
                        if "switch_notifications" in data:
                            data[vin]["switch_notifications"] = data["switch_notifications"]
            data.pop("text_abrp_token", None)
            data.pop("number_battery_charging_limit", None)
            data.pop("number_refresh_interval", None)
            data.pop("switch_battery_charging_limit", None)
            data.pop("switch_abrp_sync", None)
            data.pop("switch_battery_values_correction", None)
            data.pop("switch_notifications", None)
            return data

        new_data = await hass.async_add_executor_job(update_data, data)
        hass.config_entries.async_update_entry(config, data=new_data, version=target_version, minor_version=target_minor_version)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    target_version = 1
    target_minor_version = 6
    if config.version == target_version and config.minor_version < target_minor_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        data = dict(config.data)

        def update_data(data):
            public_path = hass.config.path("www")
            customer_id = data["customer_id"]
            entry_path = f"{public_path}/{DOMAIN}/{customer_id}"
            if os.path.isdir(entry_path):
                for vin in os.listdir(entry_path):
                    vin_path = os.path.join(entry_path, vin)
                    if os.path.isfile(vin_path):
                        vin = os.path.splitext(vin)[0]
                        if vin in data and "switch_notifications" in data[vin]:
                            data[FIELD_NOTIFICATIONS] = data[vin]["switch_notifications"]
                            data[vin].pop("switch_notifications", None)
            return data

        new_data = await hass.async_add_executor_job(update_data, data)
        hass.config_entries.async_update_entry(config, data=new_data, version=target_version, minor_version=target_minor_version)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    # Bumped past the current INTEGRATION_VERSION (20260801) on purpose: betas
    # already shipped as 20260801, so this migration must still trigger for
    # entries already sitting at that version. Aligns with INTEGRATION_VERSION
    # once the 2026.8.2 stable ships.
    target_version = 20260802
    if config.version < target_version or "vehicles" not in config.data:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        data = dict(config.data)

        def update_data(data):
            # Move all flat per-vehicle nodes under a dedicated "vehicles" sub-node
            # so the stale-vehicle prune process can no longer touch other config data.
            vehicles = dict(data.get("vehicles", {}))
            reserved = ("oauth", "mqtt", "vehicles")
            for key in list(data.keys()):
                value = data[key]
                if key in reserved or not isinstance(value, dict):
                    continue
                # Extra safety: only treat entries that look like a VIN (17 alphanumeric chars).
                if len(key) == 17 and key.isalnum():
                    moved = data.pop(key)
                    # A "vehicles" entry written by a newer build before this
                    # migration ran wins per key over the older flat data.
                    vehicles[key] = {**moved, **vehicles.get(key, {})}
            data["vehicles"] = vehicles
            return data

        new_data = await hass.async_add_executor_job(update_data, data)
        if INTEGRATION_IS_BETA:
            # Leave the entry version alone on beta (see the global update below)
            hass.config_entries.async_update_entry(config, data=new_data)
        else:
            hass.config_entries.async_update_entry(config, data=new_data, version=target_version, minor_version=1)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    # template for future migration steps
    target_version = 20260702   # to be updated with the next version number
    if config.version < target_version:
        _LOGGER.debug("Migrating configuration from version %s.%s", config.version, config.minor_version)
        data = dict(config.data)
        def update_data(data):
            # migration logic here
            return data
        new_data = await hass.async_add_executor_job(update_data, data)
        if INTEGRATION_IS_BETA:
            # Leave the entry version alone on beta (see the global update below)
            hass.config_entries.async_update_entry(config, data=new_data)
        else:
            hass.config_entries.async_update_entry(config, data=new_data, version=target_version, minor_version=1)
        _LOGGER.debug("Migration to configuration version %s.%s successful", config.version, config.minor_version)

    # Global update of versions - only pull the entry version forward on real
    # (non-beta) releases, so beta iterations that share a version number keep
    # re-triggering their own migration steps until the stable release ships.
    if config.version < INTEGRATION_VERSION and not INTEGRATION_IS_BETA:
        _LOGGER.debug("Entry version updated from %s.%s to %s.1", config.version, config.minor_version, INTEGRATION_VERSION)
        hass.config_entries.async_update_entry(config, version=INTEGRATION_VERSION, minor_version=1)

    return True
