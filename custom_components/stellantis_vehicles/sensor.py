import logging

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import ( UnitOfLength, UnitOfSpeed )
from .base import ( StellantisBaseSensor, StellantisRestoreSensor )

from .const import (
    DOMAIN,
    FIELD_COUNTRY_CODE,
    SENSORS_DEFAULT
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)

        for key in SENSORS_DEFAULT:
            default_value = SENSORS_DEFAULT.get(key, {})
            sensor_engine_limit = default_value.get("engine", [])
            if not sensor_engine_limit or coordinator.vehicle_type in sensor_engine_limit:
                if default_value.get("data_map", None):

                    unit_of_measurement = default_value.get("unit_of_measurement", None)
                    if stellantis.get_config(FIELD_COUNTRY_CODE) == "GB":
                        if key in ["mileage","autonomy","fuel_autonomy"]:
                            unit_of_measurement = UnitOfLength.MILES
                        if key == "battery_charging_rate":
                            unit_of_measurement = UnitOfSpeed.MILES_PER_HOUR

                    description = SensorEntityDescription(
                        name = key,
                        key = key,
                        translation_key = key,
                        icon = default_value.get("icon", None),
                        unit_of_measurement = unit_of_measurement,
                        device_class = default_value.get("device_class", None),
                        suggested_display_precision = default_value.get("suggested_display_precision", None)
                    )
                    entities.extend([StellantisBaseSensor(coordinator, description, default_value.get("data_map", None), default_value.get("available", None))])

        description = SensorEntityDescription(
            name = "type",
            key = "type",
            translation_key = "type",
            icon = "mdi:car-info"
        )
        entities.extend([StellantisTypeSensor(coordinator, description)])

        description = SensorEntityDescription(
            name = "command_status",
            key = "command_status",
            translation_key = "command_status",
            icon = "mdi:format-list-bulleted-type"
        )
        entities.extend([StellantisCommandStatusSensor(coordinator, description)])

#         await coordinator.async_request_refresh()

    async_add_entities(entities)


class StellantisTypeSensor(StellantisRestoreSensor):
    def coordinator_update(self):
        self._attr_native_value = self._coordinator.vehicle_type


class StellantisCommandStatusSensor(StellantisRestoreSensor):
    def coordinator_update(self):
        command_history = self._coordinator.command_history
        if not command_history:
            return
        attributes = {}
        for index, date in enumerate(command_history):
            if index == 0:
                self._attr_native_value = command_history[date]
            else:
                attributes[date] = command_history[date]

        self._attr_extra_state_attributes = attributes