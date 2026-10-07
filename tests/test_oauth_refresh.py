"""OAuth token refresh serialization against a real Home Assistant instance."""
import asyncio
import json
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import CAR_API_HEADERS, DOMAIN, OAUTH_TOKEN_URL
from custom_components.stellantis_vehicles.stellantis import StellantisVehicles


def _make(hass, expires_in):
    # Let a real reauth flow load without standing up the manifest dependencies.
    hass.config.components.update({"frontend", "http", "webhook"})
    oauth = {"access_token": "a0", "refresh_token": "r0", "expires_in": expires_in.isoformat()}
    entry = MockConfigEntry(domain=DOMAIN, data={"mobile_app": "MyPeugeot", "country_code": "NL", "oauth": oauth}, title="MyPeugeot")
    entry.add_to_hass(hass)
    sv = StellantisVehicles(hass)
    sv._config = {"oauth": dict(oauth)}
    sv.set_entry(entry)
    sv.apply_query_params = lambda url, params: url
    sv.apply_dict_params = lambda d: dict(d)

    # Stellantis token endpoint: each refresh token is single-use.
    server = {"valid": "r0", "issued": 0, "sent": []}

    async def fake_http(url, method, headers=None, *args, **kwargs):
        presented = sv.get_config("oauth")["refresh_token"]
        server["sent"].append(presented)
        await asyncio.sleep(0.01)
        if presented != server["valid"]:
            raise ConfigEntryAuthFailed("invalid_grant - grant is invalid")
        server["issued"] += 1
        server["valid"] = f"r{server['issued']}"
        return {"access_token": f"a{server['issued']}", "refresh_token": server["valid"], "expires_in": 3600}

    sv.make_http_request = fake_http
    return sv, entry, server


async def test_concurrent_refreshes_send_one_request(hass):
    sv, entry, server = _make(hass, dt_util.utcnow() + timedelta(hours=1))
    await asyncio.gather(*(sv.refresh_oauth_token_request() for _ in range(3)))
    assert server["sent"] == ["r0"]
    assert entry.data["oauth"]["refresh_token"] == "r1"

    # A later, non-concurrent refresh still goes out with the rotated token.
    await sv.refresh_oauth_token_request()
    assert server["sent"] == ["r0", "r1"]
    assert entry.data["oauth"]["refresh_token"] == "r2"


async def test_scheduled_refresh_racing_401_retry_does_not_start_reauth(hass):
    # Token close to expiry: the scheduled refresh fires while a poll's
    # 401 retry path is refreshing too.
    sv, entry, server = _make(hass, dt_util.utcnow() + timedelta(minutes=1))
    await asyncio.gather(sv.scheduled_oauth_token_refresh(), sv.refresh_oauth_token_request())
    await hass.async_block_till_done()
    sv.reset_scheduled_oauth_token()

    assert server["sent"] == ["r0"]
    assert entry.data["oauth"]["refresh_token"] == "r1"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body
    async def text(self): return json.dumps(self._body)
    async def json(self): return self._body
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class _StellantisSession:
    """Fake aiohttp session behind the real make_http_request: the token
    endpoint rotates single-use refresh tokens, the API accepts only the
    latest access token and answers 401 otherwise."""
    closed = False

    def __init__(self, sv, server):
        self.sv, self.server = sv, server
        self.valid_access = "none-yet"  # a0 has already expired server-side
        self.bearers = []

    def request(self, method, url, headers=None, **kwargs):
        if url.startswith(OAUTH_TOKEN_URL):
            presented = self.sv.get_config("oauth")["refresh_token"]
            self.server["sent"].append(presented)
            if presented != self.server["valid"]:
                return _Resp(400, {"error": "invalid_grant", "error_description": "grant is invalid"})
            self.server["issued"] += 1
            self.server["valid"] = f"r{self.server['issued']}"
            self.valid_access = f"a{self.server['issued']}"
            return _Resp(200, {"access_token": self.valid_access, "refresh_token": self.server["valid"], "expires_in": 3600})
        self.bearers.append(headers["Authorization"])
        if headers["Authorization"] == f"Bearer {self.valid_access}":
            return _Resp(200, {"ok": True})
        return _Resp(401, {})

    async def close(self):
        pass


async def test_401_path_refreshes_once_and_skips_for_late_401(hass):
    sv, entry, server = _make(hass, dt_util.utcnow() + timedelta(hours=1))
    del sv.make_http_request  # use the real HTTP layer and its 401 retry path
    session = sv._session = _StellantisSession(sv, server)
    # Headers built the way production builds them, while a0 is current.
    stale_headers = StellantisVehicles.apply_dict_params(sv, CAR_API_HEADERS)

    # a0 was rejected: refresh once, retry with a1.
    assert await sv.make_http_request("https://api.example/v1", "GET", dict(stale_headers)) == {"ok": True}
    # Another poll sent with a0 gets its 401 after the rotation: no second refresh.
    assert await sv.make_http_request("https://api.example/v2", "GET", dict(stale_headers)) == {"ok": True}

    assert server["sent"] == ["r0"]
    assert session.bearers == ["Bearer a0", "Bearer a1", "Bearer a0", "Bearer a1"]
    assert entry.data["oauth"]["access_token"] == "a1"


async def test_dead_refresh_token_is_sent_once_and_starts_one_reauth(hass):
    sv, entry, server = _make(hass, dt_util.utcnow() + timedelta(minutes=1))
    server["valid"] = "revoked-elsewhere"
    results = await asyncio.gather(
        sv.scheduled_oauth_token_refresh(),
        sv.refresh_oauth_token_request("a0"),
        sv.refresh_oauth_token_request("a0"),
        return_exceptions=True,
    )
    await hass.async_block_till_done()
    sv.reset_scheduled_oauth_token()

    assert server["sent"] == ["r0"]
    assert results[0] is None  # scheduled path handles it and starts reauth
    assert all(isinstance(r, ConfigEntryAuthFailed) for r in results[1:])
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]
