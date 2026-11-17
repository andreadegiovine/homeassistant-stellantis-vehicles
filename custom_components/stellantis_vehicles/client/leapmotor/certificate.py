"""The mobile app's TLS certificate the Leapmotor login requires.

It is downloaded once, when a Leapmotor account is set up, and kept in the
Home Assistant storage folder; the integration does not ship it.
"""
import logging
import os

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import DOMAIN
from .api import LeapmotorCertificateError

from .const import (
    APP_CERT_URL,
    APP_KEY_URL,
    APP_CERT_FOLDER,
    APP_CERT_FILENAME,
    APP_KEY_FILENAME
)

_LOGGER = logging.getLogger(__name__)


def certificate_folder(hass: HomeAssistant) -> str:
    return os.path.join(hass.config.path(), ".storage", DOMAIN, APP_CERT_FOLDER)


def _validate(cert_pem: bytes, key_pem: bytes) -> None:
    """Raise unless the two PEMs are a certificate and the private key that goes with it."""
    try:
        certificate = x509.load_pem_x509_certificate(cert_pem)
        key = serialization.load_pem_private_key(key_pem, password=None)
    except (ValueError, TypeError) as err:
        raise LeapmotorCertificateError(f"The app certificate files are not a valid certificate and key: {err}") from err
    public = serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    if certificate.public_key().public_bytes(*public) != key.public_key().public_bytes(*public):
        raise LeapmotorCertificateError("The app certificate and its private key do not match")


def _read(folder: str) -> tuple[bytes, bytes] | None:
    paths = os.path.join(folder, APP_CERT_FILENAME), os.path.join(folder, APP_KEY_FILENAME)
    if not all(os.path.isfile(path) for path in paths):
        return None
    contents = []
    for path in paths:
        with open(path, "rb") as file:
            contents.append(file.read())
    _validate(*contents)
    return contents[0], contents[1]


def _write(folder: str, cert_pem: bytes, key_pem: bytes) -> None:
    os.makedirs(folder, exist_ok=True)
    for filename, content in ((APP_CERT_FILENAME, cert_pem), (APP_KEY_FILENAME, key_pem)):
        with os.fdopen(os.open(os.path.join(folder, filename), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as file:
            file.write(content)


async def _download(hass: HomeAssistant, url: str) -> bytes:
    try:
        async with async_get_clientsession(hass).get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            response.raise_for_status()
            return await response.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise LeapmotorCertificateError(f"Could not download the app certificate from {url}: {err}") from err


async def async_load_app_certificate(hass: HomeAssistant) -> tuple[bytes, bytes] | None:
    """Return the stored (certificate, key) PEMs, or None if they were never downloaded."""
    return await hass.async_add_executor_job(_read, certificate_folder(hass))


async def async_ensure_app_certificate(hass: HomeAssistant) -> tuple[bytes, bytes]:
    """Return the app certificate, downloading and storing it first if it is not there yet."""
    stored = await async_load_app_certificate(hass)
    if stored:
        return stored
    cert_pem = await _download(hass, APP_CERT_URL)
    key_pem = await _download(hass, APP_KEY_URL)
    await hass.async_add_executor_job(_validate, cert_pem, key_pem)
    await hass.async_add_executor_job(_write, certificate_folder(hass), cert_pem, key_pem)
    _LOGGER.info("Leapmotor app certificate downloaded and stored in %s", certificate_folder(hass))
    return cert_pem, key_pem
