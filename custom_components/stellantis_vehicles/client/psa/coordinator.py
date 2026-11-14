"""Vehicle coordinator of the PSA client: MQTT live events, remote commands, trips."""
import asyncio
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any

from homeassistant.core import callback, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from ...base import StellantisVehicleCoordinator
from ...utils import ( time_from_pt_string, parse_timestamp, rate_limit, log_call, parse_vehicle_rights, SENSITIVE_DATA_FILTER )
from ...exceptions import CommunicationError, RateLimitException
from .mqtt_event import event_content

from ...const import (
    SUPPORTED_FEATURES_RETRY_DELAYS,
    VEHICLE_TYPE_ELECTRIC,
    VEHICLE_TYPE_HYBRID
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)

# Event fields overlaid onto the REST data, grouped by the REST section they
# update. Freshness is tracked per group (see _track_mqtt_changes), so every
# field _overlay_mqtt_state writes must be covered here.
_MQTT_OVERLAY_GROUPS = {
    "charging": lambda event: ((event.get("charging") or {}).get("hmi_state_code"), (event.get("charging") or {}).get("plugged")),
    "doors": lambda event: (event.get("doors") or {}).get("locking_state_code"),
    "preconditioning": lambda event: (event.get("preconditioning") or {}).get("status_code"),
    "door_opening": lambda event: (event.get("doors") or {}).get("open"),
}


