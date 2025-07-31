import logging
import re
from datetime import datetime, timedelta, UTC
import json
from copy import deepcopy

from homeassistant.helpers.update_coordinator import ( CoordinatorEntity, DataUpdateCoordinator )
from homeassistant.components.device_tracker import ( SourceType, TrackerEntity )
from homeassistant.components.sensor import RestoreSensor
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.components.time import TimeEntity
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import ( STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_ON, STATE_OFF )
from homeassistant.exceptions import ConfigEntryAuthFailed

from .utils import ( time_from_pt_string, get_datetime, date_from_pt_string, datetime_from_isoformat, time_from_string )

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID,
    UPDATE_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

class StellantisVehicleCoordinator(DataUpdateCoordinator):
    def __init__(self, hass:HomeAssistant, config, vehicle, stellantis, translations) -> None:
        super().__init__(hass, _LOGGER, name = DOMAIN, update_interval=timedelta(seconds=UPDATE_INTERVAL))

        self._hass = hass
        self._translations = translations
        self._config = config
        self._vehicle = vehicle
        self._stellantis = stellantis
        self._data = {}
        self._sensors = {}
        self._commands_history = {}
        self._disabled_commands = []
        self._last_trip = None
#        self._total_trip = None

    async def _async_update_data(self):
        """ Update vehicle data from Stellantis. """
        _LOGGER.debug("---------- START _async_update_data")
        try:
            # Update token
            await self._stellantis.refresh_token()
            # Vehicle status
            self._data = await self._stellantis.get_vehicle_status(self._vehicle)
        except ConfigEntryAuthFailed as e:
            _LOGGER.error("Authentication failed while updating data for vehicle '%s': %s", self._vehicle['vin'], str(e))
            raise
        except Exception as e:
            _LOGGER.error(str(e))
        _LOGGER.debug(self._config)
        _LOGGER.debug(self._data)
        await self.after_async_update_data()
        _LOGGER.debug("---------- END _async_update_data")

    def get_translation(self, path, default = None):
        """ Get translation from path. """
        return self._translations.get(path, default)

    @property
    def vehicle_type(self):
        """ Vehicle type. """
        return self._vehicle["type"]

    @property
    def command_history(self):
        """ Commands history. """
        history = {}
        if not self._commands_history:
            return history
        reorder_actions = list(reversed(self._commands_history.keys()))
        for action_id in reorder_actions:
            action_name = self._commands_history[action_id]["name"]
            action_updates = self._commands_history[action_id]["updates"]
            reorder_updates = reversed(action_updates)
            for update in reorder_updates:
                status = update["info"]
                translation_path = f"component.stellantis_vehicles.entity.sensor.command_status.state.{status}"
                status = self.get_translation(translation_path, status)
                history.update({update["date"].strftime("%d/%m/%y %H:%M:%S:%f")[:-4]: str(action_name) + ": " + status})
        return history

    @property
    def pending_action(self):
        """ Pending action. """
        if not self._commands_history:
            return False
        last_action_id = list(self._commands_history.keys())[-1]
        return not self._commands_history[last_action_id]["updates"]

    async def update_command_history(self, action_id, update = None):
        """ Update command history. """
        if action_id not in self._commands_history:
            return
        if update:
            self._commands_history[action_id]["updates"].append({"info": update, "date": get_datetime()})
            if update == "99":
                self._disabled_commands.append(self._commands_history[action_id]["name"])
        self.async_update_listeners()

    async def send_command(self, name, service, message):
        """ Send a command to the vehicle. """
        try:
            action_id = await self._stellantis.send_mqtt_message(service, message, self._vehicle)
            self._commands_history.update({action_id: {"name": name, "updates": []}})
        except ConfigEntryAuthFailed as e:
            _LOGGER.error("Authentication failed while sending command '%s' to vehicle '%s': %s", name, self._vehicle['vin'], str(e))
            self._stellantis._entry.async_start_reauth(self._hass)
        except Exception as e:
            _LOGGER.error("Failed to send command %s: %s", name, str(e))
            raise

    async def send_wakeup_command(self, button_name):
        """ Send wakeup command to the vehicle. """
        await self.send_command(button_name, "/VehCharge/state", {"action": "state"})

    async def send_doors_command(self, button_name, action):
        """ Send doors command to the vehicle. """
        await self.send_command(button_name, "/Doors", {"action": action})

    async def send_horn_command(self, button_name):
        """ Send horn command to the vehicle. """
        await self.send_command(button_name, "/Horn", {"nb_horn": "2", "action": "activate"})

    async def send_lights_command(self, button_name):
        """ Send lights command to the vehicle. """
        await self.send_command(button_name, "/Lights", {"duration": "10", "action": "activate"})

    async def send_charge_command(self, button_name, update_only_time = False, action = "immediate"):
        """ Send charge command to the vehicle. """
        current_hour = self._sensors.get("time_battery_charging_start")
        if update_only_time:
            current_status = self._sensors.get("battery_charging")
            if current_status != "InProgress":
                    action = "delayed"
        await self.send_command(button_name, "/VehCharge", {"program": {"hour": current_hour.hour, "minute": current_hour.minute}, "type": action})

    def get_programs(self):
        """ Get current preconditioning programs. """
        default_programs = {
           "program1": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program2": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program3": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program4": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0}
        }
        active_programs = None
        if "programs" in self._data["preconditionning"]["airConditioning"]:
            current_programs = self._data["preconditionning"]["airConditioning"]["programs"]
            if current_programs:
                for program in current_programs:
                    if program:
                        occurence = program.get("occurence")
                        if occurence and occurence.get("day") and program.get("start"):
                            date = time_from_pt_string(program["start"])
                            config = {
                                "day": [
                                    int("Mon" in occurence["day"]),
                                    int("Tue" in occurence["day"]),
                                    int("Wed" in occurence["day"]),
                                    int("Thu" in occurence["day"]),
                                    int("Fri" in occurence["day"]),
                                    int("Sat" in occurence["day"]),
                                    int("Sun" in occurence["day"])
                                ],
                                "hour": date.hour,
                                "minute": date.minute,
                                "on": int(program["enabled"])
                            }
                            default_programs["program" + str(program["slot"])] = config
        return default_programs

    async def send_preconditioning_command(self, button_name, action):
        """ Send preconditioning command to the vehicle. """
        await self.send_command(button_name, "/ThermalPrecond", {"asap": action, "programs": self.get_programs()})

    async def send_abrp_data(self):
        """ Send vehicle data to ABRP. """
        tlm = {
            "utc": int(get_datetime().astimezone(UTC).timestamp()),
            "soc": None,
            "power": None,
            "speed": None,
            "lat": None,
            "lon": None,
            "is_charging": False,
            "is_dcfc": False,
            "is_parked": False
        }

        if self._sensors.get("battery"):
            tlm["soc"] = self._sensors.get("battery")
        if self._sensors.get("speed"):
            tlm["speed"] = self._sensors.get("speed")
        if self._data.get("lastPosition"):
            tlm["lat"] = float(self._data["lastPosition"]["geometry"]["coordinates"][1])
            tlm["lon"] = float(self._data["lastPosition"]["geometry"]["coordinates"][0])
        if self._sensors.get("battery_charging"):
            tlm["is_charging"] = self._sensors.get("battery_charging") == "InProgress"
        if self._sensors.get("battery_charging_type"):
            tlm["is_dcfc"] = tlm["is_charging"] and self._sensors.get("battery_charging_type") == "Quick"
        if self._sensors.get("battery_soh"):
            tlm["soh"] = float(self._sensors.get("battery_soh"))
        if self._data.get("lastPosition", {}).get("properties", {}).get("heading"):
            tlm["heading"] = float(self._data.get("lastPosition").get("properties").get("heading"))
        if len(self._data.get("lastPosition", {}).get("geometry", {}).get("coordinates", [])) == 3:
            tlm["elevation"] = float(self._data.get("lastPosition").get("geometry").get("coordinates")[2])
        if self._sensors.get("temperature"):
            tlm["ext_temp"] = self._sensors.get("temperature")
        if self._sensors.get("mileage"):
            tlm["odometer"] = self._sensors.get("mileage")
        if self._sensors.get("autonomy"):
            tlm["est_battery_range"] = self._sensors.get("autonomy")

        params = {"tlm": json.dumps(tlm), "token": self._sensors.get("text_abrp_token")}
        await self._stellantis.send_abrp_data(params)


    async def after_async_update_data(self):
        """ Apply changes and do actions after vehicle data update. """
        if self.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            if not hasattr(self, "_manage_charge_limit_sent"):
                self._manage_charge_limit_sent = False

            if "battery_charging" in self._sensors:
                if self._sensors.get("battery_charging") == "InProgress" and not self._manage_charge_limit_sent:
                    charge_limit_on = self._sensors.get("switch_battery_charging_limit", False)
                    charge_limit = self._sensors.get("number_battery_charging_limit", None)
                    if charge_limit_on and charge_limit and "battery" in self._sensors:
                        current_battery = self._sensors.get("battery")
                        if int(float(current_battery)) >= int(charge_limit):
                            button_name = self.get_translation("component.stellantis_vehicles.entity.button.charge_stop.name")
                            await self.send_charge_command(button_name, False, "delayed")
                            self._manage_charge_limit_sent = True
                elif self._sensors.get("battery_charging") != "InProgress" and self._manage_charge_limit_sent:
                    self._manage_charge_limit_sent = False

            if "switch_abrp_sync" in self._sensors and self._sensors.get("switch_abrp_sync") and "text_abrp_token" in self._sensors and len(self._sensors.get("text_abrp_token")) == 36:
                await self.send_abrp_data()

        if "engine" in self._sensors and "ignition" in self._data and "type" in self._data["ignition"]:
            current_engine_status = self._sensors.get("engine")
            new_engine_status = self._data["ignition"]["type"]
            if current_engine_status != "Stop" and new_engine_status == "Stop":
                await self.get_vehicle_last_trip()

        if "number_refresh_interval" in self._sensors and self._sensors.get("number_refresh_interval") > 0 and self._sensors.get("number_refresh_interval") != self._update_interval_seconds:
            self.update_interval = timedelta(seconds=self._sensors.get("number_refresh_interval"))
            self._stellantis._refresh_interval = self._sensors.get("number_refresh_interval")

    async def get_vehicle_last_trip(self):
        """ Get last trip from Stellantis. """
        trips = await self._stellantis.get_vehicle_last_trip(self._vehicle)
        if "_embedded" in trips and "trips" in trips["_embedded"] and trips["_embedded"]["trips"]:
            if not self._last_trip or self._last_trip["id"] != trips["_embedded"]["trips"][-1]["id"]:
                self._last_trip = trips["_embedded"]["trips"][-1]

