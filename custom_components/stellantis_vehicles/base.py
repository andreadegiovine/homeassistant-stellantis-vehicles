import logging
import re
from datetime import datetime, timedelta
import pytz

from homeassistant.helpers.update_coordinator import ( CoordinatorEntity, DataUpdateCoordinator )
from homeassistant.components.device_tracker import ( SourceType, TrackerEntity )
from homeassistant.components.sensor import ( RestoreSensor, SensorStateClass, SensorDeviceClass )
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_time

from .const import (
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)

class StellantisVehicleCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, config, vehicle, stellantis):
        super().__init__(hass, _LOGGER, name = DOMAIN, update_interval=timedelta(seconds=30))

        self._hass = hass
        self._config = config
        self._vehicle = vehicle
        self._stellantis = stellantis
        self._data = {}
        self._pending_action_id = None
        self._actions_status = {}
        self._actions_status_retry = 0

    async def _async_update_data(self):
        _LOGGER.debug("---------- START _async_update_data")
        try:
            # Vehicle status
            self._data = await self._stellantis.get_vehicle_status()
            # Vehicle callback
            await self._stellantis.get_callback_id()
        except Exception as e:
            _LOGGER.error(str(e))
        _LOGGER.debug(self._config)
        _LOGGER.debug(self._data)
        _LOGGER.debug("---------- END _async_update_data")

    async def set_action_status(self, name, action_id, status, detail = None):
        if not self._pending_action_id:
            return
        new_status = f"{name} {status}"
        if detail:
            new_status = new_status + f" ({detail})"
        old_actions = self._actions_status
        self._actions_status = {datetime.now(): new_status}
        self._actions_status.update(old_actions)
        self._pending_action_id = None
        self._actions_status_retry = 0
        self.async_update_listeners()
#         async self.async_request_refresh()

    async def get_action_status(self, now = None):
        if not self._pending_action_id:
            return

        try:
            action_status_request = await self._stellantis.get_action_status(self._pending_action_id)
        except Exception as e:
            _LOGGER.error(str(e))
            if self._actions_status_retry > 3:
                _LOGGER.debug("Max retry")
                await self.set_action_status("Unknown", self._pending_action_id, "max fetch retry")
                return
            else:
                self._actions_status_retry = self._actions_status_retry + 1
                _LOGGER.debug(f"Current retry {self._actions_status_retry}")
                async_track_point_in_time(self._hass, self.get_action_status, (datetime.now() + timedelta(seconds=20)))
                return

        name = action_status_request["type"]
        status = action_status_request["status"]
        detail = None
        if "failureCause" in action_status_request:
            detail = action_status_request["failureCause"]
        await self.set_action_status(name, self._pending_action_id, status, detail)

    async def send_command(self, name, data):
        if not self._pending_action_id:
            json = {
                name: data
            }
            try:
                command_request = await self._stellantis.send_command(json)
            except Exception as e:
                _LOGGER.error(str(e))
                return

            self._pending_action_id = command_request["remoteActionId"]
            async_track_point_in_time(self._hass, self.get_action_status, (datetime.now() + timedelta(seconds=10)))
        self.async_update_listeners()
#         async self.async_request_refresh()



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
            "manufacturer": self._config["mobile_app"]
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
            return int(self._coordinator._data["lastPosition"]["properties"]["heading"])
        return 0

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
    def __init__(self, coordinator, description, data_map = []):
        super().__init__(coordinator, description)

        self._data_map = data_map

    def timestring_to_datetime(self, timestring, sum_to_now = False):
        regex = 'PT'
        if timestring.find("H"):
            regex = regex + "%HH"
        if timestring.find("M"):
            regex = regex + "%MM"
        if timestring.find("S"):
            regex = regex + "%SS"
        try:
            date = datetime.strptime(timestring,regex)
            if sum_to_now:
                return datetime.now().astimezone(pytz.timezone('Europe/Rome')) + timedelta(hours=date.hour, minutes=date.minute)
            else:
                today = datetime.now().astimezone(pytz.timezone('Europe/Rome')).replace(hour=date.hour, minute=date.minute, second=0, microsecond=0)
                tomorrow = (today + timedelta(days=1)).replace(hour=date.hour, minute=date.minute, second=0, microsecond=0)
                if today < datetime.now().astimezone(pytz.timezone('Europe/Rome')):
                    return tomorrow
                else:
                    return today
        except Exception as e:
            return None

    def coordinator_update(self):
        value = self.get_value_from_map(self._data_map)
        if value == None:
            if self._attr_native_value == "unknown":
                self._attr_native_value = None
            return

        if self._key in ["battery_charging_time", "battery_charging_end"]:
            value = self.timestring_to_datetime(value, self._key == "battery_charging_end")

        self._attr_native_value = value


class StellantisBaseBinarySensor(StellantisBaseEntity, BinarySensorEntity):
    def __init__(self, coordinator, description, data_map = [], on_value = None):
        super().__init__(coordinator, description)

        self._data_map = data_map
        self._on_value = on_value

        self._attr_device_class = description.device_class

        self.coordinator_update()

    def coordinator_update(self):
        value = self.get_value_from_map(self._data_map)
        if value == None:
            return
        self._attr_is_on = value == self._on_value


class StellantisBaseButton(StellantisBaseEntity, ButtonEntity):
    @property
    def available(self):
        return not self._coordinator._pending_action_id

    async def async_press(self):
        raise NotImplementedError

    def coordinator_update(self):
        return True