class PsaVehicleCoordinator(StellantisVehicleCoordinator):
    def __init__(self, hass:HomeAssistant, config, vehicle, stellantis, translations, config_entry) -> None:
        super().__init__(hass, config, vehicle, stellantis, translations, config_entry)
        # Last accepted MQTT vehicle event (see apply_mqtt_event) and the
        # ordering/freshness state that goes with it.
        self._mqtt_state = {}
        self._mqtt_last_key = None
        self._mqtt_changed_at:dict[str, datetime | None] = {}
        self._manage_charge_limit_sent = False
        self._privacy_full_logged = False
        # Set once the maintenance endpoint has returned an empty result, so it
        # is not polled again for the lifetime of this coordinator (issue #623:
        # some vehicles 404 on every request and flooded the logs).
        self._maintenance_unsupported = False

    def diagnostics(self) -> dict[str, Any]:
        # Last accepted MQTT vehicle event, parsed (see parse_mqtt_event).
        return {"mqtt_state": self.mqtt_state}

    async def _fetch_vehicle_data(self) -> dict[str, Any] | None:
        """ Fetch the vehicle status and maintenance info. """
        new_data = await self._stellantis.get_vehicle_status(self._vehicle)
        if new_data:
            maintenance = {} if self._maintenance_unsupported else await self._stellantis.get_vehicle_maintenance(self._vehicle)
            if maintenance:
                new_data["maintenance"] = {
                    "mileageBeforeMaintenance": maintenance.get("mileageBeforeMaintenance"),
                    "daysBeforeMaintenance": maintenance.get("daysBeforeMaintenance"),
                    "updatedAt": maintenance.get("updatedAt")
                }
            elif not self._maintenance_unsupported:
                _LOGGER.debug("Vehicle maintenance data not found - disabling further maintenance polling")
                self._maintenance_unsupported = True
        return new_data

    def _on_status_received(self, new_data:dict[str, Any]) -> None:
        self._log_privacy_mode(new_data.get("privacy", {}).get("state"))

    def _prepare_new_data(self, new_data:dict[str, Any]) -> None:
        if self._mqtt_state:
            self._overlay_mqtt_state(new_data)

    async def _send_remote_command(self, service: str, message: dict[str, Any]) -> str | None:
        return await self._stellantis.send_mqtt_message(service, message, self._vehicle)

    async def after_async_update_data(self, new_data: dict[str, Any]) -> None:
        if self.vehicle_type in [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]:
            await self._auto_stop_charge_at_limit()
        await super().after_async_update_data(new_data)
        await self._fetch_last_trip_on_engine_stop(new_data)

    @log_call
    async def async_lookup_supported_features(self) -> None:
        """ Look up the remote services the vehicle's subscription covers.

        Only shown in the diagnostics for now, nothing depends on it yet, so a
        failure is logged and otherwise ignored. Communication errors are
        retried with a growing delay; an auth failure is not, as it is not
        raised inside setup or an update and so cannot start a reauth flow.
        """
        for delay in (*SUPPORTED_FEATURES_RETRY_DELAYS, None):
            try:
                response = await self._stellantis.get_vehicle_rights(self._vehicle)
            except ConfigEntryAuthFailed as err:
                _LOGGER.warning("Could not look up the vehicle's supported features: %s", err)
                return
            except (CommunicationError, RateLimitException) as err:
                if delay is None:
                    _LOGGER.warning("Could not look up the vehicle's supported features: %s", err)
                    return
                _LOGGER.debug("Supported features lookup failed, retrying in %s s: %s", delay, err)
                await asyncio.sleep(delay)
            else:
                self._supported_features = parse_vehicle_rights(response)
                _LOGGER.debug("Supported features: %s", self._supported_features)
                return

    def _log_privacy_mode(self, state):
        """ Log once when Stellantis private mode starts or stops pausing live data. """
        active = state == "Full"
        if active and not self._privacy_full_logged:
            self._privacy_full_logged = True
            _LOGGER.info("Private mode is enabled on vehicle %s, Stellantis has paused live data updates", self._vehicle["vin"])
        elif not active and self._privacy_full_logged:
            self._privacy_full_logged = False
            _LOGGER.info("Private mode is disabled on vehicle %s, live data updates resumed", self._vehicle["vin"])

    @property
    def mqtt_state(self) -> dict[str, Any]:
        """ Last accepted MQTT vehicle event (see parse_mqtt_event), or {} before the first one. """
        return self._mqtt_state

    @callback
    def apply_mqtt_event(self, event:dict[str, Any]) -> None:
        """ Apply a parsed MQTT vehicle event (see parse_mqtt_event).

        Events for a given VIN are not guaranteed to arrive in order, so
        older ones are discarded first. Only the fields in
        _MQTT_OVERLAY_GROUPS reach the entities (see _overlay_mqtt_state);
        battery level and range stay REST-only, as the MQTT values lag
        behind REST and spike (checked against a month of both).
        """
        if not self._accept_mqtt_event_order(event):
            return

        if event_content(event) == event_content(self._mqtt_state):
            # Nothing actually changed (a duplicate) - don't wake entities for it.
            return

        self._track_mqtt_changes(event)
        self._mqtt_state = event
        if self.data:
            data = deepcopy(self.data)
            self._overlay_mqtt_state(data)
            # Not async_set_updated_data(): that would reset the REST poll timer.
            self.data = data
        self.async_update_listeners()

    def _accept_mqtt_event_order(self, event:dict[str, Any]) -> bool:
        """ Reject an MQTT event older than the last one accepted for this vehicle.

        Ordering key is (timestamp, event_counter). event_counter resets to 1
        on a new session, but the newer timestamp already orders that
        correctly. Don't special-case counter 1: it is always the
        session-start snapshot (reason 0), which often arrives after the
        session's next events while still holding the older state. A missing
        or unparsable timestamp or a missing counter can't be placed in the
        sequence, so the event is accepted rather than silently dropped.
        """
        timestamp = parse_timestamp(event.get("timestamp"))
        counter = event.get("event_counter")
        if timestamp is None or counter is None:
            return True

        key = (timestamp, counter)
        if self._mqtt_last_key is not None and key < self._mqtt_last_key:
            _LOGGER.debug(
                "Discarding out-of-order MQTT event for %s (key %s < last accepted %s)",
                self._vehicle["vin"], key, self._mqtt_last_key,
            )
            return False

        self._mqtt_last_key = key
        return True

    def _track_mqtt_changes(self, event:dict[str, Any]) -> None:
        """ Record, per overlay group, when its values last changed via MQTT.

        Events repeat the last known values with a fresh timestamp (in real
        captures soc_batt stayed at a stale 58 for hours while REST already
        reported 53), so the event timestamp says nothing about how fresh a
        value is; only a change seen via MQTT does. The first event after
        startup has nothing to compare with, so its values are left to REST
        (None) until they change.
        """
        event_dt = parse_timestamp(event.get("timestamp"))
        for group, values in _MQTT_OVERLAY_GROUPS.items():
            if not self._mqtt_state:
                self._mqtt_changed_at[group] = None
            elif values(event) != values(self._mqtt_state):
                self._mqtt_changed_at[group] = event_dt

    def _overlay_mqtt_state(self, data:dict[str, Any]) -> None:
        """ Write the fields of the last accepted MQTT event into REST-shaped ``data``, in place.

        Entities keep reading ``coordinator.data`` via their value_map, so the
        event is translated into the REST vocabulary. Each group is only
        overwritten if it last changed via MQTT after that section's REST
        timestamp, so a later REST poll wins again. Fields without a
        confirmed mapping are left to REST.
        """
        event = self._mqtt_state

        electric = next((energy for energy in data.get("energies") or [] if energy.get("type") == "Electric"), None)
        if electric is not None and self._mqtt_is_newer("charging", electric.get("createdAt") or data.get("updatedAt")):
            event_charging = event.get("charging") or {}
            charging = electric.setdefault("extension", {}).setdefault("electric", {}).setdefault("charging", {})
            # hmi_state codes matched against REST status at the same
            # timestamp; REST reports plugged-but-idle as Disconnected too.
            # 2 and 4 (seen around charge start) are unmapped.
            charging_status = {0: "Disconnected", 1: "InProgress", 3: "Stopped"}.get(event_charging.get("hmi_state_code"))
            if charging_status:
                charging["status"] = charging_status
            if event_charging.get("plugged") is not None:
                charging["plugged"] = event_charging["plugged"]

        doors_state = data.get("doorsState")
        if doors_state is not None and self._mqtt_is_newer("doors", doors_state.get("createdAt") or data.get("updatedAt")):
            locking_code = (event.get("doors") or {}).get("locking_state_code")
            locked_states = doors_state.get("lockedStates") or []
            # Only touch lockedStates when the lock state actually differs, so
            # finer REST values (e.g. SuperLocked) survive. 0 and 7 are
            # transient mid-(un)lock steps and are ignored.
            if locking_code == 1 and "Unlocked" in locked_states:
                doors_state["lockedStates"] = ["Locked"]
            elif locking_code == 3 and "Unlocked" not in locked_states:
                doors_state["lockedStates"] = ["Unlocked"]

        if doors_state is not None and self._mqtt_is_newer("door_opening", doors_state.get("createdAt") or data.get("updatedAt")):
            door_open = (event.get("doors") or {}).get("open") or {}
            names = {"Driver": "driver", "Passenger": "passenger", "RearLeft": "rear_left", "RearRight": "rear_right", "Trunk": "trunk"}
            for opening in doors_state.get("opening") or []:
                name = names.get(opening.get("identifier"))
                if name in door_open:
                    opening["state"] = "Open" if door_open[name] else "Closed"

        # REST sends this section as "preconditioning", "preconditionning" or
        # both, depending on the vehicle; keep every copy consistent.
        for key in ("preconditioning", "preconditionning"):
            air_conditioning = (data.get(key) or {}).get("airConditioning")
            if air_conditioning is not None and self._mqtt_is_newer("preconditioning", air_conditioning.get("createdAt") or data.get("updatedAt")):
                status = {0: "Disabled", 1: "Enabled", 2: "Finished"}.get((event.get("preconditioning") or {}).get("status_code"))
                if status:
                    air_conditioning["status"] = status

    def _mqtt_is_newer(self, group:str, rest_timestamp:Any) -> bool:
        """ Whether the group's last MQTT change is newer than the REST timestamp (a missing one counts as older). """
        changed_at = self._mqtt_changed_at.get(group)
        if changed_at is None:
            return False
        rest_dt = parse_timestamp(rest_timestamp)
        return rest_dt is None or changed_at > rest_dt

    @rate_limit(6, 1200) # 6 per 20 min
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

    async def send_charge_limit_command(self, button_name, action):
        """ Send charge limit command to the vehicle. """
        await self.send_command(button_name, "/VehCharge/limit", {"action": action})

    def get_programs(self):
        """ Get current preconditioning programs. """
        default_programs = {
           "program1": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program2": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program3": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0},
           "program4": {"day": [0, 0, 0, 0, 0, 0, 0], "hour": 34, "minute": 7, "on": 0}
        }
        air_conditioning = (self.data.get("preconditioning") or {}).get("airConditioning") or {}
        current_programs = air_conditioning.get("programs")
        if current_programs:
            for program in current_programs:
                if program:
                    occurence = program.get("occurence")
                    if occurence and occurence.get("day") and program.get("start"):
                        date = time_from_pt_string(program["start"])
                        if date is None:
                            continue
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

    async def _auto_stop_charge_at_limit(self) -> None:
        """ Send a delayed charge-stop command once the configured limit is reached. """
        if "battery_charging" not in self._sensors:
            return
        if self._sensors.get("battery_charging_limit") == "Partial":
            return
        if self._sensors.get("battery_charging") != "InProgress":
            self._manage_charge_limit_sent = False
            return
        if self._manage_charge_limit_sent:
            return
        charge_limit_on = self._sensors.get("switch_battery_charging_limit", False)
        charge_limit = self._sensors.get("number_battery_charging_limit")
        battery = self._sensors.get("battery")
        if not (charge_limit_on and charge_limit and battery is not None):
            return
        if int(float(battery)) < int(charge_limit):
            return
        # The stop command carries the charging start time (hour/minute); until
        # the vehicle reports one this is a normal state, not an error.
        if self._sensors.get("time_battery_charging_start") is None:
            _LOGGER.debug("Cannot auto-stop charging for vehicle %s yet: no charging start time known", self._vehicle["vin"])
            return
        button_name = self.get_translation("component.stellantis_vehicles.entity.button.charge_stop.name")
        try:
            await self.send_charge_command(button_name, False, "delayed")
        except (HomeAssistantError, CommunicationError) as err:
            # Raising here would fail the whole update and discard the fresh data.
            _LOGGER.warning("Could not stop charging vehicle %s at the configured limit, retrying on the next update: %s", self._vehicle["vin"], err)
            return
        self._manage_charge_limit_sent = True

    async def _fetch_last_trip_on_engine_stop(self, new_data: dict[str, Any]) -> None:
        """ Fetch the last trip once the engine transitions from running to Stop. """
        current_engine_status = self._sensors.get("engine")
        new_engine_status = new_data.get("ignition", {}).get("type")
        if new_engine_status != "Stop":
            return
        if current_engine_status in (None, "Stop"):
            _LOGGER.debug("No last-trip fetch needed (engine %s -> Stop)", current_engine_status)
            return
        _LOGGER.debug("Engine status changed from %s to %s, fetching last trip data", current_engine_status, new_engine_status)
        await self.get_vehicle_last_trip()

    async def get_vehicle_last_trip(self):
        """ Get last trip from Stellantis. """
        try:
            trips = await self._stellantis.get_vehicle_last_trip(self._vehicle)
            if "_embedded" in trips and "trips" in trips["_embedded"] and trips["_embedded"]["trips"]:
                if not self._last_trip or self._last_trip["id"] != trips["_embedded"]["trips"][-1]["id"]:
                    self._last_trip = trips["_embedded"]["trips"][-1]
        except Exception as e:
            _LOGGER.warning("Failed to fetch last trip data: %s", e)

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
