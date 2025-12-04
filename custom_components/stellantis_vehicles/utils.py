import logging
import asyncio
from datetime import UTC, datetime, timedelta
from asyncio import Semaphore
from functools import wraps
import re
from typing import Any, Dict

from homeassistant.util import dt

from .exceptions import RateLimitException

_LOGGER = logging.getLogger(__name__)

def get_datetime(date = None):
    if date is None:
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
        _LOGGER.warning(str(e))
        return None

def rate_limit(limit: int, every: int):
    def limit_decorator(func):
        semaphore = Semaphore(limit)
        
        async def release_after_delay():
            await asyncio.sleep(every)
            semaphore.release()
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if semaphore._value <= 0:
                _LOGGER.debug(f"Rate limit exceeded {func.__name__}: max {limit} per {every}s")
                raise RateLimitException("rate_limit")

            await semaphore.acquire()
            asyncio.create_task(release_after_delay())
            return await func(*args, **kwargs)
        
        return async_wrapper
    
    return limit_decorator

class SensitiveDataFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.custom_values = []
        self.entry_data = {}
        self.masked_entry_keys = ["access_token", "refresh_token", "oauth_code", "customer_id"]

    def add_custom_value(self, value):
        self.custom_values.append(value)

    def add_entry_values(self, entry_data):
        self.entry_data = entry_data

    def get_masked_values(self, data, result=None):
        if result is None:
            result = []
        for key, value in data.items():
            if isinstance(data[key], dict):
                self.get_masked_values(data[key], result)
            if key in self.masked_entry_keys:
                result.append(value)
        return result

    @property
    def compiled_patterns(self):
        sensitive_values = self.get_masked_values(self.entry_data) + self.custom_values
        return [re.compile(re.escape(value), re.IGNORECASE) for value in sensitive_values]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._mask_value(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, (tuple, list)):
                record.args = tuple(self._mask_value(arg) for arg in record.args)
            else:
                record.args = self._mask_value(record.args)

        return True

    def _mask_value(self, value: Any) -> Any:
        if value is None:
            return value

        if isinstance(value, dict):
            return self._mask_dict(value)
        elif isinstance(value, (list, tuple)):
            return type(value)(self._mask_value(item) for item in value)
        elif isinstance(value, str):
            return self._mask_string(value)

        return value

    def _mask_dict(self, data: Dict) -> Dict:
        masked = {}
        for key, value in data.items():
            masked[key] = self._mask_value(value)
        return masked

    def _mask_string(self, value: str) -> str:
        for pattern in self.compiled_patterns:
            value = pattern.sub(lambda m: self._mask_sensitive_value(m.group(0)), value)
        return value

    def _mask_sensitive_value(self, value: Any) -> str:
        if value is None or value == '':
            return '###'

        value_str = str(value).strip()
        if len(value_str) <= 5:
            return '###'

        return f"{value_str[:5]}###"