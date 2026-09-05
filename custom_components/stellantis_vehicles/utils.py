import asyncio
import logging
from collections import deque
from datetime import UTC, datetime, timedelta
from time import monotonic
from functools import wraps
import re
from typing import Any, Dict

from homeassistant.util import dt

from .exceptions import RateLimitException
from .const import (
    FIELD_ANONYMIZE_LOGS
)

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

def replace_string_placeholders(string, placeholders=None):
    if placeholders is None:
        placeholders = {}
    for placeholder in placeholders:
        value = placeholders[placeholder]
        string = string.replace("{" + placeholder + "}", str(value))
    return string

def sort_dict(items, ordered_keys=None):
    if ordered_keys is None or not isinstance(ordered_keys, list):
        return items
    result = {}
    for key in ordered_keys:
        if key in items:
            result[key] = items[key]
    return result

def log_call(func):
    """Log entry and exit of a function at debug level.

    Replaces the hand-written ``---------- START`` / ``---------- END`` markers.
    Works on coroutine functions and plain functions alike (the latter for the
    synchronous paho-mqtt callbacks). The exit line runs from a ``finally``
    block, so it also covers the paths that return early or raise. Entry/exit
    are logged under the decorated function's own module logger, so the lines
    stay next to that module's other logging.
    """
    logger = logging.getLogger(func.__module__)
    name = func.__name__

    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.debug("---------- START %s", name)
            try:
                return await func(*args, **kwargs)
            finally:
                logger.debug("---------- END %s", name)
    else:
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug("---------- START %s", name)
            try:
                return func(*args, **kwargs)
            finally:
                logger.debug("---------- END %s", name)

    return wrapper


def rate_limit(limit: int, every: int):
    """Reject calls once `limit` of them have run within the last `every` seconds.

    Timestamps of the recent successful calls are kept in a deque and pruned on
    each call once they fall outside the window. No background tasks are
    involved, so there is nothing to cancel on unload.
    """
    def limit_decorator(func):
        # Monotonic timestamps of the last (up to `limit`) successful calls.
        calls: deque[float] = deque()

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            now = monotonic()
            while calls and now - calls[0] >= every:
                calls.popleft()
            if len(calls) >= limit:
                _LOGGER.debug("Rate limit exceeded %s: max %s per %ss", func.__name__, limit, every)
                raise RateLimitException("rate_limit")

            calls.append(now)
            return await func(*args, **kwargs)

        return async_wrapper

    return limit_decorator

class SensitiveDataFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.custom_values = []
        self.entry_data = {}
        self.masked_entry_keys = ["access_token", "refresh_token", "oauth_code", "customer_id", "client_id", "client_secret", "basic_token"]
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
        if self.entry_data.get(FIELD_ANONYMIZE_LOGS, False):
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