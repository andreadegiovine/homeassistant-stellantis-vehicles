from homeassistant.const import ( UnitOfTemperature, UnitOfLength, PERCENTAGE, UnitOfElectricPotential, UnitOfEnergy, UnitOfSpeed )
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

DOMAIN = "stellantis_vehicles"

MOBILE_APPS = {
    "MyPeugeot": {
        "oauth_url": "https://idpcvs.peugeot.com",
        "realm": "clientsB2CPeugeot",
        "scheme": "mymap",
        "client_id": "1eebc2d5-5df3-459b-a624-20abfcf82530",
        "secret": "T5tP7iS0cO8sC0lA2iE2aR7gK6uE5rF3lJ8pC3nO1pR7tL8vU1"
    },
    "MyCitroen": {
        "oauth_url": "https://idpcvs.citroen.com",
        "realm": "clientsB2CCitroen",
        "scheme": "mymacsdk",
        "client_id": "5364defc-80e6-447b-bec6-4af8d1542cae",
        "secret": "iE0cD8bB0yJ0dS6rO3nN1hI2wU7uA5xR4gP7lD6vM0oH0nS8dN"
    },
    "MyDS": {
        "oauth_url": "https://idpcvs.driveds.com",
        "realm": "clientsB2CDS",
        "scheme": "mymdssdk",
        "client_id": "cbf74ee7-a303-4c3d-aba3-29f5994e2dfa",
        "secret": "X6bE6yQ3tH1cG5oA6aW4fS6hK0cR0aK5yN2wE4hP8vL8oW5gU3"
    },
    "MyOpel": {
        "oauth_url": "https://idpcvs.opel.com",
        "realm": "clientsB2COpel",
        "scheme": "mymopsdk",
        "client_id": "07364655-93cb-4194-8158-6b035ac2c24c",
        "secret": "F2kK7lC5kF5qN7tM0wT8kE3cW1dP0wC5pI6vC0sQ5iP5cN8cJ8"
    },
    "MyVauxhall": {
        "oauth_url": "https://idpcvs.vauxhall.co.uk",
        "realm": "clientsB2CVauxhall",
        "scheme": "mymvxsdk",
        "client_id": "122f3511-4f74-4a0c-bcda-af2f3b2e3a65",
        "secret": "N1iY3jO4jI1sF2yS6yJ3rG7xQ4kL4kK1dO3xT5uX6dF3kW8gI6"
    }
}

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

MQTT_SERVER = "mwa.mpsa.com"
MQTT_RESP_TOPIC = "psa/RemoteServices/to/cid/"
MQTT_EVENT_TOPIC = "psa/RemoteServices/events/MPHRTServices/"
MQTT_REQ_TOPIC = "psa/RemoteServices/from/cid/"

CLIENT_ID_QUERY_PARAMS = {
    "client_id": "{#client_id#}",
    "locale": "{#locale_2#}"
}

