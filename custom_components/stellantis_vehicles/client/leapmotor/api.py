"""Requests to the Leapmotor cloud: session, signing and endpoints.

Every request is mutually authenticated over TLS: the login (and the
certificate sync remote commands need) with the mobile app's certificate, all
the others with the account certificate the login returns. Requests are also
signed: the login with a plain hash, the others with a key derived from
material the login returns.

The protocol was documented by the MIT-licensed kerniger/leapmotor-ha project
(Copyright (c) 2026 kerniger).
"""
import asyncio
import io
import json
import logging
import os
import random
import ssl
import tempfile
import time
import zipfile
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import aiohttp

from ...exceptions import CommunicationError
from ...utils import SENSITIVE_DATA_FILTER
from . import crypto

from .const import (
    API_BASE_URL,
    LOGIN_URL,
    TOKEN_REFRESH_URL,
    VEHICLES_URL,
    VEHICLE_STATUS_URL,
    CERT_SYNC_URL,
    PIN_VERIFY_URL,
    REMOTE_CONTROL_URL,
    REMOTE_CONTROL_RESULT_URL,
    PICTURE_KEY_URL,
    PICTURE_PACKAGE_URL,
    PICTURE_PACKAGE_FILE,
    CHARGING_PLAN_URL,
    COMMAND_CHARGING_PLAN_ID,
    APP_VERSION,
    APP_SOURCE,
    APP_CHANNEL,
    APP_LANGUAGE,
    APP_DEVICE_TYPE,
    APP_P12_ENC_ALG,
    APP_POLICY_ID,
    LOGIN_REFUSED_CODE,
    STATUS_PATH_ALIASES,
    STATUS_PATH_DEFAULT,
    REMOTE_RESULT_DEFAULT_TIMEOUT_MS,
    REMOTE_RESULT_DEFAULT_INTERVAL_MS
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addFilter(SENSITIVE_DATA_FILTER)

REQUEST_TIMEOUT = 60


class LeapmotorApiError(CommunicationError):
    """The Leapmotor cloud refused or failed a request."""

    def __init__(self, message: str, *, http_status: int | None = None, code: Any = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code

    @property
    def is_token_error(self) -> bool:
        """Whether the session token was rejected (expired, or replaced by another login)."""
        message = str(self).lower()
        return self.http_status == 401 or ("token" in message and any(marker in message for marker in ("invalid", "expire", "unauthorized", "not valid")))


class LeapmotorAuthError(LeapmotorApiError):
    """The account credentials were refused."""


class LeapmotorPinError(LeapmotorApiError):
    """The vehicle PIN was refused."""


class LeapmotorCertificateError(CommunicationError):
    """A client certificate is missing or unusable."""


def build_client_context(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    """TLS context presenting a client certificate. Blocking: run in an executor.

    The gateway's own certificate is self-signed, so it cannot be verified
    against the system trust store (the official app does not either).
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # load_cert_chain only reads files; they are gone as soon as it has.
    with tempfile.TemporaryDirectory() as folder:
        cert_path, key_path = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
        for path, content in ((cert_path, cert_pem), (key_path, key_pem)):
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "wb") as file:
                file.write(content)
        try:
            context.load_cert_chain(cert_path, key_path)
        except (ssl.SSLError, OSError, ValueError) as err:
            raise LeapmotorCertificateError(f"Unusable client certificate: {err}") from err
    return context


def extract_picture(package: bytes) -> bytes | None:
    """The vehicle image inside a picture package, or None if it holds none. Blocking."""
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            names = archive.namelist()
            if PICTURE_PACKAGE_FILE not in names:
                # Another app layout: take the largest image there is.
                images = [info for info in archive.infolist() if info.filename.lower().endswith(".png")]
                if not images:
                    return None
                return archive.read(max(images, key=lambda info: info.file_size))
            return archive.read(PICTURE_PACKAGE_FILE)
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


def _form(params: dict[str, str]) -> str:
    return "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params.items())


class LeapmotorApi:
    def __init__(self, get_session: Callable[[], aiohttp.ClientSession], email: str, password: str, device_id: str, app_cert_pem: bytes, app_key_pem: bytes) -> None:
        self._get_session = get_session
        self._email = email
        self._password = password
        self._login_device_id = device_id
        self._app_cert = (app_cert_pem, app_key_pem)
        self._app_context: ssl.SSLContext | None = None
        self._account_context: ssl.SSLContext | None = None
        self._login_lock = asyncio.Lock()
        # Path segment of the status endpoint that worked, per VIN.
        self._status_paths: dict[str, str] = {}
        # Outcome of the last request per endpoint, for the diagnostics.
        self.last_results: dict[str, dict[str, Any]] = {}
        self._clear_session()

    def _clear_session(self) -> None:
        self.user_id: str | None = None
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._sign_key: bytes | None = None
        self._device_id = self._login_device_id
        self._account_context = None
        self._cert_synced = False

    @property
    def logged_in(self) -> bool:
        return self._token is not None

    # -- transport ---------------------------------------------------------

    def _common_headers(self) -> dict[str, str]:
        return {
            "acceptLanguage": APP_LANGUAGE,
            "channel": APP_CHANNEL,
            "deviceType": APP_DEVICE_TYPE,
            "X-P12_ENC_ALG": APP_P12_ENC_ALG,
            "source": APP_SOURCE,
            "version": APP_VERSION,
            "nonce": str(random.randint(100000, 9999999)),
            "deviceId": self._device_id,
            "timestamp": str(int(time.time() * 1000)),
        }

    def _signed_headers(self, sign_params: dict[str, str]) -> dict[str, str]:
        """Headers of a session request, signed over the app fields and the given parameters, sorted by name."""
        headers = self._common_headers()
        fields = {key: headers[key] for key in ("acceptLanguage", "channel", "deviceId", "deviceType", "nonce", "source", "timestamp", "version")}
        fields.update(sign_params)
        headers["sign"] = crypto.sign_request(self._sign_key, "".join(str(value) for _, value in sorted(fields.items())))
        headers.update({"Content-Type": "application/x-www-form-urlencoded", "userId": self.user_id, "token": self._token})
        return headers

    async def _post_raw(self, label: str, path: str, headers: dict[str, str], body: str, context: ssl.SSLContext) -> tuple[int, bytes]:
        try:
            async with self._get_session().post(API_BASE_URL + path, headers=headers, data=body, ssl=context, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                return response.status, await response.read()
        except asyncio.TimeoutError as err:
            raise LeapmotorApiError(f"Leapmotor {label} timed out") from err
        except aiohttp.ClientError as err:
            raise LeapmotorApiError(f"Leapmotor {label} failed: {err}") from err

    async def _post(self, label: str, path: str, headers: dict[str, str], body: str, context: ssl.SSLContext) -> dict[str, Any]:
        http_status, content = await self._post_raw(label, path, headers, body, context)
        try:
            result = json.loads(content.decode("utf-8", errors="replace"))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            self.last_results[label] = {"http_status": http_status, "code": None, "message": "not JSON", "at": time.time()}
            raise LeapmotorApiError(f"Leapmotor {label} returned an unexpected response (HTTP {http_status})", http_status=http_status)
        # A few endpoints name the result code "result".
        code, message = result.get("code", result.get("result")), result.get("message")
        self.last_results[label] = {"http_status": http_status, "code": code, "message": message, "at": time.time()}
        _LOGGER.debug("Leapmotor %s: HTTP %s code=%s message=%s", label, http_status, code, message)
        if http_status != 200 or code != 0:
            raise LeapmotorApiError(f"Leapmotor {label} failed: {message or f'HTTP {http_status}'}", http_status=http_status, code=code)
        return result

    async def _request(self, label: str, path: str, body_params: dict[str, str] | None = None, sign_params: dict[str, str] | None = None, app_certificate: bool = False) -> dict[str, Any]:
        """One signed session request, as is: no login, no retry."""
        body_params = body_params or {}
        headers = self._signed_headers(body_params if sign_params is None else sign_params)
        context = self._app_context if app_certificate else self._account_context
        return await self._post(label, path, headers, _form(body_params), context)

    async def _session_request(self, label: str, path: str, body_params: dict[str, str] | None = None, sign_params: dict[str, str] | None = None) -> dict[str, Any]:
        """A session request that logs in first if needed and recovers a rejected token once."""
        await self.ensure_login()
        try:
            return await self._request(label, path, body_params, sign_params)
        except LeapmotorApiError as err:
            if not err.is_token_error:
                raise
            await self._recover_session()
            return await self._request(label, path, body_params, sign_params)

    # -- session -----------------------------------------------------------

    async def ensure_login(self) -> None:
        if self._token is None:
            async with self._login_lock:
                if self._token is None:
                    await self._login()

    async def _recover_session(self) -> None:
        """Refresh a rejected token, falling back to a full login."""
        async with self._login_lock:
            if self._refresh_token:
                try:
                    await self._refresh()
                    return
                except LeapmotorApiError as err:
                    _LOGGER.debug("Leapmotor token refresh failed, logging in again: %s", err)
            self._clear_session()
            await self._login()

    async def _login(self) -> None:
        loop = asyncio.get_running_loop()
        if self._app_context is None:
            self._app_context = await loop.run_in_executor(None, build_client_context, *self._app_cert)
        self._clear_session()
        headers = self._common_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["sign"] = crypto.sign_login("".join([
            APP_LANGUAGE, APP_DEVICE_TYPE, self._device_id, "1", self._email, "0", "1",
            headers["nonce"], self._password, APP_POLICY_ID, APP_SOURCE, headers["timestamp"], APP_VERSION,
        ]))
        body = _form({"isRecoverAcct": "0", "password": self._password, "policyId": APP_POLICY_ID, "loginMethod": "1", "email": self._email})
        try:
            result = await self._post("login", LOGIN_URL, headers, body, self._app_context)
        except LeapmotorApiError as err:
            if str(err.code) == LOGIN_REFUSED_CODE:
                raise LeapmotorAuthError(str(err), http_status=err.http_status, code=err.code) from err
            raise
        data = result.get("data") or {}
        try:
            token = str(data["token"])
            sign_key = crypto.derive_sign_key(str(data["signIkm"]), str(data["signSalt"]), str(data["signInfo"]))
            password = crypto.derive_account_p12_password(data["id"], str(data["uid"]))
            certificate = await loop.run_in_executor(None, crypto.load_account_certificate, str(data["base64Cert"]), password)
        except (KeyError, TypeError, ValueError) as err:
            raise LeapmotorCertificateError(f"Could not open the account certificate returned by the login: {err}") from err
        self._account_context = await loop.run_in_executor(None, build_client_context, *certificate)
        self.user_id = str(data["id"])
        self._refresh_token = str(data.get("refreshToken") or "") or None
        self._sign_key = sign_key
        self._device_id = crypto.session_device_id(token, self._login_device_id)
        self._token = token

    async def _refresh(self) -> None:
        current = self._refresh_token
        result = await self._request("token refresh", TOKEN_REFRESH_URL, {"refreshToken": current})
        data = result.get("data") or {}
        if not data.get("token"):
            raise LeapmotorApiError("Leapmotor token refresh returned no token")
        self._token = str(data["token"])
        self._refresh_token = str(data.get("refreshToken") or "") or current

    # -- vehicles ----------------------------------------------------------

    async def vehicles(self) -> list[dict[str, Any]]:
        """The vehicles of the account: its own and the ones shared with it."""
        result = await self._session_request("vehicle list", VEHICLES_URL)
        data = result.get("data") or {}
        vehicles = []
        for bucket, shared in (("bindcars", False), ("sharedcars", True)):
            for item in data.get(bucket) or []:
                if item.get("vin"):
                    vehicles.append({**item, "shared": shared})
        return vehicles

    async def status(self, vin: str, car_type: str | None, car_id: str | None = None) -> dict[str, Any]:
        """The ``data`` of the vehicle status. ``car_id`` is added for a shared vehicle whose plain status is empty."""
        model = str(car_type or "").strip().lower()
        path = self._status_paths.get(vin) or STATUS_PATH_ALIASES.get(model, model or STATUS_PATH_DEFAULT)
        try:
            result = await self._session_request("vehicle status", VEHICLE_STATUS_URL.format(car_type=path), {"vin": vin})
        except LeapmotorApiError as err:
            # A model without its own endpoint answers on the default one.
            if err.http_status != 404 or path == STATUS_PATH_DEFAULT:
                raise
            path = STATUS_PATH_DEFAULT
            result = await self._session_request("vehicle status", VEHICLE_STATUS_URL.format(car_type=path), {"vin": vin})
        self._status_paths[vin] = path
        data = result.get("data") or {}
        if car_id and not data.get("signal"):
            try:
                shared = await self._session_request("vehicle status", VEHICLE_STATUS_URL.format(car_type=path), {"vin": vin, "carId": car_id}, {"vin": vin})
            except LeapmotorApiError:
                shared = {}
            data = shared.get("data") or data
        return data

    async def picture(self, vin: str) -> bytes | None:
        """The image of the vehicle as the app shows it (PNG), or None if the cloud has none."""
        # The request carries the device id of the session: log in before building it.
        await self.ensure_login()
        result = await self._session_request("vehicle picture", PICTURE_KEY_URL, {"deviceID": self._device_id, "vin": vin})
        key = (result.get("data") or {}).get("key")
        if not key:
            return None
        # The package is a binary download: no JSON envelope to read an error from.
        headers = self._signed_headers({"key": str(key)})
        headers.pop("X-P12_ENC_ALG", None)
        http_status, package = await self._post_raw("vehicle picture package", PICTURE_PACKAGE_URL, headers, _form({"key": str(key)}), self._account_context)
        self.last_results["vehicle picture package"] = {"http_status": http_status, "code": None, "message": f"{len(package)} bytes", "at": time.time()}
        if http_status != 200:
            raise LeapmotorApiError(f"Leapmotor vehicle picture package failed: HTTP {http_status}", http_status=http_status)
        return await asyncio.get_running_loop().run_in_executor(None, extract_picture, package)

    async def charging_plan(self, vin: str) -> dict[str, Any]:
        """The charging plan (limit and schedule) as stored by the cloud; {} if there is none."""
        result = await self._session_request("charging plan", CHARGING_PLAN_URL, {"vin": vin, "cmdId": COMMAND_CHARGING_PLAN_ID})
        plan = result.get("data")
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except ValueError:
                plan = None
        return plan if isinstance(plan, dict) else {}

    # -- remote commands ---------------------------------------------------

    async def remote_control(self, vin: str, command_id: str, command_content: str, pin: str) -> dict[str, Any]:
        """Send a remote command; returns the ``data`` describing how to poll its result.

        Everything up to the PIN check is retried once on a rejected token; the
        command itself is sent exactly once.
        """
        await self.ensure_login()
        for attempt in (0, 1):
            try:
                operate_password = crypto.encrypt_pin(pin, self._token)
                if not self._cert_synced:
                    await self._request("certificate sync", CERT_SYNC_URL, app_certificate=True)
                    self._cert_synced = True
                try:
                    await self._request("PIN check", PIN_VERIFY_URL, {"operatePassword": operate_password, "vin": vin})
                except LeapmotorApiError as err:
                    if err.is_token_error:
                        raise
                    raise LeapmotorPinError(str(err), http_status=err.http_status, code=err.code) from err
                break
            except LeapmotorPinError:
                raise
            except LeapmotorApiError as err:
                if attempt or not err.is_token_error:
                    raise
                await self._recover_session()
        result = await self._request("remote command", REMOTE_CONTROL_URL, {"cmdContent": command_content, "vin": vin, "cmdId": command_id, "operatePassword": operate_password})
        return result.get("data") or {}

    async def remote_control_result(self, remote_control_id: str) -> bool:
        """Whether the vehicle has carried out a remote command."""
        result = await self._request("remote command result", REMOTE_CONTROL_RESULT_URL, {"remoteCtlId": remote_control_id})
        return result.get("data") == 1

    async def wait_remote_control(self, control: dict[str, Any]) -> bool:
        """Poll a sent command until the vehicle carried it out; False on timeout."""
        remote_control_id = control.get("remoteCtlId")
        if not remote_control_id:
            # Nothing to wait for: the cloud accepted the command as final.
            return True
        timeout = max(int(control.get("queryRemoteCtlResultTimeout") or REMOTE_RESULT_DEFAULT_TIMEOUT_MS), 1000) / 1000
        interval = max(int(control.get("queryInterval") or REMOTE_RESULT_DEFAULT_INTERVAL_MS), 250) / 1000
        deadline = time.monotonic() + timeout
        while True:
            if await self.remote_control_result(str(remote_control_id)):
                return True
            if time.monotonic() + interval >= deadline:
                return False
            await asyncio.sleep(interval)
