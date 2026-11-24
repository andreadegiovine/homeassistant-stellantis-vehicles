"""Vehicle coordinator of the Leapmotor client: remote commands over the cloud API."""
import json
import logging
from copy import deepcopy
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ...base import StellantisVehicleCoordinator
from ...const import DOMAIN
from ...exceptions import CommunicationError
from ...utils import SENSITIVE_DATA_FILTER, get_datetime, parse_timestamp

from .status import apply_charging_plan, charging_plan, charging_plan_is_complete

from .const import (
    SUPPORTED_ENTITIES,
    COMMAND_BATTERY_PREHEATING_ON,
    COMMAND_BATTERY_PREHEATING_OFF,
    COMMAND_CHARGING_PLAN_ID,
    CHARGING_PLAN_READ_ONLY_MODELS,
    PLAN_CONFIRMATION_TIMEOUT,
    TRIP_MIN_DISTANCE,
    COMMAND_LOCK,
    COMMAND_UNLOCK,
    COMMAND_FIND_CAR,
    COMMAND_CLIMATE_ON,
    COMMAND_CLIMATE_OFF,
    COMMAND_CLIMATE_OFF_T03
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)


class LeapmotorVehicleCoordinator(StellantisVehicleCoordinator):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Trip in progress: where and when it started, top speed so far.
        self._trip: dict[str, Any] | None = None
        # Charging plan change just sent, shown until the vehicle reports it.
        self._plan_sent: dict[str, Any] | None = None

    @property
    def _car_type(self) -> str:
        return str(self._vehicle.get("car_type") or "").upper()

    def supports(self, platform: str, key: str) -> bool:
        if key in ("battery_charging_limit", "battery_charging_start", "battery_charging_schedule") and self._car_type in CHARGING_PLAN_READ_ONLY_MODELS:
            return False
        return key in SUPPORTED_ENTITIES.get(platform, ())

    def diagnostics(self) -> dict[str, Any]:
        return {
            "car_type": self._vehicle.get("car_type"),
            "shared": self._vehicle.get("shared"),
            "rights": self._vehicle.get("rights"),
            "abilities": self._vehicle.get("abilities"),
        }

    has_vehicle_charge_limit = True

    @property
    def _plan(self) -> dict[str, Any]:
        return (self.data or {}).get("chargingPlan") or {}

    @property
    def vehicle_charge_limit(self) -> int | None:
        try:
            return int(float(self._plan.get("percent")))
        except (TypeError, ValueError):
            return None

    @property
    def charging_schedule_enabled(self) -> bool | None:
        """ Whether the vehicle waits for the scheduled start time to charge. """
        try:
            return bool(int(float(self._plan.get("isEnable"))))
        except (TypeError, ValueError):
            return None

    async def _write_charging_plan(self, name: str, **changes) -> None:
        """ Write the charging plan back with the given values changed, everything else as it is.

        The change is shown at once: the vehicle can take a while to report
        it, and a status no newer than the current one is not applied at all.
        It is taken back if the vehicle does not carry the command out.
        """
        plan = self._plan
        if not charging_plan_is_complete(plan):
            # The status does not always carry the whole plan.
            stored = charging_plan(await self._stellantis.get_charging_plan(self._vehicle))
            plan = {key: plan.get(key) if plan.get(key) not in (None, "") else stored.get(key) for key in stored}
        if not charging_plan_is_complete(plan):
            raise ServiceValidationError(translation_domain = DOMAIN, translation_key = "charging_plan_incomplete")
        new_plan = {**plan, **changes}
        content = json.dumps({
            "chargeEnable": 1 if int(float(new_plan["isEnable"])) else 0,
            "chargesoc": int(float(new_plan["percent"])),
            "circulation": int(float(new_plan.get("circulation") or 0)),
            "cycles": str(new_plan["cycles"]),
            "endtime": str(new_plan["endTime"]),
            "recharge": int(float(new_plan.get("recharge") or 0)),
            "starttime": str(new_plan["beginTime"]),
        }, separators=(",", ":"))
        await self.send_command(name, COMMAND_CHARGING_PLAN_ID, content)
        self._plan_sent = {"changes": changes, "previous": self._plan, "at": get_datetime()}
        if self.data:
            data = deepcopy(self.data)
            apply_charging_plan(data, new_plan)
            # Not async_set_updated_data(): that would reset the poll timer.
            self.data = data
        self.async_update_listeners()

    def _prepare_new_data(self, new_data: dict[str, Any]) -> None:
        """ Keep a charging plan change just sent until the vehicle reports it. """
        sent = self._plan_sent
        if not sent:
            return
        plan = new_data.get("chargingPlan") or {}
        reported = all(str(plan.get(key)) == str(value) for key, value in sent["changes"].items())
        if reported or (get_datetime() - sent["at"]).total_seconds() > PLAN_CONFIRMATION_TIMEOUT:
            self._plan_sent = None
            return
        apply_charging_plan(new_data, {**plan, **sent["changes"]})

    def _plan_not_applied(self) -> None:
        """ The vehicle did not carry a charging plan change out: show its own plan again. """
        sent, self._plan_sent = self._plan_sent, None
        if sent and self.data:
            data = deepcopy(self.data)
            apply_charging_plan(data, sent["previous"])
            self.data = data

    async def send_charge_limit_value_command(self, name: str, value: int) -> None:
        await self._write_charging_plan(name, percent=int(value))

    async def send_charge_command(self, button_name, update_only_time = False, action = "immediate"):
        """ Schedule the charge at the start time chosen in the time entity.

        Only the start time can be set (the shared time entity calls this with
        ``update_only_time``); choosing one also turns the schedule on, as a
        start time does nothing while it is off.
        """
        if not update_only_time:
            raise NotImplementedError
        start = self._sensors.get("time_battery_charging_start")
        # In the format the plan already uses (with or without seconds).
        seconds = ":00" if str(self._plan.get("beginTime") or "").count(":") == 2 else ""
        await self._write_charging_plan(button_name, beginTime=f"{start.hour:02d}:{start.minute:02d}{seconds}", isEnable=1)

    async def send_charging_schedule_command(self, name: str, enable: bool) -> None:
        await self._write_charging_plan(name, isEnable=1 if enable else 0)

    async def send_battery_preheating_command(self, name: str, enable: bool) -> None:
        await self.send_command(name, *(COMMAND_BATTERY_PREHEATING_ON if enable else COMMAND_BATTERY_PREHEATING_OFF))

    async def after_async_update_data(self, new_data: dict[str, Any]) -> None:
        self._track_trip(new_data)
        await super().after_async_update_data(new_data)

    def _track_trip(self, data: dict[str, Any]) -> None:
        """ Build the last trip from the statuses: Leapmotor has no trips endpoint.

        A trip runs from the first status showing the vehicle ready or moving
        to the first one showing it stopped; it is as precise as the polling,
        and one in progress is lost if Home Assistant restarts.
        """
        kinetic = data.get("kinetic") or {}
        driving = bool(kinetic.get("moving")) or (data.get("ignition") or {}).get("type") == "StartUp"
        mileage = (data.get("odometer") or {}).get("mileage")
        electric = next((energy for energy in data.get("energies") or [] if energy.get("type") == "Electric"), {})
        residual = (((electric.get("extension") or {}).get("electric") or {}).get("battery") or {}).get("load", {}).get("residual")
        moment = parse_timestamp(data.get("updatedAt")) or get_datetime()

        if driving and self._trip is None:
            if mileage is not None:
                self._trip = {"start": moment, "mileage": mileage, "residual": residual, "max_speed": 0.0}
        if self._trip is None:
            return
        self._trip["max_speed"] = max(self._trip["max_speed"], kinetic.get("speed") or 0.0)
        if driving:
            return

        trip, self._trip = self._trip, None
        duration = (moment - trip["start"]).total_seconds()
        if mileage is None or mileage - trip["mileage"] < TRIP_MIN_DISTANCE or duration <= 0:
            return
        distance = round(mileage - trip["mileage"], 1)
        last_trip = {
            "id": trip["start"].isoformat(),
            "distance": distance,
            "duration": duration,
            "startMileage": trip["mileage"],
            # Average in m/s and top speed in km/h, as the PSA trips report them.
            "kinetic": {"avgSpeed": distance * 1000 / duration, "maxSpeed": trip["max_speed"]},
        }
        if trip["residual"] is not None and residual is not None and trip["residual"] > residual:
            consumption = trip["residual"] - residual
            last_trip["energyConsumptions"] = [{"type": "Electric", "consumption": consumption, "avgConsumption": consumption / distance * 100}]
        self._last_trip = last_trip

    async def _send_remote_command(self, service: str, message: Any) -> str | None:
        """ Send the command; its result is then followed in the background. """
        try:
            control = await self._stellantis.send_remote_command(self._vehicle, service, message)
        except CommunicationError as err:
            # Shown to the user as is: a refused PIN, an offline vehicle...
            raise HomeAssistantError(
                translation_domain = DOMAIN,
                translation_key = "command_refused",
                translation_placeholders = {"reason": str(err)}
            ) from err
        action_id = str(control.get("remoteCtlId") or f"leapmotor-{id(control)}")
        self.config_entry.async_create_background_task(self.hass, self._follow_remote_command(action_id, control), f"{DOMAIN} remote command result")
        return action_id

    async def _follow_remote_command(self, action_id: str, control: dict[str, Any]) -> None:
        """ Record the outcome of a sent command in its history, then refresh the status. """
        try:
            done = await self._stellantis.wait_remote_command(control)
            update = "0" if done else "300"
        except Exception as err:
            _LOGGER.warning("Could not read the result of a remote command for vehicle %s: %s", self._vehicle["vin"], err)
            update = "failed"
        await self.update_command_history(action_id, update)
        if update == "0":
            await self.async_request_refresh()
        if update != "0":
            self._plan_not_applied()
            self.async_update_listeners()

    async def send_doors_command(self, button_name, action):
        await self.send_command(button_name, *(COMMAND_LOCK if action == "lock" else COMMAND_UNLOCK))

    async def send_horn_command(self, button_name):
        """ The closest Leapmotor has: "find my car" sounds the horn and flashes the lights. """
        await self.send_command(button_name, *COMMAND_FIND_CAR)

    async def send_preconditioning_command(self, button_name, action):
        if action == "activate":
            command = COMMAND_CLIMATE_ON
        elif str(self._vehicle.get("car_type") or "").upper() == "T03":
            command = COMMAND_CLIMATE_OFF_T03
        else:
            command = COMMAND_CLIMATE_OFF
        await self.send_command(button_name, *command)
