import logging
import re
from datetime import datetime, timedelta

from homeassistant.helpers.update_coordinator import ( CoordinatorEntity, DataUpdateCoordinator )
from homeassistant.components.device_tracker import ( SourceType, TrackerEntity )
from homeassistant.components.sensor import RestoreSensor
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_point_in_time

from .utils import ( date_from_pt_string, get_datetime, timestring_to_datetime )

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)

class StellantisVehicleCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, config, vehicle, stellantis, translations):
        super().__init__(hass, _LOGGER, name = DOMAIN, update_interval=timedelta(seconds=30))

        self._hass = hass
        self._translations = translations
        self._config = config
        self._vehicle = vehicle
        self._stellantis = stellantis
        self._data = {}
        self._sensors = {}
        self._commands_history = {}
        self._disabled_commands = []
        self._get_trip_scheduled = False
        self._last_trip = None

    async def _async_update_data(self):
        _LOGGER.debug("---------- START _async_update_data")
        try:
            # Vehicle status
            self._data = await self._stellantis.get_vehicle_status()
        except Exception as e:
            _LOGGER.error(str(e))
        _LOGGER.debug(self._config)
        _LOGGER.debug(self._data)
        _LOGGER.debug("---------- END _async_update_data")

        await self.after_async_update_data(self._data)
        await self.get_trip_scheduled()

    @property
    def vehicle_type(self):
        return self._stellantis.get_config("type")

    @property
    def command_history(self):
        history = {}
        if not self._commands_history:
            return history
        reorder_actions = list(reversed(self._commands_history.keys()))
        for action_id in reorder_actions:
            action_name = self._commands_history[action_id]["name"]
            action_updates = self._commands_history[action_id]["updates"]
            reorder_updates = reversed(action_updates)
            for update in reorder_updates:
                status = update["info"]["status"]
                translation_path = f"component.stellantis_vehicles.entity.sensor.command_status.state.{status}"
                status = self._translations.get(translation_path, status)

                details = update["info"]["details"]
                if details:
                    translation_path = f"component.stellantis_vehicles.entity.sensor.command_status.state.{details}"
                    details = self._translations.get(translation_path, details)
                    status = status + " (" + details + ")"

                if "source" in update["info"]:
                    status = status + " [" + str(update["info"]["source"]) + "]"
                history.update({update["date"].strftime("%d/%m/%y %H:%M:%S:%f")[:-4]: str(action_name) + ": " + status})

        return history

    @property
    def pending_action(self):
        if not self._commands_history:
            return False
        last_action_id = list(self._commands_history.keys())[-1]
        return not self._commands_history[last_action_id]["updates"]

    async def update_command_history(self, action_id, update = None, retry = None):
        if not action_id in self._commands_history:
            return
        if update:
            self._commands_history[action_id]["updates"].append({"info": update, "date": get_datetime()})
            if update["status"] == "99":
                self._disabled_commands.append(self._commands_history[action_id]["name"])
        self.async_update_listeners()

    async def send_command(self, name, service, message):
        action_id = await self._stellantis.send_mqtt_message(service, message)
        self._commands_history.update({action_id: {"name": name, "updates": [], "retry": 0}})

    async def send_wakeup_command(self, button_name):
        await self.send_command(button_name, "/VehCharge/state", {"action": "state"})

    async def send_doors_command(self, button_name):
        current_status = self._sensors["doors"]
        new_status = "unlock"
        if current_status == "Deactive":
            new_status = "lock"
        await self.send_command(button_name, "/Doors", {"action": new_status})

    async def send_horn_command(self, button_name):
        await self.send_command(button_name, "/Horn", {"nb_horn": "2", "action": "activate"})

    async def send_lights_command(self, button_name):
        await self.send_command(button_name, "/Lights", {"duration": "10", "action": "activate"})

    async def send_charge_command(self, button_name):
        current_hour = self._data["energies"][0]["extension"]["electric"]["charging"]["nextDelayedTime"]
        date = date_from_pt_string(current_hour)
        current_status = self._sensors["battery_charging"]
        charge_type = "immediate"
        if current_status == "InProgress":
            charge_type = "delayed"
        await self.send_command(button_name, "/VehCharge", {"program": {"hour": date.hour, "minute": date.minute}, "type": charge_type})

    def get_programs(self):
        default_programs = {
           "program1": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program2": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program3": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program4": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0}
        }
        active_programs = None
        if "programs" in self._data["preconditionning"]["airConditioning"]:
            current_programs = self._data["preconditionning"]["airConditioning"]["programs"]
            for program in current_programs:
                if "occurence" in program and "day" in program["occurence"]:
                    date = date_from_pt_string(program["start"])
                    config = {
                        "day": [
                            int("Mon" in program["occurence"]["day"]),
                            int("Tue" in program["occurence"]["day"]),
                            int("Wed" in program["occurence"]["day"]),
                            int("Thu" in program["occurence"]["day"]),
                            int("Fri" in program["occurence"]["day"]),
                            int("Sat" in program["occurence"]["day"]),
                            int("Sun" in program["occurence"]["day"])
                        ],
                        "hour": date.hour,
                        "minute": date.minute,
                        "on": int(program["enabled"])
                    }
                    default_programs["program"+str(program["slot"])] = config
        return default_programs

    async def send_air_conditioning_command(self, button_name):
        current_status = self._sensors["air_conditioning"]
        new_status = "activate"
        if current_status == "Enabled":
            new_status = "deactivate"
        await self.send_command(button_name, "/ThermalPrecond", {"asap": new_status, "programs": self.get_programs()})

    async def after_async_update_data(self, data):
        if not hasattr(self, "_manage_charge_limit_sent"):
            self._manage_charge_limit_sent = False

        if self.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            if "battery_charging" in self._sensors:
                if self._sensors["battery_charging"] == "InProgress" and not self._manage_charge_limit_sent:
                    charge_limit_on = "switch_battery_charging_limit" in self._sensors and self._sensors["switch_battery_charging_limit"]
                    charge_limit = None
                    if "number_battery_charging_limit" in self._sensors and self._sensors["number_battery_charging_limit"]:
                        charge_limit = self._sensors["number_battery_charging_limit"]
                    if charge_limit_on and charge_limit and "battery" in self._sensors:
                        current_battery = self._sensors["battery"]
                        if int(float(current_battery)) >= int(float(charge_limit)):
                            button_name = self._translations.get("component.stellantis_vehicles.entity.button.charge_start_stop.name")
                            await self.send_charge_command(button_name)
                            self._manage_charge_limit_sent = True
                elif self._sensors["battery_charging"] != "InProgress" and not self._manage_charge_limit_sent:
                    self._manage_charge_limit_sent = False

    async def get_trip_scheduled(self, now=None):
        if self._get_trip_scheduled:
            self._get_trip_scheduled()
            self._get_trip_scheduled = False
            trips = await self._stellantis.get_vehicle_trips()
            if "_embedded" in trips and "trips" in trips["_embedded"] and trips["_embedded"]["trips"]:
                if not self._last_trip or self._last_trip["id"] != trips["_embedded"]["trips"][-1]["id"]:
                    self._last_trip = trips["_embedded"]["trips"][-1]

        next_run = get_datetime() + timedelta(minutes=2)
        self._get_trip_scheduled = async_track_point_in_time(self._hass, self.get_trip_scheduled, next_run)


