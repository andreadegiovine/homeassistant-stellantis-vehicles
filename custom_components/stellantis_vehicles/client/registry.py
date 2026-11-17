"""Maps a config entry to the cloud client that serves it."""
from homeassistant.core import HomeAssistant

from ..const import FIELD_CLIENT, CLIENT_PSA
from ..interfaces import VehiclesClient
from .psa.client import StellantisVehicles
from .leapmotor.client import LeapmotorVehicles
from .leapmotor.const import CLIENT_LEAPMOTOR

CLIENTS: dict[str, type[VehiclesClient]] = {
    CLIENT_PSA: StellantisVehicles,
    CLIENT_LEAPMOTOR: LeapmotorVehicles,
}


def create_client(hass: HomeAssistant, data: dict) -> VehiclesClient:
    """Build the client for a config entry's data.

    Entries created before clients existed carry no client key and are PSA.
    """
    return CLIENTS[data.get(FIELD_CLIENT, CLIENT_PSA)](hass)
