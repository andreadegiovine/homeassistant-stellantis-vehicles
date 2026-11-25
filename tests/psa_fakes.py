"""A scripted fake of the Stellantis (PSA) HTTP API for the tests."""
import json
from datetime import timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles.const import DOMAIN
from custom_components.stellantis_vehicles.client.psa.client import StellantisVehicles

VIN = "VR3TESTVIN0000001"
CUSTOMER_ID = "AP-0000000001"


class Resp:
    """Just enough of aiohttp's response for make_http_request."""

    def __init__(self, status, body=None):
        self.status = status
        self._body = body

    async def text(self):
        return "" if self._body is None else json.dumps(self._body)

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Answers each request from a queue of responses (or exceptions), in order."""

    closed = False

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def close(self):
        self.closed = True


def make_client(hass, session=None, **config):
    """A StellantisVehicles for a MyPeugeot NL account, with its config entry."""
    # Let a real reauth flow load without standing up the manifest dependencies.
    hass.config.components.update({"frontend", "http", "webhook"})
    oauth = {
        "access_token": "access-0",
        "refresh_token": "refresh-0",
        "expires_in": (dt_util.utcnow() + timedelta(hours=1)).isoformat(),
    }
    data = {
        "mobile_app": "MyPeugeot",
        "country_code": "NL",
        "customer_id": CUSTOMER_ID,
        "oauth": oauth,
        **config,
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data, title="MyPeugeot")
    entry.add_to_hass(hass)
    client = StellantisVehicles(hass)
    client.save_config(data)
    client.set_entry(entry)
    # A failed request closes the session; the next one must get the fake back,
    # not a real aiohttp session.
    fake = session or FakeSession()

    def start_session():
        if client._session is None:
            client._session = fake

    client.start_session = start_session
    client._session = fake
    return client, entry
