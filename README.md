# Stellantis Vehicles
## Requisite
- **Vehicle native mobile app** installed and active;
- **Remote service** compatible vehicle;
- **Use a pc for installation**;

Currently only PSA vehicles are compatibile (Peugeot, Citroen, DS, Opel and Vauxhall).

Currently Stellantis not provide B2C api credentials, this integration use the mobile app auth credentials and flow.

**Inspired by https://github.com/flobz/psa_car_controller (OTP step its a fork).**

## Features
- Get vehicles status;
- Send remote command;
- Set a charge limit (only EV);

## Installation
### Using [HACS](https://hacs.xyz/)
1. Go to HACS section;
2. From the 3 dots menu (top right) click on **Add custom repository**;
3. Add as **Integration** this url https://github.com/andreadegiovine/homeassistant-stellantis-vehicles;
4. Search and install **Stellantis Vehicles** from the HACS integration list;
5. Add this integration from the **Home Assistant** integrations.

### Manually
1. Download this repository;
2. Copy the directory **custom_components/stellantis_vehicles** on your Home Assistant **config/custom_components/stellantis_vehicles**;
3. Restart HomeAssistant;
4. Add this integration from the **Home Assistant** integrations.

## Testing roadmap
### Vehicles tested
- [x] Opel Mokka-e 2022 [e-remote] (me)
- [x] Peugeot e208 2021 [e-remote] (@bgoncal, @Ladida1)
- [x] Vauxhall Mokka-e (@pantha007)
- [x] Citroen C5 X 2022 (@bycippy)
- [ ] Others EV vehicles
- [ ] Others thermal vehicles
- [ ] Multi vehicles account
### Features tested
- [x] Command: **Charge Start/Stop** (E-remote)
- [x] Command: **Air conditioning Start/Stop** (E-remote)
- [ ] Command: **Charge Start/Stop** (Connect Plus)
- [ ] Command: **Air conditioning Start/Stop** (Connect Plus)
- [ ] Command: **Doors** (Connect Plus)
- [ ] Command: **Horn** (Connect Plus)
- [ ] Command: **Lights** (Connect Plus)
- [ ] Sensor: **Battery capacity** accurance
- [ ] Sensor: **Battery residual** accurance
- [ ] Sensor: **Doors** accurance
- [ ] Sensor: **Engine** accurance
- [ ] Sensor: **Moving** accurance

Before any issue request please enable the debug log of this integration by your configuration.yaml:

```
logger:
    default: error
    logs:
        custom_components.stellantis_vehicles: debug
```

and paste the log data on the issue request.

## Screenshot
![Controls](./images/controls.png)
![Sensors](./images/sensors.png)

## Translations
Copy the content of file `custom_components/stellantis_vehicles/translations/en.json`, edit all labels ("key": **"Label"**) and open a issue request choosing Translation request.

## File "configs.json"
This file contains all app api credentials by culture.

To update this file run the Dockerfile under **configs_updater** directory and use the final output as file content.