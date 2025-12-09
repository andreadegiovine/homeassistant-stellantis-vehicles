# HomeAssistant - Stellantis Vehicles
[![Active installations](https://img.shields.io/badge/active_installations-2200-%2318BCF2?style=for-the-badge&logo=homeassistant)](#)  
[![Last version](https://img.shields.io/github/v/release/andreadegiovine/homeassistant-stellantis-vehicles?style=for-the-badge&logo=github&label=last%20version&color=green)](#)

- [Requirements](#requirements)
- [Features](#features)
- [Installation](#installation)
- [Screenshot](#screenshot)
- [OAuth2 Code](#oauth2-code)
- [Commands](#commands)
- [Battery capacity / residual sensors](#battery-capacity--residual-sensors)
- [Errors](#errors)
- [ABRP - A Better Routeplanner](#abrp---a-better-routeplanner)
- [Support the project](#support-the-project)

> Currently only <ins>PSA vehicles</ins> are compatibile.

| Peugeot                              | Citroën                              | DS                         | Opel                           | Vauxhall                               |
|--------------------------------------|--------------------------------------|----------------------------|--------------------------------|----------------------------------------|
| ![MyPeugeot](./images/MyPeugeot.png) | ![MyCitroen](./images/MyCitroen.png) | ![MyDS](./images/MyDS.png) | ![MyOpel](./images/MyOpel.png) | ![MyVauxhall](./images/MyVauxhall.png) |

## Requirements
Get status:
- **Vehicle native mobile app** installed and active;
- **Use a pc for autentication**;

Send remote commands:
- Get status requirements;
- **Remote service** actived (E-remote or Connect Plus);

> Currently Stellantis not provide B2C api credentials, this integration use the mobile apps api credentials and login flow.

## Features
|                            | Electric / Hybrid | Thermic | E-remote control | Remote control  | Connect Plus |
|----------------------------|:-----------------:|:-------:|:----------------:|:---------------:|:------------:|
| Get status                 |        ✔️         |   ✔️    |        ✔️        |                 |      ✔️      |
| Wake up                    |        ✔️         |   ✔️    |        ✔️        |                 |      ✔️      |
| ABRP sync                  |        ✔️         |   ✔️    |        ✔️        |                 |      ✔️      |
| Preconditioning start/stop |        ✔️         |   ✔️    |        ✔️        |                 |      ✔️      |
| Doors open/close           |        ✔️         |   ✔️    |                  |       ✔️        |      ✔️      |
| Flash lights               |        ✔️         |   ✔️    |                  |       ✔️        |      ✔️      |
| Honk the horn              |        ✔️         |   ✔️    |                  |       ✔️        |      ✔️      |
| Charging start/stop        |        ✔️         |         |        ✔️        |                 |      ✔️      |
| Charging limit             |        ✔️         |         |        ✔️        |                 |      ✔️      |

## Installation
<details><summary><b>Using HACS</b></summary>

1. Go to [HACS](https://hacs.xyz/) section;
2. Search and install **Stellantis Vehicles** from the HACS integration list;
3. Add this integration from the **Home Assistant** integrations.

</details>
<details><summary><b>Manually</b></summary>

1. Download this repository;
2. Copy the directory **custom_components/stellantis_vehicles** on your Home Assistant **config/custom_components/stellantis_vehicles**;
3. Restart HomeAssistant;
4. Add this integration from the **Home Assistant** integrations.

</details>

## Screenshot
![Controls](./images/controls.png)
![Sensors](./images/sensors.png)

## OAuth2 Code
### Remote service
To authenticate your account, this [remote service](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles-worker) is used to simulate browser login on the official website. 

<ins>**Your credentials are not stored or shared**</ins>

### Manual
<details><summary><b>Using browser console</b></summary>

As described on config flow, please get the right code from the mobile app redirect like this example (Chrome browser):

![Oauth2](./images/oauth2-code.png)

</details>
<details><summary><b>Using python tool</b></summary>

Thanks to [@benbox69](https://github.com/benbox69) for creating this awesome Python tool to fetch oauth code without using browser console: [stellantis-oauth-helper](https://github.com/benbox69/stellantis-oauth-helper)

</details>

## Commands
To use remote commands, the "E-remote" or "Connect Plus" service must be activated and configured in the vehicle.

How to complete the OTP step and activate remote commands:
<details><summary><b>New configuration</b></summary>

![Enable remote commands](./images/remote-commands-1.png)

</details>
<details><summary><b>Existing configuration</b></summary>

![Enable remote commands](./images/remote-commands-2.png)

</details>

### WakeUp
For some vehicles no updates are received a few minutes after the engine is turned off. Use automations like these to schedule the vehicle wake up:

```yaml
- id: "standby_wakeup"
  alias: Vehicle standby WakeUp (every 1 hour)
  description: ""
  mode: single
  triggers:
    - trigger: time_pattern
      hours: /1
  conditions:
    - condition: state
      entity_id: binary_sensor.#####VIN#####_battery_charging
      state: "off"
  actions:
    - action: button.press
      metadata: {}
      data: {}
      target:
        entity_id: button.#####VIN#####_wakeup
```

```yaml
- id: "charging_wakeup"
  alias: Vehicle charging WakeUp (every 5 minutes)
  description: ""
  mode: single
  triggers:
    - trigger: time_pattern
      minutes: /5
  conditions:
    - condition: state
      entity_id: binary_sensor.#####VIN#####_battery_charging
      state: "on"
  actions:
    - action: button.press
      metadata: {}
      data: {}
      target:
        entity_id: button.#####VIN#####_wakeup
```
\* the entity names above are in english, please use your language entity names.

<ins>**Some users report that performing too many wakeups drains the service battery, making some features unavailable (such as keyless entry)**</ins>.

### Air conditioning Start/Stop
As described in the Stellantis apps, the command is enabled when:
1. The vehicle engine is off;
2. The vehicle doors are locked;
3. The battery level is at least ~~50% (20% for hybrids)~~ 20% or in charging ([#226](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles/issues/226));

## Battery capacity / residual sensors
Thanks to the community ([#272](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles/issues/272)), it seems that for some vehicles **Stellantis provides incorrect values**. The **switch.battery_values_correction** entity (in your language) applies a correction if active.

\*currently only to the battery_residual sensor

## Errors
<ins>Before any issue request, please check the integration log and look for solution below</ins>.

### OTP error - NOK:MAXNBTOOLS
It seems that this error is due to reaching the limit of associated devices / SMS received. Restore your Stellantis account and try again:
[Follow this procedure from Peugeot community](https://peugeot.my-customerportal.com/peugeot/s/article/AP-I-have-problems-with-the-pin-safety-code-or-I-want-to-change-it-What-can-I-do?language=en_GB).

<ins>**This operation removes the devices connected to your vehicle, no vehicle data will be lost**</ins>.

### OTP error - NOK:NOK_BLOCKED
It seems that this error is due to reaching the limit of wrong PIN used. Re-authenticate the integration.

## ABRP - A Better Routeplanner
Get a token from [ABRP](https://abetterrouteplanner.com/):
1. Login to your account;
2. Navigate to vehicle settings;
3. Navigate to real time data;
4. Navigate to edit connections;
5. Generate a token using "Generic" method;

Use the generated token in **abrp_token sensor** and enable **abrp_sync switch** to send updates.

## Contributors & Translations
Start from the "**develop**" branch and submit PRs in that branch.

Commit messages are included as release notes, please keep them short and understandable.

Before each PR please test:
- New installation;
- Reconfiguration;
- Commands;
- Sensors;
- 1 week without errors in logs;

If the checklist is complete, the PR will be merged and will be released a BETA version, if no issues are reported the changes will included on next stable release.

Thanks to all users who contribute to this integration by updating translations and reporting issues.

### Special thanks:
- [@MoellerDi](https://github.com/MoellerDi) for the great work and big support;
- [@benbox69](https://github.com/benbox69) for the python oauth2 helper tool;
- [@khenderick](https://github.com/khenderick) for the great work and big support;

Thanks to everyone for the issues, especially to:
- [@chmtc94](https://github.com/chmtc94);
- [@FrankTub](https://github.com/FrankTub);
- [@Jordan87](https://github.com/Jordan87);

## Support the project
**The latest heroes who believe in this project** 👇

**🏆 5 beers**  
Andy  
Kenneth Henderick  
Someone  
<sub>*and other heroes*</sub>

**🥈 3 beers**  
Sven  
Martijn  
John Woertman  
<sub>*and other heroes*</sub>

**🥉 2 beers**  
Grosi001  
ryhaberecht  
Tizian  

**⭐ 1 beers**  
Thomas  
@hengelha  
speedmops  
<sub>*and other heroes*</sub>

### Want to join the Club?
[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/andreatito)  
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/W7W11C9QJ7)
