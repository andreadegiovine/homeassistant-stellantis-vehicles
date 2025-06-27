import logging
from copy import deepcopy

from homeassistant.components.binary_sensor import ( BinarySensorEntity, BinarySensorEntityDescription, BinarySensorDeviceClass )
from .base import ( StellantisBaseBinarySensor, StellantisBaseEntity )

from .const import (
    DOMAIN,
    BINARY_SENSORS_DEFAULT
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)

        for key in BINARY_SENSORS_DEFAULT:
            default_value = BINARY_SENSORS_DEFAULT.get(key, {})
            sensor_engine_limit = default_value.get("engine", [])
            if not sensor_engine_limit or coordinator.vehicle_type in sensor_engine_limit:
                if default_value.get("value_map", None) and default_value.get("updated_at_map", None):
                    description = BinarySensorEntityDescription(
                        name = key,
                        key = key,
                        translation_key = key,
                        icon = default_value.get("icon", None),
                        device_class = default_value.get("device_class", None)
                    )
                    entities.extend([StellantisBaseBinarySensor(coordinator, description, deepcopy(default_value.get("value_map")), deepcopy(default_value.get("updated_at_map")), default_value.get("on_value", None))])

        description = BinarySensorEntityDescription(
            name = "remote_commands",
            key = "remote_commands",
            translation_key = "remote_commands",
            icon = "mdi:broadcast",
            device_class = BinarySensorDeviceClass.CONNECTIVITY
        )
        entities.extend([StellantisRemoteCommandsBinarySensor(coordinator, description)])

    async_add_entities(entities)


class StellantisRemoteCommandsBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def coordinator_update(self):
        self._attr_is_on = self._stellantis and self._stellantis._mqtt and self._stellantis._mqtt.is_connected()