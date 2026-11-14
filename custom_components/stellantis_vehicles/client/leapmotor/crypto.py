"""Cryptography of the Leapmotor cloud API.

The algorithms mirror what the official mobile app does and were documented by
the MIT-licensed kerniger/leapmotor-ha project (Copyright (c) 2026 kerniger).
"""
import base64
import hashlib
import hmac
import json

from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import pkcs12

from .const import PIN_FALLBACK_AES_IV, PIN_FALLBACK_AES_KEY

_SM4_SBOX = bytes.fromhex(
    "d690e9fecce13db716b614c228fb2c052b679a762abe04c3aa44132649860699"
    "9c4250f491ef987a33540b43edcfac62e4b31ca9c908e89580df94fa758f3fa6"
    "4707a7fcf37317ba83593c19e6854fa8686b81b27164da8bf8eb0f4b70569d35"
    "1e240e5e6358d1a225227c3b01217887d40046579fd327524c3602e7a0c4c89e"
    "eabf8ad240c738b5a3f7f2cef96115a1e0ae5da49b341a55ad933230f58cb1e3"
    "1df6e22e8266ca60c02923ab0d534e6fd5db3745defd8e2f03ff6a726d6c5b51"
    "8d1baf92bbddbc7f11d95c411f105ad80ac13188a5cd7bbd2d74d012b8e5b4b0"
    "8969974a0c96777e65b9f109c56ec68418f07dec3adc4d2079ee5f3ed7cb3948"
)

# Round keys of the fixed SM4 key the app derives the account certificate
# password with.
_P12_SM4_ROUND_KEYS = (
    0x818FA553, 0xEBA3318D, 0x5FC3C93A, 0xBD1DADD9,
    0xBB61CAB9, 0x000FD7EA, 0xDC6E0166, 0xDA937279,
    0x607EE786, 0xB548754C, 0x107330E4, 0xEA17C186,
    0x0F56F74B, 0xB21E443C, 0xE1210FE2, 0x009995C8,
    0xE7529A48, 0x6EF474F6, 0x2AB06DF6, 0x43B11BE8,
    0x359D4A14, 0xC29E2CDE, 0x30CF6A3E, 0x79D1C806,
    0x7C502387, 0xAAAB9BC6, 0xF0FE744B, 0x1CAFC872,
    0x95A9D075, 0x88070D58, 0x22800475, 0x8391938B,
)


def _rotate_left(value: int, bits: int) -> int:
    return ((value << bits) & 0xFFFFFFFF) | (value >> (32 - bits))


def _sm4_encrypt_block(block: bytes) -> bytes:
    x = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 16, 4)]
    for round_key in _P12_SM4_ROUND_KEYS:
        t = x[1] ^ x[2] ^ x[3] ^ round_key
        b = int.from_bytes(bytes(_SM4_SBOX[byte] for byte in t.to_bytes(4, "big")), "big")
        new_x = x[0] ^ b ^ _rotate_left(b, 2) ^ _rotate_left(b, 10) ^ _rotate_left(b, 18) ^ _rotate_left(b, 24)
        x = [x[1], x[2], x[3], new_x & 0xFFFFFFFF]
    return b"".join(value.to_bytes(4, "big") for value in reversed(x))


def derive_account_p12_password(account_id: str | int, uid: str) -> str:
    """Password of the account certificate bundle returned by the login."""
    cn = hashlib.md5(str(account_id).encode("ascii")).hexdigest()
    digest = hashlib.sha256(f"{cn}{cn[::2]}{uid[1::2]}".encode("ascii")).digest()
    pad_len = 16 - (len(digest) % 16)
    padded = digest + bytes([pad_len]) * pad_len
    encoded = b"".join(_sm4_encrypt_block(padded[offset:offset + 16]) for offset in range(0, len(padded), 16))
    return base64.b64encode(encoded[:12]).decode("ascii")[:15]


def load_account_certificate(base64_p12: str, password: str) -> tuple[bytes, bytes]:
    """Return the (certificate, private key) PEMs of the account certificate bundle."""
    key, cert, _ = pkcs12.load_key_and_certificates(base64.b64decode(base64_p12), password.encode("utf-8"))
    if key is None or cert is None:
        raise ValueError("The account certificate bundle holds no key or certificate")
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()),
    )


def derive_sign_key(ikm: str, salt: str, info: str) -> bytes:
    """Key the requests of a session are signed with."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode("utf-8"), info=info.encode("utf-8")).derive(ikm.encode("utf-8"))


def sign_login(sign_input: str) -> str:
    return hashlib.sha256(sign_input.encode("utf-8")).hexdigest()


def sign_request(sign_key: bytes, sign_input: str) -> str:
    return hmac.new(sign_key, sign_input.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_pin(pin: str, token: str | None) -> str:
    """Encrypt the vehicle PIN the way remote commands expect it (operatePassword)."""
    if not token:
        key_text, iv_text = PIN_FALLBACK_AES_KEY, PIN_FALLBACK_AES_IV
    elif len(token) < 64:
        raise ValueError("The session token is too short to encrypt the vehicle PIN")
    else:
        key_text = hashlib.md5(token[:32].encode("utf-8")).hexdigest()[8:24]
        iv_text = hashlib.md5(token[32:64].encode("utf-8")).hexdigest()[8:24]
    padder = padding.PKCS7(128).padder()
    padded = padder.update(pin.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key_text.encode("utf-8")), modes.CBC(iv_text.encode("utf-8"))).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")


def session_device_id(token: str | None, fallback: str) -> str:
    """Device id the server bound the session to, read from the token payload."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        parts = str(payload.get("user_name") or "").split(",")
        if len(parts) >= 4 and parts[2]:
            return parts[2]
    except (AttributeError, IndexError, ValueError):
        pass
    return fallback