OAUTH_AUTHORIZE_QUERY_PARAMS = {
    "client_id": "{#client_id#}",
    "response_type": "code",
    "redirect_uri": "{#scheme#}://oauth2redirect/{#locale#}",
    "scope": "openid profile email",
    "locale": "{#locale_2#}"
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
    "redirect_uri": "{#scheme#}://oauth2redirect/{#locale#}",
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
FIELD_SMS_CODE = "sms_code"
FIELD_PIN_CODE = "pin_code"

PLATFORMS = [
    "device_tracker",
    "sensor",
    "binary_sensor",
    "button",
    "number",
    "switch"
]

SENSORS_DEFAULT = {
    "vehicle" : {
        "icon" : "mdi:car",
    },
    "service_battery_voltage" : {
        "icon" : "mdi:car-battery",
        "unit_of_measurement" : PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "data_map" : ["battery", "voltage"]
    },
    "type" : {
        "icon" : "mdi:car-info",
        "data_map" : ["service", "type"]
    },
    "temperature" : {
        "icon" : "mdi:thermometer",
        "unit_of_measurement" : UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "data_map" : ["environment", "air", "temp"]
    },
    "mileage" : {
        "icon" : "mdi:road-variant",
        "unit_of_measurement" : UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "data_map" : ["odometer", "mileage"]
    },
    "autonomy" : {
        "icon" : "mdi:map-marker-distance",
        "unit_of_measurement" : UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "data_map" : ["energies", 0, "autonomy"]
    },
    "battery" : {
        "unit_of_measurement" : PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "data_map" : ["energies", 0, "level"]
    },
    "battery_soh" : {
        "icon" : "mdi:battery-heart-variant",
        "unit_of_measurement" : PERCENTAGE,
        "data_map" : ["energies", 0, "extension", "electric", "battery", "health", "resistance"]
    },
    "battery_charging_rate" : {
        "icon" : "mdi:ev-station",
        "unit_of_measurement" : UnitOfSpeed.KILOMETERS_PER_HOUR,
        "device_class": SensorDeviceClass.SPEED,
        "data_map" : ["energies", 0, "extension", "electric", "charging", "chargingRate"]
    },
    "battery_charging_type" : {
        "icon" : "mdi:lightning-bolt",
        "data_map" : ["energies", 0, "extension", "electric", "charging", "chargingMode"]
    },
    "battery_charging_time" : {
        "icon" : "mdi:battery-clock",
        "device_class" : SensorDeviceClass.TIMESTAMP,
        "data_map" : ["energies", 0, "extension", "electric", "charging", "nextDelayedTime"],
        "available" : {"battery_charging": "InProgress"}
    },
     "battery_charging_end" : {
         "icon" : "mdi:battery-check",
         "device_class" : SensorDeviceClass.TIMESTAMP,
         "data_map" : ["energies", 0, "extension", "electric", "charging", "remainingTime"],
         "available" : {"battery_charging": "InProgress"}
     },
     "battery_capacity" : {
         "icon" : "mdi:battery-arrow-up-outline",
         "unit_of_measurement" : UnitOfEnergy.KILO_WATT_HOUR,
         "device_class" : SensorDeviceClass.ENERGY_STORAGE,
         "data_map" : ["energies", 0, "extension", "electric", "battery", "load", "capacity"],
         "suggested_display_precision": 2
     },
     "battery_residual" : {
         "icon" : "mdi:battery-arrow-up",
         "unit_of_measurement" : UnitOfEnergy.KILO_WATT_HOUR,
         "device_class" : SensorDeviceClass.ENERGY_STORAGE,
         "data_map" : ["energies", 0, "extension", "electric", "battery", "load", "residual"],
         "suggested_display_precision": 2
     }
}

BINARY_SENSORS_DEFAULT = {
    "moving" : {
        "icon" : "mdi:car-traction-control",
        "data_map" : ["kinetic", "moving"],
        "device_class" : BinarySensorDeviceClass.MOTION,
        "on_value": True
    },
    "doors" : {
        "icon" : "mdi:car-door-lock",
        "data_map" : ["alarm", "status", "activation"],
        "device_class" : BinarySensorDeviceClass.LOCK,
        "on_value": "Deactive"
    },
    "battery_plugged" : {
        "icon" : "mdi:power-plug-battery",
        "data_map" : ["energies", 0, "extension", "electric", "charging", "plugged"],
        "device_class" : BinarySensorDeviceClass.PLUG,
        "on_value": True
    },
    "battery_charging" : {
        "icon" : "mdi:battery-charging-medium",
        "data_map" : ["energies", 0, "extension", "electric", "charging", "status"],
        "device_class" : BinarySensorDeviceClass.BATTERY_CHARGING,
        "on_value": "InProgress"
    },
    "engine" : {
        "icon" : "mdi:power",
        "data_map" : ["ignition", "type"],
        "device_class" : BinarySensorDeviceClass.POWER,
        "on_value": "Start"
    },
    "air_conditioning" : {
        "icon" : "mdi:air-conditioner",
        "data_map" : ["preconditioning", "airConditioning", "status"],
        "device_class" : BinarySensorDeviceClass.POWER,
        "on_value": "Active"
    }
}