class StellantisBaseEntity(CoordinatorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator)

        self._coordinator = coordinator
        self._hass = self._coordinator._hass
        self._config = self._coordinator._config
        self._vehicle = self._coordinator._vehicle
        self._stellantis = self._coordinator._stellantis
        self._data = {}

        self._key                   = description.key

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
        return {
            "identifiers": {
                (DOMAIN, self._vehicle["vin"], self._vehicle["type"])
            },
            "name": self._vehicle["vin"],
            "model": self._vehicle["type"] + " - " + self._vehicle["vin"],
            "manufacturer": self._config[FIELD_MOBILE_APP]
        }

    def get_value_from_map(self, data_map):
        vehicle_data = self._coordinator._data
        value = None
        updated_at = None
        for key in data_map:
            # Get last available node date
            if value and "createdAt" in value:
                updated_at = value["createdAt"]

            if not value and key in vehicle_data:
                value = vehicle_data[key]
            elif value and isinstance(key, int):
                value = value[key]
            elif value and key in value:
                value = value[key]

        if value and not isinstance(value, (float, int, str, bool)):
            value = None

        if value and updated_at:
            self._attr_extra_state_attributes["updated_at"] = updated_at

        return value

    @callback
    def _handle_coordinator_update(self):
        if self._coordinator.data is False:
            return
        self.coordinator_update()
        self.async_write_ha_state()

    def coordinator_update(self):
        raise NotImplementedError


class StellantisBaseDevice(StellantisBaseEntity, TrackerEntity):
    @property
    def entity_picture(self):
        return str(self._coordinator._vehicle["picture"])

    @property
    def force_update(self):
        return False

    @property
    def battery_level(self):
        if "energy" in self._coordinator._data:
            return int(self._coordinator._data["energy"][0]["level"])
        return None

    @property
    def latitude(self):
        if "lastPosition" in self._coordinator._data:
            return float(self._coordinator._data["lastPosition"]["geometry"]["coordinates"][1])
        return None

    @property
    def longitude(self):
        if "lastPosition" in self._coordinator._data:
            return float(self._coordinator._data["lastPosition"]["geometry"]["coordinates"][0])
        return None

    @property
    def location_accuracy(self):
        if "lastPosition" in self._coordinator._data:
            return 20
        return None

    @property
    def source_type(self):
        return SourceType.GPS

    def coordinator_update(self):
        return True


