import os
import json

from homeassistant.const import ( UnitOfTemperature, UnitOfLength, PERCENTAGE, UnitOfElectricPotential, UnitOfEnergy, UnitOfSpeed, UnitOfVolume )
from homeassistant.components.sensor.const import ( SensorDeviceClass, SensorStateClass )
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

DOMAIN = "stellantis_vehicles"

with open(os.path.dirname(os.path.abspath(__file__)) + "/configs.json", "r") as f:
    MOBILE_APPS = json.load(f)

MQTT_REFRESH_TOKEN_TTL = (60*24*3) # 3 days
OTP_FILENAME = "{#customer_id#}_otp.pickle"

IMAGE_PATH = "stellantis-vehicles"

OAUTH_BASE_URL = "{#oauth_url#}/am/oauth2"
OAUTH_AUTHORIZE_URL = OAUTH_BASE_URL + "/authorize"
OAUTH_TOKEN_URL = OAUTH_BASE_URL + "/access_token"

API_BASE_URL = "https://api.groupe-psa.com"
GET_USER_INFO_URL = API_BASE_URL + "/applications/cvs/v4/mauv/car-associations"
GET_OTP_URL = API_BASE_URL + "/applications/cvs/v4/mobile/smsCode"
GET_MQTT_TOKEN_URL = API_BASE_URL + "/connectedcar/v4/virtualkey/remoteaccess/token"
CAR_API_BASE_URL = API_BASE_URL + "/connectedcar/v4/user"
CAR_API_VEHICLES_URL = CAR_API_BASE_URL + "/vehicles"
CAR_API_GET_VEHICLE_STATUS_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/status"
CAR_API_GET_VEHICLE_TRIPS_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/trips"

MQTT_SERVER = "mwa.mpsa.com"
MQTT_RESP_TOPIC = "psa/RemoteServices/to/cid/"
MQTT_EVENT_TOPIC = "psa/RemoteServices/events/MPHRTServices/"
MQTT_REQ_TOPIC = "psa/RemoteServices/from/cid/"

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
    "Authorization": "Bearer {#access_token#}",
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
    "refresh_token": "{#refresh_token#}"
}

CAR_API_HEADERS = {
    "Authorization": "Bearer {#access_token#}",
    "x-introspect-realm": "{#realm#}"
}

FIELD_MOBILE_APP = "mobile_app"
FIELD_COUNTRY_CODE = "country_code"
FIELD_OAUTH_CODE = "oauth_code"
FIELD_SMS_CODE = "sms_code"
FIELD_PIN_CODE = "pin_code"

PLATFORMS = [
    "device_tracker",
    "sensor",
    "binary_sensor",
    "button",
    "number",
    "text",
    "switch",
    "time"
]

UPDATE_INTERVAL = 60 # seconds

VEHICLE_TYPE_ELECTRIC = "Electric"
VEHICLE_TYPE_HYBRID = "Hybrid"
VEHICLE_TYPE_THERMIC = "Thermic"
VEHICLE_TYPE_HYDROGEN = "Hydrogen"

