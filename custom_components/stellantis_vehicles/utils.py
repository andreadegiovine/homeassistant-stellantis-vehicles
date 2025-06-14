import logging
from datetime import UTC, datetime, timezone, timedelta

from homeassistant.util import dt

_LOGGER = logging.getLogger(__name__)

def get_datetime(date = None):
    if date == None:
        date = datetime.now()
    if date.tzinfo != UTC:
        date = date.astimezone(UTC)
    return date.astimezone(dt.get_default_time_zone())

def datetime_from_isoformat(string):
    return get_datetime(datetime.fromisoformat(string))

def time_from_pt_string(pt_string):
    regex = 'PT'
    if pt_string.find("H") != -1:
        regex = regex + "%HH"
    if pt_string.find("M") != -1:
        regex = regex + "%MM"
    if pt_string.find("S") != -1:
        regex = regex + "%SS"
    return datetime.strptime(pt_string, regex).time()

def time_from_string(string):
    return datetime.strptime(string, "%H:%M:%S").time()

def date_from_pt_string(pt_string, start_date = None):
    if not start_date:
        start_date = get_datetime()
    try:
        time = time_from_pt_string(pt_string)
        return start_date + timedelta(hours=time.hour, minutes=time.minute)

    except Exception as e:
        _LOGGER.error(str(e))
        return None

# def masked_configs(configs = {}):
#     masked_params = ["access_token","customer_id","refresh_token","vehicle_id","vin","client_id","client_secret","basic_token"]
#     masks = {}
#     for key in configs:
#         if isinstance(configs[key], (tuple, list, set, dict)):
#             masks.update(masked_configs(configs[key]))
#         elif key in masked_params:
#             masks.update({configs[key]: str(configs[key][:8]) + "******"})
#     return masks
#
# def masked_log(data, configs = {}):
#     masks = masked_configs(configs)
#     result = json.dumps(data)
#     for mask in masks:
#         result = result.replace(mask, masks[mask])
#     return result