#     def parse_trips_page_data(self, data):
#         result = []
#         if "_embedded" in data and "trips" in data["_embedded"] and data["_embedded"]["trips"]:
#             for trip in data["_embedded"]["trips"]:
#                 item = {"engine": {}}
#                 if "startMileage" in trip:
#                     item["start_mileage"] = float(trip["startMileage"])
#                 if "energyConsumptions" in trip:
#                     for consuption in trip["energyConsumptions"]:
#                         if not "type" in consuption or not "consumption" in consuption or not "avgConsumption" in consuption:
#                             _LOGGER.error(consuption)
#                             continue
#                         trip_consumption = float(consuption["consumption"]) / 1000
#                         trip_avg_consumption = float(consuption["avgConsumption"]) / 1000
#                         if trip_consumption <= 0 or trip_avg_consumption <= 0:
#                             _LOGGER.error(consuption)
#                             continue
#                         trip_distance = trip_consumption / (trip_avg_consumption / 100)
#                         item["engine"][consuption["type"].lower()] = {
#                             "distance": trip_distance,
#                             "consumption": trip_consumption
#                         }
#                 else:
#                     continue
#                 if not item["engine"]:
#                     continue
#                 result.append(item)
#         return result
#
#     async def get_vehicle_trips(self):
#         vehicle_trips_request = await self._stellantis.get_vehicle_trips()
#         total_trips = int(vehicle_trips_request["total"])
#         next_page_url = vehicle_trips_request["_links"]["next"]["href"]
#         pages = math.ceil(total_trips / 60) - 1
#         result = self.parse_trips_page_data(vehicle_trips_request)
#         if pages > 1:
#             for _ in range(pages):
#                 page_token = next_page_url.split("pageToken=")[1]
#                 page_trips_request = await self._stellantis.get_vehicle_trips(page_token)
#                 result = result + self.parse_trips_page_data(page_trips_request)
#                 if "next" in page_trips_request["_links"]:
#                     next_page_url = page_trips_request["_links"]["next"]["href"]
#         self._total_trip = {"totals": total_trips, "trips": result}

