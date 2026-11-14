"""Constants specific to the PSA (ex Groupe PSA) cloud client."""
import os
import json

with open(os.path.dirname(os.path.abspath(__file__)) + "/configs.json", "r") as f:
    MOBILE_APPS = json.load(f)

MQTT_REFRESH_TOKEN_TTL = (60*24*3) # 3 days

OTP_FILENAME = "{#customer_id#}_otp.pickle"

OAUTH_BASE_URL = "{#oauth_url#}/am/oauth2"

OAUTH_AUTHORIZE_URL = OAUTH_BASE_URL + "/authorize"

OAUTH_TOKEN_URL = OAUTH_BASE_URL + "/access_token"

OAUTH_CODE_URL = "https://homeassistant-stellantis-vehicles-worker.onrender.com"

API_BASE_URL = "https://api.groupe-psa.com"

GET_USER_INFO_URL = API_BASE_URL + "/applications/cvs/v4/mauv/car-associations"

# The remote services a vehicle's subscription covers, each with its "fds"
# feature code and official name (what the vendor app's forFDS(vin) calls).
GET_VEHICLE_RIGHTS_URL = API_BASE_URL + "/applications/cvs/v4/rights/vehicle/{#vin#}"

GET_OTP_URL = API_BASE_URL + "/applications/cvs/v4/mobile/smsCode"

GET_MQTT_TOKEN_URL = API_BASE_URL + "/connectedcar/v4/virtualkey/remoteaccess/token"

CAR_API_BASE_URL = API_BASE_URL + "/connectedcar/v4/user"

CAR_API_VEHICLES_URL = CAR_API_BASE_URL + "/vehicles"

CAR_API_GET_VEHICLE_STATUS_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/status"

CAR_API_GET_VEHICLE_TRIPS_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/trips"

MQTT_SERVER = "mwa.mpsa.com"

MQTT_PORT = 8885

MQTT_KEEP_ALIVE_S = 120

MQTT_RESP_TOPIC = "psa/RemoteServices/to/cid/"

MQTT_EVENT_TOPIC = "psa/RemoteServices/events/MPHRTServices/"

MQTT_REQ_TOPIC = "psa/RemoteServices/from/cid/"

MQTT_QOS = 0

MQTT_USERNAME = "IMA_OAUTH_ACCESS_TOKEN"

# resp_data failure reasons per service and field, from the vendor app's
# response enums; the first field present wins.
MQTT_RESP_DATA_ERROR_CODES = {
    "/Doors": {
        "error": {
            0: "warning_discarded_sev_not_stop",
        },
        "lock_resp_state": {
            0: "doors_state_unlocked",
            1: "doors_state_locked",
            2: "doors_discarded_door_open",
            3: "doors_request_refused",
            4: "doors_unknown_reason",
            5: "doors_cid_inside",
        },
    },
    "/Horn": {
        "error": {
            0: "warning_discarded_sev_not_stop",
            1: "warning_wait_before_resend",
        },
    },
    "/Lights": {
        "error": {
            0: "warning_discarded_sev_not_stop",
            2: "warning_wait_before_resend",
        },
    },
    "/ThermalPrecond": {
        "error": {
            0: "precond_discarded_sev_not_stop",
            1: "precond_discarded_already_ongoing",
            2: "precond_discarded_communication_problem",
            3: "precond_stop_discarded_sev_not_stop",
            4: "precond_stop_discarded_not_ongoing",
        },
    },
}

# Shared by all /VehCharge* services; the app maps only 0-3.
MQTT_CHARGING_RESP_DATA_ERROR_CODES = {
    "error": {
        0: "charging_discarded_standby",
        1: "charging_discarded_already_ongoing",
        2: "charging_discarded_communication_problem",
        3: "charging_discarded_sev_not_stop",
    },
}

CLIENT_ID_QUERY_PARAMS = {
    "client_id": "{#client_id#}",
    "locale": "{#locale#}"
}

OAUTH_AUTHORIZE_QUERY_PARAMS = {
    "client_id": "{#client_id#}",
    "response_type": "code",
    "redirect_uri": "{#scheme#}://oauth2redirect/{#culture#}",
    "scope": "openid%20profile%20email",
    "locale": "{#locale#}"
}

OAUTH_TOKEN_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": "Basic {#basic_token#}",
}

GET_OTP_HEADERS = {
    "Authorization": "Bearer {#oauth|access_token#}",
    "User-Agent": "okhttp/4.8.0",
    "Accept": "application/hal+json",
    "x-introspect-realm": "{#realm#}"
}

OAUTH_GET_TOKEN_QUERY_PARAMS = {
    "redirect_uri": "{#scheme#}://oauth2redirect/{#culture#}",
    "grant_type": "authorization_code",
    "code": "{#oauth_code#}"
}

OAUTH_REFRESH_TOKEN_QUERY_PARAMS = {
    "grant_type": "refresh_token",
    "refresh_token": "{#oauth|refresh_token#}"
}

CAR_API_HEADERS = {
    "Authorization": "Bearer {#oauth|access_token#}",
    "x-introspect-realm": "{#realm#}"
}

MQTT_REFRESH_TOKEN_JSON_DATA = {
    "grant_type": "refresh_token",
    "refresh_token": "{#mqtt|refresh_token#}"
}

# Backoff schedule (seconds) for the MQTT token refresh after a transient
# Stellantis backend failure. Capped at the last step so a prolonged outage is
# retried every ~15 min instead of once a minute.
MQTT_TOKEN_RETRY_BACKOFF = (60, 120, 300, 600, 900)

# Same schedule for the OAuth token refresh: retried on a capped backoff after a
# transient failure instead of a flat 5-minute loop, and logged at WARNING.
OAUTH_TOKEN_RETRY_BACKOFF = (60, 120, 300, 600, 900)
