import logging
import shutil
import os

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry

from .stellantis import StellantisVehicles

from .const import (
    DOMAIN,
    PLATFORMS,
    IMAGE_PATH,
    OTP_FILENAME
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry):

    stellantis = StellantisVehicles(hass)
    stellantis.save_config(config.data)
    stellantis.set_entry(config)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config.entry_id] = stellantis

    # Migrate to new file structure - can be removed in future versions
    ### Gennerate path to storage folder and move OTP file
    hass_config_path = hass.config.path()
    old_otp_file_path = os.path.join(hass_config_path, ".storage/stellantis_vehicles_otp.pickle")
    if os.path.isfile(old_otp_file_path):
        new_storage_path = os.path.join(hass_config_path, ".storage", DOMAIN)
        new_otp_file_path = os.path.join(new_storage_path, OTP_FILENAME)
        new_otp_file_path = new_otp_file_path.replace("{#customer_id#}", stellantis.get_config("customer_id"))
        if not os.path.isdir(new_storage_path):
            os.mkdir(new_storage_path)
        if not os.path.isfile(new_otp_file_path):
            _LOGGER.debug(f"Migrating OTP file to new storage path: {old_otp_file_path} -> {new_otp_file_path}")
            os.rename(old_otp_file_path, new_otp_file_path)
        else:
            os.remove(old_otp_file_path)
    # END Migrate to new file structure

    try:
        await stellantis.refresh_token()
        vehicles = await stellantis.get_user_vehicles()
    except ConfigEntryAuthFailed as e:
        await stellantis.close_session()
        raise
    except Exception as e:
        _LOGGER.error(str(e))
        await stellantis.close_session()
        vehicles = {}

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        await coordinator.async_config_entry_first_refresh()

    if vehicles:
        await hass.config_entries.async_forward_entry_setups(config, PLATFORMS)
        await stellantis.connect_mqtt()
    else:
        _LOGGER.error("No vehicles found for this account")
        await stellantis.hass_notify("no_vehicles_found")
        await stellantis.close_session()

    return True


async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    stellantis = hass.data[DOMAIN][config.entry_id]

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        hass.data[DOMAIN].pop(config.entry_id)

    stellantis._mqtt.disconnect()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, config: ConfigEntry) -> None:
    if not hass.config_entries.async_loaded_entries(DOMAIN):

        # Remove stale repairs (if any) - just in case this integration will use
        # the issue registry in the future
        issue_registry.async_delete_issue(hass, DOMAIN, DOMAIN)

        # Remove any remaining disabled or ignored entries
        for _entry in hass.config_entries.async_entries(DOMAIN):
            hass.async_create_task(hass.config_entries.async_remove(_entry.entry_id))

        # Gennerate path to storage folder and OTP file
        hass_config_path = hass.config.path()
        storage_path = os.path.join(hass_config_path, ".storage", DOMAIN)
        otp_file_path = os.path.join(storage_path, OTP_FILENAME)
        otp_file_path = otp_file_path.replace("{#customer_id#}", config.unique_id)

        # Remove OTP file if it exists
        if os.path.isfile(otp_file_path):
            _LOGGER.debug(f"Deleting OTP-File: {otp_file_path}")
            os.remove(otp_file_path)

        # Remove storage folder if empty
        if (os.path.exists(storage_path) and os.path.isdir(storage_path) and not os.listdir(storage_path)):
            _LOGGER.debug(f"Deleting empty Stellantis storage folder: {storage_path}")
            shutil.rmtree(storage_path)

        # Remove Stellantis image folder of this entry
        entry_image_path = os.path.join(hass_config_path, "www", IMAGE_PATH, config.unique_id)
        if (os.path.exists(entry_image_path) and os.path.isdir(entry_image_path)):
            _LOGGER.debug(f"Deleting Stellantis entry image folder: {entry_image_path}")
            shutil.rmtree(entry_image_path)

        # Remove Stellantis image folder if empty
        image_path = os.path.join(hass_config_path, "www", IMAGE_PATH)
        if (os.path.exists(image_path) and os.path.isdir(image_path) and not os.listdir(image_path)):
            _LOGGER.debug(f"Deleting Stellantis image folder: {image_path}")
            shutil.rmtree(image_path)
