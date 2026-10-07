"""Credentials never reach the log, whatever the anonymize option."""
import json
import logging

import pytest

from custom_components.stellantis_vehicles.exceptions import CommunicationError
from custom_components.stellantis_vehicles.stellantis import StellantisOauth
from custom_components.stellantis_vehicles.utils import SENSITIVE_DATA_FILTER

EMAIL = "jane.doe@example.com"
PASSWORD = "Hunter2*Secret-Passw0rd"
WORKER_ERROR = {"message": "Timeout 30000ms exceeded. [abd2ae36]", "code": 400}


class _Resp:
    status = 400
    async def text(self): return json.dumps(WORKER_ERROR)
    async def json(self): return WORKER_ERROR
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class _Session:
    closed = False
    def request(self, *args, **kwargs): return _Resp()
    async def close(self): pass


@pytest.fixture(autouse=True)
def fresh_filter(monkeypatch):
    for attr, value in (("_entry_values", {}), ("_entry_extra", {}), ("_entry_anonymize", {}),
                        ("_custom_values", {}), ("_pattern_cache", None)):
        monkeypatch.setattr(SENSITIVE_DATA_FILTER, attr, value)


async def _failed_login_log(hass, caplog, anonymize):
    if anonymize is not None:
        SENSITIVE_DATA_FILTER.set_entry_values("entry", {"anonymize_logs": anonymize})
    oauth = StellantisOauth(hass)
    oauth._session = _Session()
    oauth.get_oauth_url = lambda: "https://idpcvs.peugeot.com/am/oauth2/authorize"
    caplog.set_level(logging.DEBUG, logger="custom_components.stellantis_vehicles")
    with pytest.raises(CommunicationError):
        await oauth.get_oauth_code(EMAIL, PASSWORD, "https://worker.example")
    return "\n".join(r.getMessage() for r in caplog.records)


MODES = pytest.mark.parametrize("anonymize", [None, False, True], ids=["config-flow", "anonymize-off", "anonymize-on"])


@MODES
async def test_failed_login_never_logs_the_credentials(hass, caplog, anonymize):
    text = await _failed_login_log(hass, caplog, anonymize)
    assert "failed with status 400" in text
    assert "'url': 'https://idpcvs.peugeot.com/am/oauth2/authorize', 'email': '###', 'password': '###'" in text
    assert PASSWORD[:4] not in text and EMAIL[:5] not in text


@MODES
async def test_failed_otp_request_never_logs_the_code(hass, caplog, anonymize):
    if anonymize is not None:
        SENSITIVE_DATA_FILTER.set_entry_values("entry", {"anonymize_logs": anonymize})
    oauth = StellantisOauth(hass)
    oauth._session = _Session()
    caplog.set_level(logging.DEBUG, logger="custom_components.stellantis_vehicles")
    with pytest.raises(CommunicationError):
        await oauth.make_http_request("https://otp.example", "POST", None, None, {"grant_type": "password", "password": "482913"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "json={'grant_type': 'password', 'password': '###'}" in text
    assert "482913" not in text
