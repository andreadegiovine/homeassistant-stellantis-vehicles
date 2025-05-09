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
    OTP_FILE_NAME
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry):

    stellantis = StellantisVehicles(hass)
    stellantis.save_config(config.data)
    stellantis.set_entry(config)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config.entry_id] = stellantis

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
        await stellantis.create_persistent_notification("notification_no_vehicles_found")
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

        # Remove OTP file
        # Curently just a single file, but might be changed in the future
        # to allow for multiple OTP files
        # (e.g. for multiple Stellantis accounts)
        otp_filename = os.path.join(hass.config.config_dir, OTP_FILE_NAME)
        if os.path.isfile(otp_filename):
            _LOGGER.debug(f"Deleting OTP-File: {otp_filename}")
            os.remove(otp_filename)

        # Remove related vehicle images
        if "vehicles" in config.data:
            for vehicle in config.data["vehicles"]:
                vehicle_image_path = os.path.join(hass.config.config_dir, vehicle["picture"].replace("/local", "www"))
                if os.path.exists(vehicle_image_path) and os.path.isfile(vehicle_image_path):
                    _LOGGER.debug(f"Deleting Stellantis Vehicle image: {vehicle_image_path}")
                    os.remove(vehicle_image_path)

        # Remove Stellantis image folder if empty
        public_path = os.path.join(hass.config.config_dir, "www")
        stellantis_path = f"{public_path}/{IMAGE_PATH}"
        if (os.path.exists(stellantis_path) and os.path.isdir(stellantis_path) and not os.listdir(stellantis_path)):
            _LOGGER.debug(f"Deleting empty Stellantis image folder: {stellantis_path}")
            shutil.rmtree(stellantis_path)