class StellantisRestoreSensor(StellantisBaseEntity, RestoreSensor):
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored_data = await self.async_get_last_state()
        if restored_data and restored_data.state not in ["unavailable", "unknown"]:
            value = restored_data.state
            if self._key in ["battery_charging_time", "battery_charging_end"]:
                value = datetime.fromisoformat(value)
            self._attr_native_value = value
            for key in restored_data.attributes:
                if isinstance(restored_data.attributes[key], (int, float)):
                    self._attr_extra_state_attributes[key] = restored_data.attributes[key]
        self.coordinator_update()

    def coordinator_update(self):
        return True


class StellantisBaseSensor(StellantisRestoreSensor):
    def __init__(self, coordinator, description, data_map = [], available = None):
        super().__init__(coordinator, description)

        self._data_map = data_map
        if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID and self._data_map[0] == "energies" and self._data_map[1] == 0 and not self._key.startswith("fuel"):
            self._data_map[1] = 1

        self._available = available

    @property
    def available(self):
        result = True
        if not self._available:
            return result
        for key in self._available:
            if result and key in self._coordinator._sensors:
                result = self._available[key] == self._coordinator._sensors[key]
        return result

    def coordinator_update(self):
        value = self.get_value_from_map(self._data_map)
        self._coordinator._sensors[self._key] = value

        if value == None:
            if self._attr_native_value == "unknown":
                self._attr_native_value = None
            return

        if self._key == "fuel_consumption_total":
            value = float(value)/100

        if self._key in ["battery_charging_time", "battery_charging_end"]:
            value = timestring_to_datetime(value, self._key == "battery_charging_end")
            if self._key == "battery_charging_end":
                charge_limit_on = "switch_battery_charging_limit" in self._coordinator._sensors and self._coordinator._sensors["switch_battery_charging_limit"]
                charge_limit = None
                if "number_battery_charging_limit" in self._coordinator._sensors and self._coordinator._sensors["number_battery_charging_limit"]:
                    charge_limit = self._coordinator._sensors["number_battery_charging_limit"]
                if charge_limit_on and charge_limit:
                    current_battery = self._coordinator._sensors["battery"]
                    now_timestamp = datetime.timestamp(get_datetime())
                    value_timestamp = datetime.timestamp(value)
                    diff = value_timestamp - now_timestamp
                    limit_diff = (diff / (100 - int(float(current_battery)))) * (int(float(charge_limit)) - int(float(current_battery)))
                    value = get_datetime(datetime.fromtimestamp((now_timestamp + limit_diff)))

        if self._key in ["battery_capacity", "battery_residual"]:
            if int(value) < 1:
                value = None
            else:
                value = (float(value) / 1000) + 10

        self._attr_native_value = value


class StellantisBaseBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def __init__(self, coordinator, description, data_map = [], on_value = None):
        super().__init__(coordinator, description)

        self._data_map = data_map
        if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID and self._data_map[0] == "energies" and self._data_map[1] == 0:
            self._data_map[1] = 1

        self._on_value = on_value

        self._attr_device_class = description.device_class

        self.coordinator_update()

    def coordinator_update(self):
        value = self.get_value_from_map(self._data_map)
        self._coordinator._sensors[self._key] = value
        if value == None:
            return
        self._attr_is_on = value == self._on_value


class StellantisBaseButton(StellantisBaseEntity, ButtonEntity):
    @property
    def available(self):
        engine_is_off = "engine" in self._coordinator._sensors and self._coordinator._sensors["engine"] == "Stop"
        return engine_is_off and (self.name not in self._coordinator._disabled_commands) and not self._coordinator.pending_action

    async def async_press(self):
        raise NotImplementedError

    def coordinator_update(self):
        return True


class StellantisRestoreEntity(StellantisBaseEntity, RestoreEntity):
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        restored_data = await self.async_get_last_state()
        if restored_data and restored_data.state not in ["unavailable", "unknown"]:
            value = restored_data.state
            if restored_data.state == "on":
                value = True
            elif restored_data.state == "off":
                value = False
            self._coordinator._sensors[self._sensor_key] = value
        self.coordinator_update()

    def coordinator_update(self):
        return True


class StellantisBaseNumber(StellantisRestoreEntity, NumberEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description)
        self._sensor_key = f"number_{self._key}"

    @property
    def native_value(self):
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors[self._sensor_key]
        return None

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = value
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        return True

class StellantisBaseSwitch(StellantisRestoreEntity, SwitchEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description)
        self._sensor_key = f"switch_{self._key}"

    @property
    def is_on(self):
        return self._sensor_key in self._coordinator._sensors and self._coordinator._sensors[self._sensor_key]

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self._coordinator._sensors[self._sensor_key] = True
        await self._coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self._coordinator._sensors[self._sensor_key] = False
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        return True