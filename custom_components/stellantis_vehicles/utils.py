import logging
from datetime import UTC, datetime, timezone, timedelta
# import json

from homeassistant.util import dt

_LOGGER = logging.getLogger(__name__)

def get_datetime(date=None):
    if date == None:
        date = datetime.now()
    if date.tzinfo != UTC:
        date = date.astimezone(UTC)
    return date.astimezone(dt.get_default_time_zone())

def date_from_pt_string(pt_string):
    regex = 'PT'
    if pt_string.find("H") != -1:
        regex = regex + "%HH"
    if pt_string.find("M") != -1:
        regex = regex + "%MM"
    if pt_string.find("S") != -1:
        regex = regex + "%SS"
    return datetime.strptime(pt_string, regex)

def timestring_to_datetime(timestring, sum_to_now = False):
    try:
        date = date_from_pt_string(timestring)
        if sum_to_now:
            return get_datetime() + timedelta(hours=date.hour, minutes=date.minute)
        else:
            today = get_datetime().replace(hour=date.hour, minute=date.minute, second=0, microsecond=0)
            tomorrow = (today + timedelta(days=1)).replace(hour=date.hour, minute=date.minute, second=0, microsecond=0)
            if today < get_datetime():
                return tomorrow
            else:
                return today
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
