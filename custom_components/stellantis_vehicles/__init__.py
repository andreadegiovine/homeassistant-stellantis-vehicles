import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .stellantis import StellantisVehicles

from .const import (
    DOMAIN,
    PLATFORMS
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry):

    stellantis = StellantisVehicles(hass)
    stellantis.save_config(config.data)
    stellantis.set_entry(config)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config.entry_id] = stellantis

    try:
        vehicles = await stellantis.get_user_vehicles()
    except Exception as e:
        _LOGGER.error(str(e))
        vehicles = {}

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)
        await coordinator.async_config_entry_first_refresh()

    if vehicles:
        await hass.config_entries.async_forward_entry_setups(config, PLATFORMS)

        stellantis.register_webhook()

    return True


async def async_unload_entry(hass: HomeAssistant, config: ConfigEntry) -> bool:
    stellantis = hass.data[DOMAIN][config.entry_id]

    if unload_ok := await hass.config_entries.async_unload_platforms(config, PLATFORMS):
        hass.data[DOMAIN].pop(config.entry_id)

    stellantis.remove_webhooks()

    return unload_ok