SENSORS_DEFAULT = {
    "vehicle" : {
        "icon" : "mdi:car",
    },
    "service_battery_voltage" : {
        "icon" : "mdi:car-battery",
        "unit_of_measurement" : PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["battery", "voltage"],
        "updated_at_map" : ["battery", "createdAt"]
    },
    "temperature" : {
        "icon" : "mdi:thermometer",
        "unit_of_measurement" : UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["environment", "air", "temp"],
        "updated_at_map" : ["environment", "air", "createdAt"]
    },
    "mileage" : {
        "icon" : "mdi:road-variant",
        "unit_of_measurement" : UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "value_map" : ["odometer", "mileage"],
        "updated_at_map" : ["odometer", "createdAt"]
    },
    "speed" : {
        "icon" : "mdi:speedometer",
        "unit_of_measurement" : UnitOfSpeed.KILOMETERS_PER_HOUR,
        "device_class": SensorDeviceClass.SPEED,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["kinetic", "speed"],
        "updated_at_map" : ["kinetic", "createdAt"]
    },
    "autonomy" : {
        "icon" : "mdi:map-marker-distance",
        "unit_of_measurement" : UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "autonomy"],
        "updated_at_map" : ["energies", 0, "createdAt"]
    },
    "battery" : {
        "unit_of_measurement" : PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "level"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
    "battery_soh" : {
        "icon" : "mdi:battery-heart-variant",
        "unit_of_measurement" : PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "extension", "electric", "battery", "health", "resistance"],
        "updated_at_map" : ["energies", 0, "extension", "electric", "battery", "health", "createdAt"],
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
    "battery_charging_rate" : {
        "icon" : "mdi:ev-station",
        "unit_of_measurement" : UnitOfSpeed.KILOMETERS_PER_HOUR,
        "device_class": SensorDeviceClass.SPEED,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "extension", "electric", "charging", "chargingRate"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
    "battery_charging_type" : {
        "icon" : "mdi:lightning-bolt",
        "value_map" : ["energies", 0, "extension", "electric", "charging", "chargingMode"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
     "battery_charging_end" : {
        "icon" : "mdi:battery-check",
        "device_class" : SensorDeviceClass.TIMESTAMP,
        "value_map" : ["energies", 0, "extension", "electric", "charging", "remainingTime"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "available" : [{"battery_charging": "InProgress"}],
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
     },
     "battery_capacity" : {
        "icon" : "mdi:battery-arrow-up-outline",
        "unit_of_measurement" : UnitOfEnergy.KILO_WATT_HOUR,
        "device_class" : SensorDeviceClass.ENERGY_STORAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "extension", "electric", "battery", "load", "capacity"],
        "updated_at_map" : ["energies", 0, "extension", "electric", "battery", "load", "createdAt"],
        "suggested_display_precision": 2,
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
     },
     "battery_residual" : {
        "icon" : "mdi:battery-arrow-up",
        "unit_of_measurement" : UnitOfEnergy.KILO_WATT_HOUR,
        "device_class" : SensorDeviceClass.ENERGY_STORAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "extension", "electric", "battery", "load", "residual"],
        "updated_at_map" : ["energies", 0, "extension", "electric", "battery", "load", "createdAt"],
        "suggested_display_precision": 2,
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
     },
    "fuel" : {
        "icon": "mdi:gas-station",
        "unit_of_measurement" : PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "level"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "fuel_autonomy" : {
        "icon" : "mdi:map-marker-distance",
        "unit_of_measurement" : UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "autonomy"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "fuel_consumption_total" : {
        "icon": "mdi:gas-station-outline",
        "unit_of_measurement" : UnitOfVolume.LITERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "value_map" : ["energies", 0, "extension", "fuel", "consumptions", "total"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "suggested_display_precision": 2,
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "fuel_consumption_instant" : {
        "icon": "mdi:gas-station-outline",
        "unit_of_measurement" : UnitOfVolume.LITERS+"/100"+UnitOfLength.KILOMETERS,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["energies", 0, "extension", "fuel", "consumptions", "instant"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "coolant_temperature" : {
        "icon": "mdi:coolant-temperature",
        "unit_of_measurement" : UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["engines", 0, "extension", "thermic", "coolant", "temp"],
        "updated_at_map" : ["engines", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "oil_temperature" : {
        "icon": "mdi:oil-temperature",
        "unit_of_measurement" : UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["engines", 0, "extension", "thermic", "oil", "temp"],
        "updated_at_map" : ["engines", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    },
    "air_temperature" : {
        "icon": "mdi:thermometer-lines",
        "unit_of_measurement" : UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "value_map" : ["engines", 0, "extension", "thermic", "air", "temp"],
        "updated_at_map" : ["engines", 0, "createdAt"],
        "engine": [VEHICLE_TYPE_THERMIC, VEHICLE_TYPE_HYBRID]
    }
}

BINARY_SENSORS_DEFAULT = {
    "moving" : {
        "icon" : "mdi:car-traction-control",
        "value_map" : ["kinetic", "moving"],
        "updated_at_map" : ["kinetic", "createdAt"],
        "device_class" : BinarySensorDeviceClass.MOTION,
        "on_value": True
    },
    "doors" : {
        "icon" : "mdi:car-door-lock",
        "value_map" : ["doorsState", "lockedStates"],
        "updated_at_map" : ["doorsState", "createdAt"],
        "device_class" : BinarySensorDeviceClass.LOCK,
        "on_value": "Unlocked"
    },
    "battery_plugged" : {
        "icon" : "mdi:power-plug-battery",
        "value_map" : ["energies", 0, "extension", "electric", "charging", "plugged"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "device_class" : BinarySensorDeviceClass.PLUG,
        "on_value": True,
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
    "battery_charging" : {
        "icon" : "mdi:battery-charging-medium",
        "value_map" : ["energies", 0, "extension", "electric", "charging", "status"],
        "updated_at_map" : ["energies", 0, "createdAt"],
        "device_class" : BinarySensorDeviceClass.BATTERY_CHARGING,
        "on_value": "InProgress",
        "engine": [VEHICLE_TYPE_ELECTRIC, VEHICLE_TYPE_HYBRID]
    },
    "engine" : {
        "icon" : "mdi:power",
        "value_map" : ["ignition", "type"],
        "updated_at_map" : ["ignition", "createdAt"],
        "device_class" : BinarySensorDeviceClass.POWER,
        "on_value": "StartUp"
    },
    "preconditioning" : {
        "icon" : "mdi:air-conditioner",
        "value_map" : ["preconditioning", "airConditioning", "status"],
        "updated_at_map" : ["preconditioning", "airConditioning", "createdAt"],
        "device_class" : BinarySensorDeviceClass.POWER,
        "on_value": "Enabled"
    },
    "alarm" : {
        "icon" : "mdi:alarm-light",
        "value_map" : ["alarm", "status", "activation"],
        "updated_at_map" : ["alarm", "status", "createdAt"],
        "device_class" : BinarySensorDeviceClass.RUNNING,
        "on_value": "Active"
    },
    "privacy" : {
        "icon" : "mdi:alarm-light",
        "value_map" : ["privacy", "state"],
        "updated_at_map" : ["privacy", "createdAt"],
        "device_class" : BinarySensorDeviceClass.LOCK,
        "on_value": "None"
    }
}