class StellantisBaseEntity(CoordinatorEntity):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator)

        self._coordinator = coordinator
        self._hass = self._coordinator._hass
        self._config = self._coordinator._config
        self._vehicle = self._coordinator._vehicle
        self._stellantis = self._coordinator._stellantis
        self._data = {}

        self._key = description.key

        key_formatted = re.sub(r'(?<!^)(?=[A-Z])', '_', self._key).lower()

        self.entity_description     = description
        self._attr_translation_key  = description.translation_key
        self._attr_has_entity_name  = True
        self._attr_unique_id        = self._vehicle["vin"] + "_" + key_formatted
        self._attr_extra_state_attributes = {}
        self._attr_suggested_unit_of_measurement = None
        self._attr_available = True

        if hasattr(description, "unit_of_measurement"):
            self._attr_native_unit_of_measurement = description.unit_of_measurement

        if hasattr(description, "device_class"):
            self._attr_device_class = description.device_class

        if hasattr(description, "state_class"):
            self._attr_state_class = description.state_class

        if hasattr(description, "entity_category"):
            self._attr_entity_category = description.entity_category

    @property
    def device_info(self):
        """ Core device info. """
        return {
            "identifiers": {
                (DOMAIN, self._vehicle["vin"], self._vehicle["type"])
            },
            "name": self._vehicle["vin"],
            "model": self._vehicle["type"] + " - " + self._vehicle["vin"],
            "manufacturer": self._config[FIELD_MOBILE_APP]
        }

    def update_maps_for_hybrid(self):
        """ Update value/updated_at map for hybrid vehicles. """
        if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID:
            if self._value_map[0] == "energies" and self._value_map[1] == 0 and not self._key.startswith("fuel"):
                self._value_map[1] = 1
                self._updated_at_map[1] = 1

            if self._key == "battery_soh":
                self._value_map[6] = "capacity"

    def value_was_updated(self):
        """ Check if value was changed. """
        current_value = self._coordinator._sensors.get(self._key)
        self.get_value(self._value_map)
        new_value = self._coordinator._sensors.get(self._key)
        return current_value != new_value

    def get_updated_at_from_map(self, updated_at_map):
        """ Get data updated_at from map. """
        vehicle_data = self._coordinator._data
        value = None
        for key in updated_at_map:
            if value is None: # first key in the map
                if key in vehicle_data:
                    value = vehicle_data[key]
            else: # following keys in the map (value has been set with result of previous key)
                if isinstance(key, int) or key in value: 
                    value = value[key]
                else: # value not an array and key not found in value
                    value = None
            if value is None: # Stop iteration immediately if None value encountered at this stage
                break

        # Two following lines may be useless...
        # if value and not isinstance(value, str):
        #     value = None

        return value

    def get_value_from_map(self, value_map):
        """ Get data value from map. """
        vehicle_data = self._coordinator._data
        value = None
        for key in value_map:
            if value is None: # first key in the map
                if key in vehicle_data:
                    value = vehicle_data[key]
            else: # following keys in the map (value has been set with result of previous key)
                if isinstance(key, int) or key in value: 
                    value = value[key]
                else: # value not an array and key not found in value
                    value = None
            if value is None: # Stop iteration immediately if None value encountered at this stage
                break

        # Two following lines may be useless...
        # if value and not isinstance(value, (float, int, str, bool, list)):
        #     value = None

        return value

    def get_value(self, value_map):
        """ Get entity value and convert to HASS style. """
        key = self._key
        if hasattr(self, '_sensor_key'):
            key = self._sensor_key

        value = self.get_value_from_map(value_map)

        if key == "mileage":
            if (not value or float(value) == 0) and self._coordinator._sensors.get('mileage') and float(self._coordinator._sensors.get('mileage')) > 0:
                value = self._coordinator._sensors.get('mileage')

        if value != None or key not in self._coordinator._sensors:
            self._coordinator._sensors[key] = value

        if value == None:
            return None

        if key == "fuel_consumption_total":
            value = float(value)/100

        if key in ["time_battery_charging_start", "battery_charging_end"]:
            if key == "time_battery_charging_start":
                value = time_from_pt_string(value)
                self._coordinator._sensors[key] = value
            if key == "battery_charging_end":
                new_updated_at = get_datetime()
                value = date_from_pt_string(value, new_updated_at)
                charge_limit_on = self._coordinator._sensors.get("switch_battery_charging_limit", False)
                charge_limit = self._coordinator._sensors.get("number_battery_charging_limit")
                current_battery = self._coordinator._sensors.get("battery")
                if charge_limit_on and charge_limit and int(float(current_battery)) < 100:
                    now_timestamp = datetime.timestamp(new_updated_at)
                    value_timestamp = datetime.timestamp(value)
                    diff = value_timestamp - now_timestamp
                    limit_diff = (diff / (100 - int(float(current_battery)))) * (int(charge_limit) - int(float(current_battery)))
                    value = get_datetime(datetime.fromtimestamp((now_timestamp + limit_diff)))

        if key in ["battery_capacity", "battery_residual"]:
            if int(value) < 1:
                value = None
            else:
                value = (float(value) / 1000) + 10

        if key in ["coolant_temperature", "oil_temperature", "air_temperature"]:
            value = float(value)

            # Convert to Celsius if reported in Fahrenheit
            country = self._coordinator._config.get("country_code", "").upper()
            fahrenheit_countries = {"US", "BS", "BZ", "KY", "PW", "FM", "MH", "GU", "MP", "AS", "VI", "LR", "MM", "GB"}  # Adjust this list if needed

            if country in fahrenheit_countries:
                value = (value - 32) * 5.0 / 9.0

        if isinstance(value, str):
            value = value.lower()

        return value

    @property
    def available_command(self):
        """ Base availability property for mqtt commands. """
        mqtt_is_connected = self._stellantis and self._stellantis._mqtt and self._stellantis._mqtt.is_connected()
        engine_is_off = "engine" in self._coordinator._sensors and self._coordinator._sensors.get("engine") == "Stop"
        command_is_enabled = self.name not in self._coordinator._disabled_commands
        return mqtt_is_connected and engine_is_off and command_is_enabled and not self._coordinator.pending_action

    @callback
    def _handle_coordinator_update(self):
        """ Coordinator handler. """
        if self._coordinator.data is False:
            return
        self.coordinator_update()
        self.async_write_ha_state()

    def coordinator_update(self):
        """ Actions on coordinator update. """
        raise NotImplementedError


