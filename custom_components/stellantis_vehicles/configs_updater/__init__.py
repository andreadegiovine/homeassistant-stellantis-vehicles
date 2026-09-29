import logging
import os
import requests
import bz2
import json
from androguard.core.apk import APK

_LOGGER = logging.getLogger(__name__)

result = {
    "MyPeugeot": {
        "oauth_url": "https://idpcvs.peugeot.com",
        "realm": "clientsB2CPeugeot",
        "scheme": "mymap",
        "configs": {}
    },
    "MyCitroen": {
        "oauth_url": "https://idpcvs.citroen.com",
        "realm": "clientsB2CCitroen",
        "scheme": "mymacsdk",
        "configs": {}
    },
    "MyDS": {
        "oauth_url": "https://idpcvs.driveds.com",
        "realm": "clientsB2CDS",
        "scheme": "mymdssdk",
        "configs": {}
    },
    "MyOpel": {
        "oauth_url": "https://idpcvs.opel.com",
        "realm": "clientsB2COpel",
        "scheme": "mymopsdk",
        "configs": {}
    },
    "MyVauxhall": {
        "oauth_url": "https://idpcvs.vauxhall.co.uk",
        "realm": "clientsB2CVauxhall",
        "scheme": "mymvxsdk",
        "configs": {}
    }
}

def get_file_from_github(filename):
    archive_path =  f"{filename}.bz2"
    file_path = filename
    if os.path.isfile(file_path):
        os.remove(file_path)
    with open(archive_path, 'wb') as f:
        url = f"https://github.com/flobz/psa_apk/raw/main/{filename}.bz2"
        r = requests.get(url,headers={"Accept": "application/vnd.github.VERSION.raw"},stream=True,timeout=10)
        r.raise_for_status()
        for chunk in r.iter_content(1024):
            f.write(chunk)
    with bz2.BZ2File(archive_path, 'rb') as file, open(file_path, 'wb') as out_file:
        out_file.write(file.read())

_LOGGER.error("START")
for app in result:
    filename = app.lower() + ".apk"
    get_file_from_github(filename)
    a = APK(filename)
    package_name = a.get_package()
    resources = a.get_android_resources()
    cultures = json.loads(a.get_file("res/raw/cultures.json"))
    for culture in cultures:
        language = cultures[culture]["languages"][0]
        lan, country = language.split("_")
        try:
            parameters = json.loads(a.get_file("res/raw-{}-r{}/parameters.json".format(lan, country)))
            result[app]["configs"][culture] = {
                "locale": language.replace("_","-"),
                "client_id": parameters["cvsClientId"],
                "client_secret": parameters["cvsSecret"]
            }
        except Exception as e:
            _LOGGER.error("ERROR extracting parameters (%s)", type(e).__name__)
_LOGGER.error("END")
_LOGGER.error("-- UPDATE 'configs.json' CONTENT --")
# Never-class rule (security audit 2026-09-26): client_secret values are not
# logged by default, even though they are vendor-APK-derived and already
# versioned in configs.json. Set CONFIGS_UPDATER_SHOW_SECRETS=1 to print the
# full payload when actually updating configs.json.
import os as _os

if _os.environ.get("CONFIGS_UPDATER_SHOW_SECRETS") == "1":
    _LOGGER.error(json.dumps(result))
else:
    _masked = json.loads(json.dumps(result))
    for _app in _masked.values():
        for _cfg in _app.get("configs", {}).values():
            if "client_secret" in _cfg:
                _cfg["client_secret"] = "***"
    _LOGGER.error(json.dumps(_masked))
    _LOGGER.error("(client_secret masked; set CONFIGS_UPDATER_SHOW_SECRETS=1 for the full payload)")