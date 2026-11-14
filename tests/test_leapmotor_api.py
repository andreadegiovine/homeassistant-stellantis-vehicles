"""The Leapmotor client against a fake cloud that verifies every signature."""
import pytest

from custom_components.stellantis_vehicles.client.leapmotor import crypto
from custom_components.stellantis_vehicles.client.leapmotor.api import (
    LeapmotorApi,
    LeapmotorAuthError,
    LeapmotorCertificateError,
    LeapmotorPinError,
    build_client_context,
)

from .leapmotor_fakes import FakeCloud, PIN, VIN, make_certificate

APP_CERT = make_certificate()[:2]


def _api(cloud, password="secret"):
    return LeapmotorApi(lambda: cloud, "user@example.com", password, "login-device", *APP_CERT)


def test_sm4_block_matches_the_standard_test_vector(monkeypatch):
    """The fixed round keys cannot be checked, the cipher around them can (GB/T 32907 example 1)."""
    fk = (0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC)
    ck = [int.from_bytes(bytes((4 * i + j) * 7 % 256 for j in range(4)), "big") for i in range(32)]
    key = bytes.fromhex("0123456789abcdeffedcba9876543210")
    k = [int.from_bytes(key[i:i + 4], "big") ^ fk[i // 4] for i in range(0, 16, 4)]
    round_keys = []
    for i in range(32):
        t = k[1] ^ k[2] ^ k[3] ^ ck[i]
        b = int.from_bytes(bytes(crypto._SM4_SBOX[byte] for byte in t.to_bytes(4, "big")), "big")
        k = [k[1], k[2], k[3], k[0] ^ b ^ crypto._rotate_left(b, 13) ^ crypto._rotate_left(b, 23)]
        round_keys.append(k[3])
    monkeypatch.setattr(crypto, "_P12_SM4_ROUND_KEYS", tuple(round_keys))
    assert crypto._sm4_encrypt_block(key).hex() == "681edf34d206965e86b3e94f536e4246"


def test_pin_encryption_uses_the_token_and_falls_back_without_one():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    import base64, hashlib
    token = "t" * 32 + "u" * 32 + "rest"
    key = hashlib.md5(b"t" * 32).hexdigest()[8:24].encode()
    iv = hashlib.md5(b"u" * 32).hexdigest()[8:24].encode()
    assert unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(base64.b64decode(crypto.encrypt_pin("1234", token))), 16) == b"1234"
    fallback = AES.new(b"f1cf0c025baec0e2", AES.MODE_CBC, b"6b6a1fe94e133fd7")
    assert unpad(fallback.decrypt(base64.b64decode(crypto.encrypt_pin("1234", None))), 16) == b"1234"
    with pytest.raises(ValueError):
        crypto.encrypt_pin("1234", "short")


def test_an_unusable_certificate_is_reported():
    with pytest.raises(LeapmotorCertificateError):
        build_client_context(b"not a certificate", b"not a key")


async def test_login_then_vehicles_and_status():
    cloud = FakeCloud()
    api = _api(cloud)
    vehicles = await api.vehicles()
    assert [(v["vin"], v["shared"]) for v in vehicles] == [(VIN, True)]
    status = await api.status(VIN, "B10")
    assert status["signal"]["1204"] == 76
    # One login; the B10 is read on the C10 endpoint.
    assert cloud.endpoints() == ["/acct/v1/login", "/vehicle/v1/list", "/vehicle/v1/status/get/c10"]
    # The login presents the app certificate, the rest the account one.
    assert cloud.contexts[0] is not cloud.contexts[1] and cloud.contexts[1] is cloud.contexts[2]


async def test_wrong_credentials_raise_an_auth_error():
    with pytest.raises(LeapmotorAuthError):
        await _api(FakeCloud(), password="wrong").vehicles()


async def test_unknown_model_falls_back_to_the_default_status_endpoint():
    cloud = FakeCloud()
    api = _api(cloud)
    await api.status(VIN, "Z99")
    await api.status(VIN, "Z99")
    assert cloud.endpoints()[1:] == ["/vehicle/v1/status/get/z99", "/vehicle/v1/status/get/c10", "/vehicle/v1/status/get/c10"]


async def test_shared_vehicle_with_empty_status_is_read_with_its_car_id():
    cloud = FakeCloud()
    cloud.shared_only_with_car_id = True
    status = await _api(cloud).status(VIN, "B10", "77")
    assert status["signal"]["1204"] == 76
    assert cloud.calls[-1][1] == {"vin": VIN, "carId": "77"}


async def test_expired_token_is_refreshed_and_the_request_retried():
    cloud = FakeCloud()
    api = _api(cloud)
    await api.vehicles()
    cloud.expire_token_once = True
    assert await api.vehicles()
    assert cloud.endpoints() == ["/acct/v1/login", "/vehicle/v1/list", "/vehicle/v1/list", "/acct/v1/token/refresh", "/vehicle/v1/list"]


async def test_remote_command_checks_the_pin_then_waits_for_the_vehicle():
    cloud = FakeCloud()
    api = _api(cloud)
    control = await api.remote_control(VIN, "110", '{"value":"lock"}', PIN)
    assert await api.wait_remote_control(control) is True
    assert cloud.endpoints() == [
        "/acct/v1/login", "/vehicle/v1/cert/sync", "/vehicle/v1/operPwd/verify", "/vehicle/v1/app/remote/ctl",
        "/vehicle/v1/app/remote/ctl/result/query", "/vehicle/v1/app/remote/ctl/result/query",
    ]
    assert cloud.calls[3][1]["cmdContent"] == '{"value":"lock"}'
    # The certificate sync presents the app certificate again.
    assert cloud.contexts[1] is cloud.contexts[0]

    # The certificate is synced once per session.
    await api.remote_control(VIN, "110", '{"value":"unlock"}', PIN)
    assert cloud.endpoints().count("/vehicle/v1/cert/sync") == 1


async def test_remote_command_is_not_sent_with_a_wrong_pin():
    cloud = FakeCloud()
    with pytest.raises(LeapmotorPinError):
        await _api(cloud).remote_control(VIN, "110", '{"value":"lock"}', "0000")
    assert "/vehicle/v1/app/remote/ctl" not in cloud.endpoints()


async def test_remote_command_result_times_out():
    cloud = FakeCloud()
    cloud.result_after = 1000
    api = _api(cloud)
    control = await api.remote_control(VIN, "120", '{"value":"true"}', PIN)
    assert await api.wait_remote_control(control) is False
