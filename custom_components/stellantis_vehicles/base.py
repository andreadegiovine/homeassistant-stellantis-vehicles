import logging
import re
from datetime import datetime

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.device_tracker import ( SourceType, TrackerEntity )
from homeassistant.components.sensor import RestoreSensor, SensorEntityDescription
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import ( STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_ON, STATE_OFF )

from .utils import ( get_datetime, timestring_to_datetime )

from .const import (
    DOMAIN,
    FIELD_MOBILE_APP,
    VEHICLE_TYPE_HYBRID,
)

from .stellantis import StellantisVehicleCoordinator

_LOGGER = logging.getLogger(__name__)

class StellantisBaseEntity(CoordinatorEntity):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator,
            description: SensorEntityDescription
        ):
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

        if value and not isinstance(value, (float, int, str, bool, list)):
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
        if "picture" in self._coordinator._vehicle:
            return str(self._coordinator._vehicle["picture"])
        return None

    @property
    def force_update(self):
        return False

    @property
    def battery_level(self):
        if "battery" in self._coordinator._sensors and self._coordinator._sensors["battery"]:
            return int(self._coordinator._sensors["battery"])
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
            return 10
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
        if restored_data and restored_data.state not in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            value = restored_data.state
            if self._key in ["battery_charging_time", "battery_charging_end"]:
                value = datetime.fromisoformat(value)
            self._attr_native_value = value
            self._coordinator._sensors[self._key] = value
            for key in restored_data.attributes:
                self._attr_extra_state_attributes[key] = restored_data.attributes[key]
        self.coordinator_update()

    def coordinator_update(self):
        return True


class StellantisBaseSensor(StellantisRestoreSensor):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator,
            description: SensorEntityDescription,
            data_map = [],
            available = None
        ):
        super().__init__(coordinator, description)

        self._data_map = data_map
        if self._coordinator.vehicle_type == VEHICLE_TYPE_HYBRID:
            if self._data_map[0] == "energies" and self._data_map[1] == 0 and not self._key.startswith("fuel"):
                self._data_map[1] = 1
            if self._key == "battery_soh":
                self._data_map[6] = "capacity"


        self._available = available

    @property
    def available(self):
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
                        result = self._coordinator._sensors[key] in rule[key]
                    else:
                        result = rule[key] == self._coordinator._sensors[key]
        return result

    def coordinator_update(self):
        value = self.get_value_from_map(self._data_map)
        if value or (self._key not in self._coordinator._sensors):
            self._coordinator._sensors[self._key] = value

        if value is None:
            if self._attr_native_value == STATE_UNKNOWN:
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
                    limit_diff = (diff / (100 - int(float(current_battery)))) * (int(charge_limit) - int(float(current_battery)))
                    value = get_datetime(datetime.fromtimestamp((now_timestamp + limit_diff)))
            self._coordinator._sensors[self._key] = value

        if self._key in ["battery_capacity", "battery_residual"]:
            if int(value) < 1:
                value = None
            else:
                value = (float(value) / 1000) + 10

        if isinstance(value, str):
            value = value.lower()

        self._attr_native_value = value


class StellantisBaseBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator,
            description: SensorEntityDescription,
            data_map = [],
            on_value = None
        ):
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
        if value is None:
            return
        elif isinstance(value, list):
            self._attr_is_on = self._on_value in value
        else:
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
        if restored_data and restored_data.state not in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            value = restored_data.state
            if restored_data.state == STATE_ON:
                value = True
            elif restored_data.state == STATE_OFF:
                value = False
            elif self._sensor_key.startswith("number_"):
                value = float(value)
            self._coordinator._sensors[self._sensor_key] = value
        self.coordinator_update()

    def coordinator_update(self):
        return True


class StellantisBaseNumber(StellantisRestoreEntity, NumberEntity):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator,
            description: SensorEntityDescription,
            default_value = None
        ):
        super().__init__(coordinator, description)
        self._sensor_key = f"number_{self._key}"
        self._default_value = None
        if default_value:
            self._default_value = float(default_value)

    @property
    def native_value(self):
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors[self._sensor_key]
        return self._default_value

    async def async_set_native_value(self, value: float):
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = float(value)
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        return True


class StellantisBaseSwitch(StellantisRestoreEntity, SwitchEntity):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator, 
            description: SensorEntityDescription
        ):
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


class StellantisBaseText(StellantisRestoreEntity, TextEntity):
    def __init__(
            self,
            coordinator: StellantisVehicleCoordinator,
            description: SensorEntityDescription
        ):
        super().__init__(coordinator, description)
        self._sensor_key = f"text_{self._key}"

    @property
    def native_value(self):
        if self._sensor_key in self._coordinator._sensors:
            return self._coordinator._sensors[self._sensor_key]
        return ""

    async def async_set_value(self, value: str):
        self._attr_native_value = value
        self._coordinator._sensors[self._sensor_key] = str(value)
        await self._coordinator.async_refresh()

    def coordinator_update(self):
        return True