class StellantisBaseDevice(StellantisBaseEntity, TrackerEntity):
    @property
    def entity_picture(self):
        """ Entity picture. """
        if "picture" in self._coordinator._vehicle:
            return str(self._coordinator._vehicle["picture"])
        return None

    @property
    def force_update(self):
        """ Force update. """
        return False

    @property
    def battery_level(self):
        """ Battery level. """
        if self._coordinator._sensors.get("battery"):
            return int(float(self._coordinator._sensors.get("battery")))
        elif self._coordinator._sensors.get("service_battery_voltage"):
            return int(float(self._coordinator._sensors.get("service_battery_voltage")))
        return None

    @property
    def latitude(self):
        """ Latitude. """
        if "lastPosition" in self._coordinator._data:
            return float(self._coordinator._data["lastPosition"]["geometry"]["coordinates"][1])
        return None

    @property
    def longitude(self):
        """ Longitude. """
        if "lastPosition" in self._coordinator._data:
            return float(self._coordinator._data["lastPosition"]["geometry"]["coordinates"][0])
        return None

    @property
    def location_accuracy(self):
        """ Location accuracy. """
        if "lastPosition" in self._coordinator._data:
            return 10
        return None

    @property
    def source_type(self):
        """ Source type. """
        return SourceType.GPS

    def coordinator_update(self):
        """ Coordinator update. """
        return True


