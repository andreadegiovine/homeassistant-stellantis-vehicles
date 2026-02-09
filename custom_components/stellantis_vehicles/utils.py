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

def date_from_pt_string(pt_string, start_date=None):
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
        self._pattern_cache = None

    def add_custom_value(self, value):
        self.custom_values.append(value)
        self._pattern_cache = None

    def add_entry_values(self, entry_data):
        self.entry_data = entry_data
        self._pattern_cache = None

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
        if self._pattern_cache is not None:
            return self._pattern_cache
        sensitive_values = self.get_masked_values(self.entry_data) + self.custom_values
        valid_values = {str(v) for v in sensitive_values if v}
        if not valid_values:
            self._pattern_cache = None
            return None
        sorted_values = sorted(valid_values, key=len, reverse=True)
        pattern_str = '|'.join(map(re.escape, sorted_values))
        self._pattern_cache = re.compile(pattern_str, re.IGNORECASE)
        return self._pattern_cache

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._mask_value(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, (tuple, list)):
                record.args = tuple(self._mask_value(arg) for arg in record.args)
            else:
                record.args = self._mask_value(record.args)

        # record.msg = self._mask_value(record.msg)
        # if hasattr(record, 'msg') and record.args:
        #     record.msg = record.getMessage()
        #     record.args = None

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
            masked_key = self._mask_value(key)
            masked[masked_key] = self._mask_value(value)
        return masked

    def _mask_string(self, value: str) -> str:
        pattern = self.compiled_patterns
        if pattern:
            return pattern.sub(lambda m: self._mask_sensitive_value(m.group(0)), value)
        return value

    def _mask_sensitive_value(self, value: Any) -> str:
        if value is None or value == '':
            return '###'

        value_str = str(value).strip()
        if len(value_str) <= 5:
            return '###'

        return f"{value_str[:5]}###"