from datetime import UTC, datetime, timezone
import pytz

def get_datetime(date=None):
    if date == None:
        date = datetime.now()
    if date.tzinfo != UTC:
        date = date.astimezone(UTC)
    return date.astimezone(pytz.timezone('Europe/Rome'))

def date_from_pt_string(pt_string):
    regex = 'PT'
    if pt_string.find("H") != -1:
        regex = regex + "%HH"
    if pt_string.find("M") != -1:
        regex = regex + "%MM"
    if pt_string.find("S") != -1:
        regex = regex + "%SS"
    return datetime.strptime(pt_string,regex)

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
        return None