class StellantisRestoreSensor(StellantisBaseEntity, RestoreSensor):
    async def async_added_to_hass(self):
        """ Restore entity data to HASS style on system restart. """
        await super().async_added_to_hass()
        restored_data = await self.async_get_last_state()
        if restored_data and restored_data.state not in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            value = restored_data.state
            if self._key == "battery_charging_end":
                value = datetime.fromisoformat(value)
            self._attr_native_value = value
            self._coordinator._sensors[self._key] = value
            for key in restored_data.attributes:
                self._attr_extra_state_attributes[key] = restored_data.attributes[key]
        self.coordinator_update()

    def coordinator_update(self):
        """ Coordinator update. """
        return True


class StellantisBaseSensor(StellantisRestoreSensor):
    def __init__(self, coordinator, description, value_map=None, updated_at_map=None, available=None) -> None:
        super().__init__(coordinator, description)

        if value_map is None:
            value_map = []
        if updated_at_map is None:
            updated_at_map = []

        self._value_map = deepcopy(value_map)
        self._updated_at_map = deepcopy(updated_at_map)

        self.update_maps_for_hybrid()

        self._available = available

    @property
    def available(self):
        """ Base availability rules. """
        result = True
        if not self._available:
            return result
        for rule in self._available:
            if not result:
                break
            for key in rule:
                if not result:
                    break
                if result and key in self._coordinator._sensors:
                    if isinstance(rule[key], list):
                        result = self._coordinator._sensors.get(key) in rule[key]
                    else:
                        result = rule[key] == self._coordinator._sensors.get(key)
        return result

    def coordinator_update(self):
        """ Coordinator update. """
        if self.value_was_updated():
            self._attr_extra_state_attributes["updated_at"] = self.get_updated_at_from_map(self._updated_at_map)
            self._attr_native_value = self.get_value(self._value_map)


class StellantisBaseBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def __init__(self, coordinator, description, value_map=None, updated_at_map=None, on_value=None) -> None:
        super().__init__(coordinator, description)

        if value_map is None:
            value_map = []
        if updated_at_map is None:
            updated_at_map = []

        self._value_map = deepcopy(value_map)
        self._updated_at_map = deepcopy(updated_at_map)

        self.update_maps_for_hybrid()

        self._on_value = on_value

        self._attr_device_class = description.device_class

        self.coordinator_update()

    def coordinator_update(self):
        """ Coordinator update. """
        if self.value_was_updated():
            self._attr_extra_state_attributes["updated_at"] = self.get_updated_at_from_map(self._updated_at_map)
            value = self.get_value(self._value_map)
            if value == None:
                return
            elif isinstance(value, list):
                self._attr_is_on = self._on_value in value
            else:
                self._attr_is_on = str(value).lower() == str(self._on_value).lower()


class StellantisBaseButton(StellantisBaseEntity, ButtonEntity):
    @property
    def available(self):
        """ Available. """
        return self.available_command

    async def async_press(self):
        """ Button press. """
        raise NotImplementedError

    def coordinator_update(self):
        """ Coordinator update. """
        return True


class StellantisBaseActionButton(StellantisBaseButton):
    def __init__(self, coordinator, description, action) -> None:
        super().__init__(coordinator, description)
        self._action = action


