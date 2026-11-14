"""OTP files written before the PSA client moved to client/psa still load."""
import pickle
import sys
import types

from custom_components.stellantis_vehicles.client.psa.otp import otp as otp_module

LEGACY = "custom_components.stellantis_vehicles.otp"


def test_otp_file_saved_under_the_old_module_path_loads(tmp_path, monkeypatch):
    path = tmp_path / "otp.pickle"
    otp = otp_module.Otp("bb8e981582b0f31353108fb020bead1c", device_id="0123456789abcdef")

    # Pickle it the way the previous layout did: class named by its old module.
    with monkeypatch.context() as legacy:
        legacy.setattr(otp_module.Otp, "__module__", LEGACY + ".otp")
        legacy.setitem(sys.modules, LEGACY, types.ModuleType(LEGACY))
        legacy.setitem(sys.modules, LEGACY + ".otp", otp_module)
        path.write_bytes(pickle.dumps(otp))
    assert LEGACY.encode() + b".otp" in path.read_bytes()
    assert LEGACY + ".otp" not in sys.modules

    loaded = otp_module.load_otp(str(path))
    assert isinstance(loaded, otp_module.Otp)
    assert loaded.device_id == "0123456789abcdef"

    # A file saved now loads as well.
    otp_module.save_otp(loaded, str(path))
    assert isinstance(otp_module.load_otp(str(path)), otp_module.Otp)
