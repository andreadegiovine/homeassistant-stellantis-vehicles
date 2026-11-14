"""A fake Leapmotor cloud for the tests: checks every signature like the real one would."""
import base64
import datetime
import hashlib
import hmac
import io
import json
import zipfile
from urllib.parse import parse_qsl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from custom_components.stellantis_vehicles.client.leapmotor import crypto

ACCOUNT_ID = 424242
ACCOUNT_UID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
SESSION_DEVICE_ID = "session-device"
SIGN = ("ikm-value", "salt-value", "info-value")
VIN = "LFZ00000000000001"
PIN = "1234"
PREFIX = "/carownerservice/oversea"

STATUS = {
    "outdoorTemp": 11,
    "signal": {
        "sts": 1794650400000, "1204": 76, "3260": 301, "1318": 12345, "1319": 0, "1010": 0, "1258": 0,
        "1298": 1, "1277": 0, "1278": 0, "1279": 0, "1280": 0, "1281": 1,
        "1149": 2, "1178": -15.5, "1177": 400, "1200": 95, "1197": 0, "1938": 1,
        "2": 9.19, "3": 45.46,
    },
}


def make_certificate() -> tuple[bytes, bytes, rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    return cert_pem, key_pem, key, cert


def _token(serial: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"user_name": f"x,y,{SESSION_DEVICE_ID},z", "n": serial}).encode()).decode().rstrip("=")
    return f"header.{payload}.{'s' * 64}"


def make_picture_package() -> bytes:
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGBA", (40, 20), (200, 0, 0, 255)).save(image, "PNG")
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("android/xxhdpi/carpic_for_tripsum.png", image.getvalue())
        archive.writestr("android/xxhdpi/other.png", b"x")
    return package.getvalue()


class _Response:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def read(self):
        if isinstance(self._body, bytes):
            return self._body
        return (json.dumps(self._body) if isinstance(self._body, dict) else self._body).encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeCloud:
    """Stands in for the aiohttp session: ``FakeCloud().post(...)``."""

    def __init__(self, email="user@example.com", password="secret"):
        self.email, self.password = email, password
        _, _, key, cert = make_certificate()
        p12_password = crypto.derive_account_p12_password(ACCOUNT_ID, ACCOUNT_UID)
        self.p12 = base64.b64encode(pkcs12.serialize_key_and_certificates(b"account", key, cert, None, serialization.BestAvailableEncryption(p12_password.encode()))).decode()
        self.sign_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=SIGN[1].encode(), info=SIGN[2].encode()).derive(SIGN[0].encode())
        self.tokens = 0
        self.token = None
        self.calls = []          # (endpoint, form params)
        self.contexts = []       # ssl context of each call
        self.expire_token_once = False
        self.status = STATUS
        self.shared_only_with_car_id = False
        self.result_after = 2    # polls before a remote command reports done
        self._polls = 0
        self.closed = False
        self.has_picture = True

    async def close(self):
        self.closed = True

    def post(self, url, headers=None, data=None, ssl=None, timeout=None):
        path = url.split(".de", 1)[1]
        params = dict(parse_qsl(data or "", keep_blank_values=True))
        endpoint = path.removeprefix(PREFIX)
        self.calls.append((endpoint, params))
        self.contexts.append(ssl)
        return _Response(*self._handle(endpoint, headers, params))

    def _ok(self, data=None):
        return 200, {"code": 0, "message": "ok", "data": data}

    def _handle(self, endpoint, headers, params):
        if endpoint == "/acct/v1/login":
            expected = hashlib.sha256("".join([
                headers["acceptLanguage"], headers["deviceType"], headers["deviceId"], "1", params["email"], "0", "1",
                headers["nonce"], params["password"], params["policyId"], headers["source"], headers["timestamp"], headers["version"],
            ]).encode()).hexdigest()
            assert headers["sign"] == expected, "bad login signature"
            if (params["email"], params["password"]) != (self.email, self.password):
                return 200, {"code": 302010108, "message": "wrong account or password"}
            self.tokens += 1
            self.token = _token(self.tokens)
            return self._ok({"id": ACCOUNT_ID, "uid": ACCOUNT_UID, "token": self.token, "refreshToken": f"refresh-{self.tokens}",
                             "signIkm": SIGN[0], "signSalt": SIGN[1], "signInfo": SIGN[2], "base64Cert": self.p12})

        # Every other request: session headers and an HMAC over the sorted fields.
        assert headers["deviceId"] == SESSION_DEVICE_ID
        assert headers["userId"] == str(ACCOUNT_ID)
        signed = dict(params)
        if endpoint.startswith("/vehicle/v1/status/get/"):
            signed.pop("carId", None)
        fields = {key: headers[key] for key in ("acceptLanguage", "channel", "deviceId", "deviceType", "nonce", "source", "timestamp", "version")}
        fields.update(signed)
        expected = hmac.new(self.sign_key, "".join(value for _, value in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
        assert headers["sign"] == expected, f"bad signature for {endpoint}"

        if endpoint == "/acct/v1/token/refresh":
            assert params["refreshToken"] == f"refresh-{self.tokens}"
            self.tokens += 1
            self.token = _token(self.tokens)
            return self._ok({"token": self.token, "refreshToken": f"refresh-{self.tokens}"})
        if self.expire_token_once:
            self.expire_token_once = False
            return 200, {"code": 401001, "message": "token expired"}
        assert headers["token"] == self.token, "stale token"
        if endpoint == "/vehicle/v1/list":
            return self._ok({"bindcars": [], "sharedcars": [{"vin": VIN, "carId": 77, "carType": "B10"}]})
        if endpoint.startswith("/vehicle/v1/status/get/"):
            if endpoint.rsplit("/", 1)[1] != "c10":
                return 404, {"code": 404, "message": "not found"}
            if self.shared_only_with_car_id and "carId" not in params:
                return self._ok({})
            return self._ok(self.status)
        if endpoint == "/vehicle/v1/carpicture/key":
            assert params == {"deviceID": SESSION_DEVICE_ID, "vin": VIN}
            return self._ok({"key": "pic-key"} if self.has_picture else {})
        if endpoint == "/vehicle/v1/carpicture/package":
            assert params == {"key": "pic-key"} and "X-P12_ENC_ALG" not in headers
            return 200, make_picture_package()
        if endpoint == "/vehicle/v1/cert/sync":
            return self._ok()
        if endpoint == "/vehicle/v1/operPwd/verify":
            if params["operatePassword"] != crypto.encrypt_pin(PIN, self.token):
                return 200, {"code": 1, "message": "wrong operate password"}
            return self._ok()
        if endpoint == "/vehicle/v1/app/remote/ctl":
            assert params["operatePassword"] == crypto.encrypt_pin(PIN, self.token)
            self._polls = 0
            return self._ok({"remoteCtlId": "ctl-1", "queryInterval": 250, "queryRemoteCtlResultTimeout": 1500})
        if endpoint == "/vehicle/v1/app/remote/ctl/result/query":
            self._polls += 1
            return self._ok(1 if self._polls >= self.result_after else 0)
        return 404, {"code": 404, "message": "unknown endpoint"}

    def endpoints(self):
        return [endpoint for endpoint, _ in self.calls]
