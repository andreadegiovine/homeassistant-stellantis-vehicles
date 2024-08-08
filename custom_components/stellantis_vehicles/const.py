from homeassistant.const import ( UnitOfTemperature, UnitOfLength, PERCENTAGE, UnitOfElectricPotential )
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

DOMAIN = "stellantis_vehicles"

PLATFORMS = ["sensor"]

MOBILE_APPS = {
    "MyPeugeot": {
        "oauth_url": "https://idpcvs.peugeot.com",
        "realm": "clientsB2CPeugeot",
        "scheme": "mymap"
    },
    "MyCitroen": {
        "oauth_url": "https://idpcvs.citroen.com",
        "realm": "clientsB2CCitroen",
        "scheme": "mymacsdk"
    },
    "MyDS": {
        "oauth_url": "https://idpcvs.driveds.com",
        "realm": "clientsB2CDS",
        "scheme": "mymdssdk"
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
        "scheme": "mymvxsdk"
    }
}

OAUTH_BASE_URL = "{#oauth_url#}/am/oauth2"
OAUTH_AUTHORIZE_URL = OAUTH_BASE_URL + "/authorize"
OAUTH_TOKEN_URL = OAUTH_BASE_URL + "/access_token"

CAR_API_BASE_URL = "https://api.groupe-psa.com/connectedcar/v4/user"
CAR_API_CALLBACK_URL = CAR_API_BASE_URL + "/callbacks"
CAR_API_DELETE_CALLBACK_URL = CAR_API_CALLBACK_URL + "/{#callback_id#}"
CAR_API_VEHICLES_URL = CAR_API_BASE_URL + "/vehicles"
CAR_API_GET_VEHICLE_STATUS_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/status"
CAR_API_SEND_COMMAND_URL = CAR_API_VEHICLES_URL + "/{#vehicle_id#}/callbacks/{#callback_id#}/remotes"
CAR_API_CHECK_COMMAND_URL = CAR_API_SEND_COMMAND_URL + "/{#remote_action_id#}"

CLIENT_ID_QUERY_PARAM = {
    "client_id": "{#client_id#}",
    "locale": "{#locale_2#}"
}

OAUTH_AUTHORIZE_QUERY_PARAMS = {
    "client_id": "{#client_id#}",
    "response_type": "code",
    "redirect_uri": "{#scheme#}://oauth2redirect/{#locale#}",
    "scope": "openid profile",
    "locale": "{#locale_2#}"
}

OAUTH_TOKEN_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": "Basic {#basic_token#}",
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

WEBHOOK_ID = "stellantis-vehicles"

PLATFORMS = [
    "device_tracker",
    "sensor",
    "binary_sensor",
    "button"
]

SENSORS_DEFAULT = {
    "vehicle" : {
        "icon" : "mdi:car",
    },
    "service_battery_voltage" : {
        "icon" : "mdi:car-battery",
        "unit_of_measurement" : UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
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
        "data_map" : ["energy", 0, "autonomy"]
    },
    "battery" : {
#         "icon" : "mdi:battery",
        "unit_of_measurement" : PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "data_map" : ["energy", 0, "level"]
    },
    "battery_soh" : {
        "icon" : "mdi:battery-heart-variant",
        "unit_of_measurement" : PERCENTAGE,
        "data_map" : ["energy", 0, "battery", "health", "resistance"]
    },
    "battery_charging_rate" : {
        "icon" : "mdi:ev-station",
        "data_map" : ["energy", 0, "charging", "chargingRate"]
    },
    "battery_charging_time" : {
        "icon" : "mdi:clock-time-eight-outline",
        "data_map" : ["energy", 0, "charging", "nextDelayedTime"],
        "device_class" : SensorDeviceClass.TIMESTAMP
    },
     "battery_charging_end" : {
         "icon" : "mdi:battery-charging-high",
         "data_map" : ["energy", 0, "charging", "remaining_time"],
         "device_class" : SensorDeviceClass.TIMESTAMP
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
        "data_map" : ["energy", 0, "charging", "plugged"],
        "device_class" : BinarySensorDeviceClass.PLUG,
        "on_value": True
    },
    "battery_charging" : {
        "icon" : "mdi:battery-charging-medium",
        "data_map" : ["energy", 0, "charging", "status"],
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