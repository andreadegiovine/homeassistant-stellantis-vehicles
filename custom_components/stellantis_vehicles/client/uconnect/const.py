"""Constants specific to the Uconnect (ex FCA) cloud client, served by py-uconnect."""

CLIENT_UCONNECT = "uconnect"
# Shown where the PSA clients show their mobile app name.
MOBILE_APP = "Uconnect"

# Brand and region of the account: a py_uconnect.BRANDS key in lower case
# (e.g. "fiat_eu"), as translation keys must be.
FIELD_BRAND = "uconnect_brand"
FIELD_PIN_CODE = "pin_code"

# The Uconnect cloud is polled every 5 minutes by default, as the official apps
# and hass-uconnect do: it only holds the last status the vehicle sent.
UPDATE_INTERVAL = 300
# One account refresh loads every vehicle: it is reused by the coordinators
# of the other vehicles for this many seconds.
STATUS_CACHE_SECONDS = 30
# Seconds to wait for the vehicle to report the outcome of a remote command.
COMMAND_TIMEOUT = 90

# Remote commands, by the name py-uconnect knows them.
COMMAND_DOORS_LOCK = "RDL"
COMMAND_DOORS_UNLOCK = "RDU"
COMMAND_LIGHTS_HORN = "HBLF"
COMMAND_LIGHTS = "ROLIGHTS"
COMMAND_PRECOND_ON = "ROPRECOND"
COMMAND_PRECOND_OFF = "ROPRECOND_OFF"
COMMAND_HVAC_ON = "ROHVACON"
COMMAND_HVAC_OFF = "ROHVACOFF"
COMMAND_DEEP_REFRESH = "DEEPREFRESH"
COMMAND_CHARGE = "CNOW"

# Command entities and the commands enabling them: created only for the
# vehicles that support one of them.
COMMAND_ENTITIES = {
    ("button", "wakeup"): (COMMAND_DEEP_REFRESH,),
    ("button", "doors_lock"): (COMMAND_DOORS_LOCK,),
    ("button", "doors_unlock"): (COMMAND_DOORS_UNLOCK,),
    ("button", "horn"): (COMMAND_LIGHTS_HORN,),
    ("button", "lights"): (COMMAND_LIGHTS,),
    ("button", "preconditioning_start"): (COMMAND_PRECOND_ON, COMMAND_HVAC_ON),
    ("button", "preconditioning_stop"): (COMMAND_PRECOND_OFF, COMMAND_HVAC_OFF),
    ("button", "charge_start"): (COMMAND_CHARGE,),
}

# The other entities of the shared platforms this client can serve. What is
# missing here has no Uconnect equivalent (yet).
SUPPORTED_ENTITIES = {
    "sensor": {"vehicle", "mileage", "autonomy", "battery", "battery_charging_type", "battery_charging_end", "fuel", "fuel_autonomy", "mileage_before_maintenance", "days_before_maintenance", "type", "command_status", "last_charge", "last_trip"},
    "binary_sensor": {"doors", "battery_plugged", "battery_charging", "engine", "preconditioning", "privacy", "remote_commands", "command_pending"},
    "number": {"refresh_interval"},
    "switch": {"abrp_sync"},
    "text": {"abrp_token"},
    "time": set(),
    "device_tracker": {"vehicle"},
}

# fuelType of fully electric vehicles in the vehicle list.
FUEL_TYPE_ELECTRIC = "E"
KM_PER_MILE = 1.609344
