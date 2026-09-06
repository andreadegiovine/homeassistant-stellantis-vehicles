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
    try:
        return datetime.strptime(string, "%H:%M:%S").time()
    except (AttributeError, TypeError, ValueError) as e:
        _LOGGER.warning("Could not parse time '%s': %s", string, e)
        return None

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
    """Mask sensitive strings (tokens, VINs, customer ids) in log records.

    A single shared instance sits on each of this integration's module loggers
    (attached once, at import time). It therefore has to hold the sensitive
    values of *every* loaded config entry at once, and it must not let that set
    grow without bound over the process lifetime - both points were behind the
    runaway CPU use in issue #414.

    Design:
    - ``_entry_values`` keeps, per ``entry_id``, the set of sensitive strings
      extracted from that entry's stored config. It is *replaced* wholesale on
      every ``set_entry_values`` call (the integration wires that to every
      ``save_config``), so a rotated oauth/mqtt token supersedes the previous
      one instead of piling up. Keyed by ``entry_id`` so several accounts do
      not overwrite each other's tokens.
    - ``_custom_values`` is a bounded, insertion-ordered set for values seen
      outside the stored config (the OAuth code / id_token during the auth
      flow, vehicle ids from API responses). It is capped because those values
      rotate; anything that must stay masked for an entry's lifetime lives in
      ``_entry_values``.
    - Every mutating method rebinds its container instead of mutating it in
      place, so the filter can be read from the paho-mqtt network thread while
      the event loop updates it, without a "changed size during iteration".
    """

    MASKED_ENTRY_KEYS = ("access_token", "refresh_token", "oauth_code", "customer_id")
    CUSTOM_VALUES_LIMIT = 128

    def __init__(self) -> None:
        super().__init__()
        self._entry_values: dict[str, set[str]] = {}
        self._entry_anonymize: dict[str, bool] = {}
        self._custom_values: dict[str, None] = {}
        self._pattern_cache: re.Pattern[str] | None = None

    def get_masked_values(self, data:dict[str, Any], result:list[Any] | None = None) -> list[Any]:
        if result is None:
            result = []
        for key, value in data.items():
            if isinstance(value, dict):
                self.get_masked_values(value, result)
            if key in self.MASKED_ENTRY_KEYS:
                result.append(value)
        return result

    def set_entry_values(self, entry_id:str, entry_data:dict[str, Any] | None) -> None:
        """Store (replacing any previous snapshot) one config entry's sensitive
        values and its anonymize flag."""
        entry_data = entry_data or {}
        values = {str(v) for v in self.get_masked_values(entry_data) if v}
        # VINs are the *keys* of the per-vehicle config node, not values, so
        # get_masked_values() does not see them.
        values |= {str(vin) for vin in (entry_data.get("vehicles") or {}) if vin}
        self._entry_values = {**self._entry_values, entry_id: values}
        self._entry_anonymize = {
            **self._entry_anonymize,
            entry_id: bool(entry_data.get(FIELD_ANONYMIZE_LOGS, False)),
        }
        self._pattern_cache = None

    def remove_entry_values(self, entry_id:str) -> None:
        """Forget a config entry on unload so its (now invalid) tokens stop
        being masked and the compiled pattern shrinks back."""
        if entry_id not in self._entry_values:
            return
        self._entry_values = {k: v for k, v in self._entry_values.items() if k != entry_id}
        self._entry_anonymize = {k: v for k, v in self._entry_anonymize.items() if k != entry_id}
        # Nothing loaded any more -> drop the process-global extras too.
        if not self._entry_values:
            self._custom_values = {}
        self._pattern_cache = None

    def add_custom_value(self, value:Any) -> None:
        if not value:
            return
        text = str(value)
        if text in self._custom_values:
            return
        updated = dict(self._custom_values)
        updated[text] = None
        while len(updated) > self.CUSTOM_VALUES_LIMIT:
            del updated[next(iter(updated))]
        self._custom_values = updated
        self._pattern_cache = None

    @property
    def compiled_patterns(self) -> re.Pattern[str] | None:
        if self._pattern_cache is not None:
            return self._pattern_cache
        # Snapshot the container references once - they may be rebound from
        # another thread while this runs.
        entry_values = self._entry_values
        valid_values = set(self._custom_values)
        for values in entry_values.values():
            valid_values |= values
        valid_values = {v for v in valid_values if v}
        if not valid_values:
            self._pattern_cache = None
            return None
        sorted_values = sorted(valid_values, key=len, reverse=True)
        pattern_str = '|'.join(map(re.escape, sorted_values))
        self._pattern_cache = re.compile(pattern_str, re.IGNORECASE)
        return self._pattern_cache

    def filter(self, record: logging.LogRecord) -> bool:
        if any(self._entry_anonymize.values()):
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


# One shared filter instance, attached to each module logger exactly once (at
# import time). Its sensitive values are keyed by config entry, added via
# set_entry_values() on every save_config() and dropped via remove_entry_values()
# on unload, so it stays correct with several accounts loaded and its compiled
# pattern does not grow over the process lifetime.
# Previously StellantisBase.__init__ built a new one and attached it to the
# stellantis logger, and the coordinator attached it to base's logger too;
# nothing removed them, so every config-flow attempt and every entry reload left
# another filter stacked on those loggers.
SENSITIVE_DATA_FILTER = SensitiveDataFilter()
