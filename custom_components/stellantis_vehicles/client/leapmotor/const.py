"""Constants specific to the Leapmotor (international) cloud client."""

CLIENT_LEAPMOTOR = "leapmotor"
# Shown where the PSA clients show their mobile app name.
MOBILE_APP = "Leapmotor"

FIELD_PIN_CODE = "pin_code"
FIELD_DEVICE_ID = "device_id"

API_BASE_URL = "https://appgateway.leapmotor-international.de"
API_PREFIX = "/carownerservice/oversea"
LOGIN_URL = API_PREFIX + "/acct/v1/login"
TOKEN_REFRESH_URL = API_PREFIX + "/acct/v1/token/refresh"
VEHICLES_URL = API_PREFIX + "/vehicle/v1/list"
VEHICLE_STATUS_URL = API_PREFIX + "/vehicle/v1/status/get/{car_type}"
CERT_SYNC_URL = API_PREFIX + "/vehicle/v1/cert/sync"
PIN_VERIFY_URL = API_PREFIX + "/vehicle/v1/operPwd/verify"
REMOTE_CONTROL_URL = API_PREFIX + "/vehicle/v1/app/remote/ctl"
REMOTE_CONTROL_RESULT_URL = API_PREFIX + "/vehicle/v1/app/remote/ctl/result/query"

# Values the official app sends with every request; they are part of the
# request signature.
APP_VERSION = "1.12.3"
APP_SOURCE = "leapmotor"
APP_CHANNEL = "1"
APP_LANGUAGE = "en-GB"
APP_DEVICE_TYPE = "1"
APP_P12_ENC_ALG = "1"
APP_POLICY_ID = "20260204"

# The login endpoint only answers a client presenting the mobile app's own TLS
# certificate. It is the same for every user and is not shipped with the
# integration: it is downloaded once when a Leapmotor account is set up and
# kept in the Home Assistant storage folder. A file already there is used
# as-is, so it can also be provided by hand.
APP_CERT_URL = "https://raw.githubusercontent.com/markoceri/leapmotor-certs/main/app.crt"
APP_KEY_URL = "https://raw.githubusercontent.com/markoceri/leapmotor-certs/main/app.key"
APP_CERT_FOLDER = "leapmotor"
APP_CERT_FILENAME = "app_cert.pem"
APP_KEY_FILENAME = "app_key.pem"

# API result code of a login refused for wrong credentials.
LOGIN_REFUSED_CODE = "302010108"

# Used by the app to encrypt the vehicle PIN when no session token is at hand.
PIN_FALLBACK_AES_KEY = "f1cf0c025baec0e2"
PIN_FALLBACK_AES_IV = "6b6a1fe94e133fd7"

REMOTE_RESULT_DEFAULT_TIMEOUT_MS = 30000
REMOTE_RESULT_DEFAULT_INTERVAL_MS = 2000

# Remote commands: (command id, command content). The content is signed and
# sent verbatim, so it is kept as the exact string the app sends.
COMMAND_LOCK = ("110", '{"value":"lock"}')
COMMAND_UNLOCK = ("110", '{"value":"unlock"}')
COMMAND_FIND_CAR = ("120", '{"value":"true"}')
COMMAND_CLIMATE_ON = ("170", '{"circle":"out","mode":"nohotcold","operate":"manual","position":"all","temperature":"24","windlevel":"4","wshld":"1"}')
COMMAND_CLIMATE_OFF = ("170", '{"operate":"off"}')
# The T03 only switches the climate off with the full payload.
COMMAND_CLIMATE_OFF_T03 = ("170", '{"circle":"out","mode":"wind","operate":"off","position":"all","temperature":"26","windlevel":"3","wshld":"0"}')

# Models that answer on another model's status endpoint.
STATUS_PATH_ALIASES = {"b05": "c10", "b10": "c10", "b11": "c10"}
STATUS_PATH_DEFAULT = "c10"

# Entities of the shared platforms this client can serve, by platform. What is
# missing here has no (verified) Leapmotor equivalent yet.
SUPPORTED_ENTITIES = {
    "sensor": {"vehicle", "temperature", "mileage", "speed", "autonomy", "battery", "battery_charging_type", "battery_charging_end", "fuel", "fuel_autonomy", "type", "command_status", "last_charge"},
    "binary_sensor": {"moving", "doors", "door_trunk", "door_driver", "door_passenger", "door_rear_left", "door_rear_right", "battery_plugged", "battery_charging", "engine", "preconditioning", "remote_commands", "command_pending"},
    "button": {"doors_lock", "doors_unlock", "horn", "preconditioning_start", "preconditioning_stop"},
    "number": {"refresh_interval"},
    "switch": {"abrp_sync"},
    "text": {"abrp_token"},
    "time": set(),
    "device_tracker": {"vehicle"},
}
