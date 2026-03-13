import logging
from time import ( strftime, gmtime )
from copy import deepcopy

from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import ( UnitOfLength, UnitOfSpeed, UnitOfEnergy, UnitOfVolume, UnitOfPower, PERCENTAGE )
from homeassistant.components.sensor.const import ( SensorDeviceClass, SensorStateClass )
from homeassistant.const import EntityCategory

from .base import ( StellantisBaseSensor, StellantisRestoreSensor )
from .utils import sort_dict

from .const import (
    DOMAIN,
    SENSORS_DEFAULT,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID,
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

        if coordinator.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            description = SensorEntityDescription(
                name = "last_charge",
                key = "last_charge",
                translation_key = "last_charge",
                icon = "mdi:ev-station",
                device_class = SensorDeviceClass.TIMESTAMP,
                entity_category = EntityCategory.DIAGNOSTIC
            )
            entities.extend([StellantisLastChargeSensor(coordinator, description)])

            description = SensorEntityDescription(
                name = "charge_cost",
                key = "charge_cost",
                translation_key = "charge_cost",
                icon = "mdi:cash",
                device_class = SensorDeviceClass.MONETARY,
                suggested_display_precision = 2
            )
            entities.extend([StellantisChargeCostSensor(coordinator, description)])

            description = SensorEntityDescription(
                name = "actual_average_consumption",
                key = "actual_average_consumption",
                translation_key = "actual_average_consumption",
                icon = "mdi:flash",
                unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR+"/100"+UnitOfLength.KILOMETERS,
                device_class = SensorDeviceClass.ENERGY_DISTANCE,
                state_class = SensorStateClass.MEASUREMENT,
                suggested_display_precision = 2
            )
            entities.extend([StellantisChargeMetricSensor(coordinator, description)])

        description = SensorEntityDescription(
            name = "type",
            key = "type",
            translation_key = "type",
            icon = "mdi:car-info",
            entity_category = EntityCategory.DIAGNOSTIC
        )
        entities.extend([StellantisTypeSensor(coordinator, description)])

        if stellantis.remote_commands:
            description = SensorEntityDescription(
                name = "command_status",
                key = "command_status",
                translation_key = "command_status",
                icon = "mdi:format-list-bulleted-type",
                entity_category = EntityCategory.DIAGNOSTIC
            )
            entities.extend([StellantisCommandStatusSensor(coordinator, description)])

        description = SensorEntityDescription(
            name = "last_trip",
            key = "last_trip",
            translation_key = "last_trip",
            icon = "mdi:map-marker-path",
            unit_of_measurement = UnitOfLength.KILOMETERS,
            device_class = SensorDeviceClass.DISTANCE,
            entity_category = EntityCategory.DIAGNOSTIC
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
        if command_history:
            self._attr_native_value = command_history[next(iter(command_history))]

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

class StellantisLastChargeSensor(StellantisRestoreSensor):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._sensor_key = self._key

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._coordinator.async_update_listeners()

    def _get_attribute_units(self):
        return {
            "initial_percentage": PERCENTAGE,
            "final_percentage": PERCENTAGE,
            "recharged_percent": PERCENTAGE,
            "initial_energy": UnitOfEnergy.KILO_WATT_HOUR,
            "final_energy": UnitOfEnergy.KILO_WATT_HOUR,
            "recharged_energy": UnitOfEnergy.KILO_WATT_HOUR,
            "avg_power": UnitOfPower.KILO_WATT,
            "initial_autonomy": UnitOfLength.KILOMETERS,
            "final_autonomy": UnitOfLength.KILOMETERS,
            "recharged_autonomy": UnitOfLength.KILOMETERS,
            "initial_mileage": UnitOfLength.KILOMETERS,
            "final_mileage": UnitOfLength.KILOMETERS,
            "distance_since_last_charge": UnitOfLength.KILOMETERS,
            "charge_cost": self._coordinator.currency_code,
            "actual_average_consumption": UnitOfEnergy.KILO_WATT_HOUR+"/100"+UnitOfLength.KILOMETERS
        }

    def _normalize_attributes(self, attributes):
        units = self._get_attribute_units()
        numbers = {
            "initial_percentage",
            "final_percentage",
            "recharged_percent",
            "initial_energy",
            "final_energy",
            "recharged_energy",
            "avg_power",
            "initial_autonomy",
            "final_autonomy",
            "recharged_autonomy",
            "initial_mileage",
            "final_mileage",
            "distance_since_last_charge",
            "charge_cost",
            "actual_average_consumption"
        }
        integers = {"initial_percentage", "final_percentage", "recharged_percent"}
        normalized = {}

        for key, value in attributes.items():
            if key == "in_progress":
                if isinstance(value, str):
                    normalized[key] = value.lower() in ["true", "yes", "on"]
                else:
                    normalized[key] = bool(value)
                continue

            if key in units and isinstance(value, str):
                suffix = f" {units[key]}"
                if suffix.strip() and value.endswith(suffix):
                    value = value[:-len(suffix)]

            if key in numbers:
                value = self._coordinator._float_or_none(value)
                if value is None:
                    continue
                if key in integers:
                    value = round(value)
            normalized[key] = value

        return normalized

    def _format_attributes(self, attributes):
        units = self._get_attribute_units()
        formatted = deepcopy(attributes)
        for key, value in list(formatted.items()):
            if key == "in_progress":
                continue
            if key in units and value is not None:
                unit = units[key]
                formatted[key] = f"{value} {unit}" if unit else value

        ordered_keys = [
            "in_progress",
            "duration",
            "final_time",
            "initial_percentage",
            "final_percentage",
            "recharged_percent",
            "initial_energy",
            "final_energy",
            "recharged_energy",
            "charge_cost",
            "avg_power",
            "initial_autonomy",
            "final_autonomy",
            "recharged_autonomy",
            "initial_mileage",
            "final_mileage",
            "distance_since_last_charge",
            "actual_average_consumption"
        ]

        return sort_dict(formatted, ordered_keys)

    def coordinator_update(self):
        last_charge_state = self._coordinator.get_last_charge_state()
        if last_charge_state["native_value"] is None and not last_charge_state["attributes"] and (self._attr_native_value is not None or self._attr_extra_state_attributes):
            self._coordinator.set_last_charge_state(self._attr_native_value, self._normalize_attributes(self._attr_extra_state_attributes))

        last_charge_state = self._coordinator.update_charge_tracking()
        self._attr_native_value = last_charge_state["native_value"]
        self._coordinator._sensors[self._key] = self._attr_native_value
        self._attr_extra_state_attributes = self._format_attributes(last_charge_state["attributes"])


class StellantisChargeMetricSensor(StellantisRestoreSensor):
    def coordinator_update(self):
        last_charge_state = self._coordinator.get_last_charge_state()
        if last_charge_state["native_value"] is None and not last_charge_state["attributes"]:
            return

        self._coordinator.update_charge_tracking()
        self._attr_native_value = self._coordinator._sensors.get(self._key)


class StellantisChargeCostSensor(StellantisChargeMetricSensor):
    def coordinator_update(self):
        self._attr_native_unit_of_measurement = self._coordinator.currency_code
        super().coordinator_update()
