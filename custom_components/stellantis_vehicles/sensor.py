import logging
from time import strftime
from time import gmtime

from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import ( UnitOfLength, UnitOfSpeed, UnitOfEnergy, UnitOfVolume )
from homeassistant.components.sensor.const import SensorDeviceClass
from .base import ( StellantisBaseSensor, StellantisRestoreSensor )

from .const import (
    DOMAIN,
    FIELD_COUNTRY_CODE,
    SENSORS_DEFAULT,
    VEHICLE_TYPE_ELECTRIC,
    MS_TO_KMH_CONVERSION,
    KWH_CORRECTION
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass:HomeAssistant, entry, async_add_entities) -> None:
    stellantis = hass.data[DOMAIN][entry.entry_id]
    entities = []

    vehicles = await stellantis.get_user_vehicles()

    for vehicle in vehicles:
        coordinator = await stellantis.async_get_coordinator(vehicle)

        for key in SENSORS_DEFAULT:
            default_value = SENSORS_DEFAULT.get(key, {})
            sensor_engine_limit = default_value.get("engine", [])
            if not sensor_engine_limit or coordinator.vehicle_type in sensor_engine_limit:
                if default_value.get("value_map", None) and default_value.get("updated_at_map", None):
                    description = SensorEntityDescription(
                        name = key,
                        key = key,
                        translation_key = key,
                        icon = default_value.get("icon", None),
                        unit_of_measurement = default_value.get("unit_of_measurement", None),
                        device_class = default_value.get("device_class", None),
                        state_class = default_value.get("state_class", None),
                        suggested_display_precision = default_value.get("suggested_display_precision", None)
                    )
                    entities.extend([StellantisBaseSensor(coordinator, description, default_value.get("value_map"), default_value.get("updated_at_map"), default_value.get("available", None))])

        description = SensorEntityDescription(
            name = "type",
            key = "type",
            translation_key = "type",
            icon = "mdi:car-info"
        )
        entities.extend([StellantisTypeSensor(coordinator, description)])

        if stellantis.remote_commands:
            description = SensorEntityDescription(
                name = "command_status",
                key = "command_status",
                translation_key = "command_status",
                icon = "mdi:format-list-bulleted-type"
            )
            entities.extend([StellantisCommandStatusSensor(coordinator, description)])

        description = SensorEntityDescription(
            name = "last_trip",
            key = "last_trip",
            translation_key = "last_trip",
            icon = "mdi:map-marker-path",
            unit_of_measurement = UnitOfLength.KILOMETERS,
            device_class = SensorDeviceClass.DISTANCE
        )
        entities.extend([StellantisLastTripSensor(coordinator, description)])

#         description = SensorEntityDescription(
#             name = "total_trip",
#             key = "total_trip",
#             translation_key = "total_trip",
#             icon = "mdi:map-marker-path"
#         )
#         entities.extend([StellantisTotalTripSensor(coordinator, description)])

#         await coordinator.async_request_refresh()

    async_add_entities(entities)


class StellantisTypeSensor(StellantisRestoreSensor):
    def coordinator_update(self):
        self._attr_native_value = self._coordinator.vehicle_type.lower()


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


class StellantisLastTripSensor(StellantisRestoreSensor):
    def coordinator_update(self):
        last_trip = self._coordinator._last_trip
        if not last_trip:
            return

        state = None
        if "distance" in last_trip:
            state = last_trip["distance"]
        self._attr_native_value = state

        attributes = {}
        if "duration" in last_trip and float(last_trip["duration"]) > 0:
            attributes["duration"] = strftime("%H:%M:%S", gmtime(last_trip["duration"]))
        if "startMileage" in last_trip:
            attributes["start_mileage"] = str(last_trip["startMileage"]) + " " + UnitOfLength.KILOMETERS
        if "kinetic" in last_trip:
            if "avgSpeed" in last_trip["kinetic"] and float(last_trip["kinetic"]["avgSpeed"]) > 0:
                avg_speed_kmh = float(last_trip["kinetic"]["avgSpeed"]) * MS_TO_KMH_CONVERSION
                attributes["avg_speed"] = str(round(avg_speed_kmh, 2)) + " " + UnitOfSpeed.KILOMETERS_PER_HOUR
            if "maxSpeed" in last_trip["kinetic"] and float(last_trip["kinetic"]["maxSpeed"]) > 0:
                max_speed_kmh = float(last_trip["kinetic"]["maxSpeed"])
                attributes["max_speed"] = str(round(max_speed_kmh, 2)) + " " + UnitOfSpeed.KILOMETERS_PER_HOUR
        if "energyConsumptions" in last_trip:
            for consuption in last_trip["energyConsumptions"]:
                if "type" not in consuption:
                    continue
                consumption_unit_of_measurement = ""
                avg_consumption_unit_of_measurement = ""
                if consuption["type"] == VEHICLE_TYPE_ELECTRIC:
                    consumption_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
                    avg_consumption_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR+"/100"+UnitOfLength.KILOMETERS
                    divide = 1000
                    correction_on = self._coordinator._sensors.get("switch_battery_values_correction", False)
                    if correction_on:
                        divide = divide / KWH_CORRECTION
                else:
                    consumption_unit_of_measurement = UnitOfVolume.LITERS
                    avg_consumption_unit_of_measurement = UnitOfVolume.LITERS+"/100"+UnitOfLength.KILOMETERS
                    divide = 100
                if "consumption" in consuption and round(float(consuption["consumption"])/divide, 2) > 0:
                    attributes[consuption["type"].lower() + "_consumption"] = str(round(float(consuption["consumption"])/divide, 2)) + " " + consumption_unit_of_measurement
                if "avgConsumption" in consuption and round(float(consuption["avgConsumption"])/divide, 2) > 0:
                    attributes[consuption["type"].lower() + "_avg_consumption"] = str(round(float(consuption["avgConsumption"])/divide, 2)) + " " + avg_consumption_unit_of_measurement
        self._attr_extra_state_attributes = attributes


# class StellantisTotalTripSensor(StellantisRestoreSensor):
#     def coordinator_update(self):
#         total_trip = self._coordinator._total_trip
#         if not total_trip:
#             return
#         totals = total_trip["totals"]
#         trips = total_trip["trips"]
#         included = len(trips)
#         results = {}
#         inde = 1
#         for trip in trips:
#             _LOGGER.error(inde)
#             inde = inde + 1
#             for engine in trip["engine"]:
#                 if engine + "_distance" not in results:
#                     results[engine + "_distance"] = 0
#                 if engine + "_consumption" not in results:
#                     results[engine + "_consumption"] = 0
#                 results[engine + "_distance"] = results[engine + "_distance"] + trip["engine"][engine]["distance"]
#                 results[engine + "_consumption"] = results[engine + "_consumption"] + trip["engine"][engine]["consumption"]
#                 results[engine + "_avg_consumption"] = results[engine + "_consumption"] / results[engine + "_distance"] * 100
#
#         self._attr_native_value = str(included) + "/" + str(totals)
#         self._attr_extra_state_attributes = results