class StellantisRestoreEntity(StellantisBaseEntity, RestoreEntity):
    async def async_added_to_hass(self):
        """ Restore entity data to HASS style on system restart. """
        await super().async_added_to_hass()
        restored_data = await self.async_get_last_state()
        if restored_data and restored_data.state not in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            value = restored_data.state
            if restored_data.state == STATE_ON:
                value = True
            elif restored_data.state == STATE_OFF:
                value = False
            elif self._sensor_key.startswith("number_"):
                value = float(value)
            elif self._sensor_key.startswith("time_"):
                value = time_from_string(value)
            self._coordinator._sensors[self._sensor_key] = value
        self.coordinator_update()

    def coordinator_update(self):
        """ Coordinator update. """
        return True


class StellantisBaseNumber(StellantisRestoreEntity, NumberEntity):
    def __init__(self, coordinator, description, default_value = None) -> None:
        super().__init__(coordinator, description)
        self._sensor_key = f"number_{self._key}"
        self._default_value = None
        if default_value:
            self._default_value = float(default_value)

    @property
    def native_value(self):
        """ Native value. """
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors.get(self._sensor_key)
        if self._stellantis.get_stored_config(self._sensor_key):
            return self._stellantis.get_stored_config(self._sensor_key)
        return self._default_value

    async def async_set_native_value(self, value: float):
        """ Set native value. """
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = float(value)
        self._stellantis.update_stored_config(self._sensor_key, float(value))
        await self._coordinator.async_refresh()


class StellantisBaseSwitch(StellantisRestoreEntity, SwitchEntity):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._sensor_key = f"switch_{self._key}"

    @property
    def is_on(self):
        """ Is on. """
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors.get(self._sensor_key)
        if self._stellantis.get_stored_config(self._sensor_key):
            return self._stellantis.get_stored_config(self._sensor_key)
        return False

    async def async_turn_on(self, **kwargs):
        """ Turn on. """
        self._attr_is_on = True
        self._coordinator._sensors[self._sensor_key] = True
        self._stellantis.update_stored_config(self._sensor_key, True)
        await self._coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """ Turn off. """
        self._attr_is_on = False
        self._coordinator._sensors[self._sensor_key] = False
        self._stellantis.update_stored_config(self._sensor_key, False)
        await self._coordinator.async_refresh()


class StellantisBaseText(StellantisRestoreEntity, TextEntity):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._sensor_key = f"text_{self._key}"

    @property
    def native_value(self):
        """ Native value. """
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors.get(self._sensor_key)
        if self._stellantis.get_stored_config(self._sensor_key):
            return self._stellantis.get_stored_config(self._sensor_key)
        return ""

    async def async_set_value(self, value: str):
        """ Set value. """
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = str(value)
        self._stellantis.update_stored_config(self._sensor_key, str(value))
        await self._coordinator.async_refresh()


class StellantisBaseTime(StellantisRestoreEntity, TimeEntity):
    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._sensor_key = f"time_{self._key}"

    @property
    def native_value(self):
        """ Native value. """
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors.get(self._sensor_key)
        return None
