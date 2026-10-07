"""OAuth token refresh serialization against a real Home Assistant instance."""
import asyncio
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN
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


async def test_late_401_with_already_replaced_token_skips_refresh(hass):
    sv, entry, server = _make(hass, dt_util.utcnow() + timedelta(hours=1))
    await sv.refresh_oauth_token_request("a0")
    # Another poll that was sent with a0 gets its 401 after the rotation.
    await sv.refresh_oauth_token_request("a0")
    assert server["sent"] == ["r0"]
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
