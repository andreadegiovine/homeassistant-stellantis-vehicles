import logging

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
                if default_value.get("data_map", None):
                    description = BinarySensorEntityDescription(
                        name = key,
                        key = key,
                        translation_key = key,
                        icon = default_value.get("icon", None),
                        device_class = default_value.get("device_class", None)
                    )
                    entities.extend([StellantisBaseBinarySensor(coordinator, description, default_value.get("data_map", None), default_value.get("on_value", None))])

        description = BinarySensorEntityDescription(
            name = "remote_control",
            key = "remote_control",
            translation_key = "remote_control",
            icon = "mdi:broadcast",
            device_class = BinarySensorDeviceClass.CONNECTIVITY
        )
        entities.extend([StellantisRemoteControlBinarySensor(coordinator, description)])

    async_add_entities(entities)


class StellantisRemoteControlBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def coordinator_update(self):
        self._attr_is_on = self._stellantis._mqtt.is_connected()