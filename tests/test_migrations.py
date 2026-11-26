"""Config entry migrations: an entry from any older release ends up in today's shape."""
import os

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stellantis_vehicles import async_migrate_entry
from custom_components.stellantis_vehicles.const import (
    DOMAIN,
    INTEGRATION_IS_BETA,
    INTEGRATION_VERSION,
)

VIN = "VR3TESTVIN0000001"
CUSTOMER_ID = "AP-0000000001"


def _write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as file:
        file.write(content)


async def test_entry_from_1_1_is_migrated_to_the_current_shape(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    # Files the 1.1 layout left behind: OTP file at the old path, old image
    # folder, and the vehicle picture that tells 1.5/1.6 which VINs exist.
    old_otp = tmp_path / ".storage" / "stellantis_vehicles_otp.pickle"
    _write(str(old_otp), b"otp-state")
    _write(str(tmp_path / "www" / "stellantis-vehicles" / "old.png"))
    _write(str(tmp_path / "www" / DOMAIN / CUSTOMER_ID / f"{VIN}.png"))

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        unique_id="mypeugeotabcde",
        data={
            "mobile_app": "MyPeugeot",
            "country_code": "NL",
            "customer_id": CUSTOMER_ID,
            "access_token": "access-0",
            "refresh_token": "refresh-0",
            "expires_in": "2026-11-25T10:00:00+00:00",
            "text_abrp_token": "abrp-token",
            "number_refresh_interval": 300,
            "switch_notifications": True,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    data = entry.data

    # 1.2: unique_id and OTP file moved; 20260902 then makes the unique_id
    # account + app + country, so one account can hold several brands.
    assert entry.unique_id == f"{CUSTOMER_ID}_MyPeugeot_NL"
    new_otp = tmp_path / ".storage" / DOMAIN / f"{CUSTOMER_ID}_otp.pickle"
    assert new_otp.read_bytes() == b"otp-state"
    assert not old_otp.exists()
    # 1.3: pre-1.3 image folder removed, the current one kept.
    assert not (tmp_path / "www" / "stellantis-vehicles").exists()
    assert (tmp_path / "www" / DOMAIN / CUSTOMER_ID / f"{VIN}.png").exists()
    # 1.4: tokens under "oauth".
    assert data["oauth"] == {
        "access_token": "access-0",
        "refresh_token": "refresh-0",
        "expires_in": "2026-11-25T10:00:00+00:00",
    }
    assert "access_token" not in data
    # 1.5 + 1.6 + 20260802: per-vehicle options under vehicles/<VIN>, the
    # notifications switch promoted to the account-wide key.
    assert data["vehicles"] == {VIN: {"text_abrp_token": "abrp-token", "number_refresh_interval": 300}}
    assert data["notifications"] is True
    for flat_key in ("text_abrp_token", "number_refresh_interval", "switch_notifications", VIN):
        assert flat_key not in data

    if not INTEGRATION_IS_BETA:
        assert (entry.version, entry.minor_version) == (INTEGRATION_VERSION, 1)


async def test_1_2_keeps_an_otp_file_already_at_the_new_path(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    old_otp = tmp_path / ".storage" / "stellantis_vehicles_otp.pickle"
    new_otp = tmp_path / ".storage" / DOMAIN / f"{CUSTOMER_ID}_otp.pickle"
    _write(str(old_otp), b"stale")
    _write(str(new_otp), b"current")

    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, data={
        "mobile_app": "MyPeugeot", "country_code": "NL", "customer_id": CUSTOMER_ID,
        "access_token": "a", "refresh_token": "r", "expires_in": "2026-11-25T10:00:00+00:00",
    })
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)

    assert new_otp.read_bytes() == b"current"
    assert not old_otp.exists()


async def test_flat_vehicle_nodes_move_under_vehicles_without_overwriting_newer_data(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=6, unique_id=f"{CUSTOMER_ID}_MyPeugeot_NL", data={
        "mobile_app": "MyPeugeot", "country_code": "NL", "customer_id": CUSTOMER_ID,
        "oauth": {"access_token": "a"},
        "mqtt": {"access_token": "m"},
        # Flat node from before 20260802, and a "vehicles" node a beta already wrote.
        VIN: {"switch_abrp_sync": False, "text_abrp_token": "old"},
        "vehicles": {VIN: {"text_abrp_token": "new"}},
        # Not a VIN: left where it is.
        "some_option": {"nested": True},
    })
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)

    assert entry.data["vehicles"] == {VIN: {"switch_abrp_sync": False, "text_abrp_token": "new"}}
    assert VIN not in entry.data
    assert entry.data["some_option"] == {"nested": True}
    assert entry.data["mqtt"] == {"access_token": "m"}


async def test_current_entry_is_left_unchanged(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    data = {
        "mobile_app": "MyPeugeot", "country_code": "NL", "customer_id": CUSTOMER_ID,
        "oauth": {"access_token": "a"}, "vehicles": {VIN: {"text_abrp_token": "t"}},
    }
    entry = MockConfigEntry(domain=DOMAIN, version=INTEGRATION_VERSION, minor_version=1,
                            unique_id=f"{CUSTOMER_ID}_MyPeugeot_NL", data=data)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert dict(entry.data) == data
    assert entry.unique_id == f"{CUSTOMER_ID}_MyPeugeot_NL"
    assert entry.version == INTEGRATION_VERSION
