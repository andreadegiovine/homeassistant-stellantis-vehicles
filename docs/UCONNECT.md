# Uconnect vehicles (beta)
[← Back to README](../README.md)

- [Requirements](#requirements)
- [Features](#features)
- [Configuration](#configuration)
  - [Brand and region](#brand-and-region)
  - [Vehicle PIN](#vehicle-pin)
- [Commands](#commands)
  - [WakeUp (deep refresh)](#wakeup-deep-refresh)
  - [Air conditioning Start/Stop](#air-conditioning-startstop)
  - [Charging start](#charging-start)
- [Last trip / last charge](#last-trip--last-charge)
- [Limits](#limits)
- [Errors](#errors)
  - [Uconnect refused the email or password](#uconnect-refused-the-email-or-password)
  - [Could not reach the Uconnect cloud](#could-not-reach-the-uconnect-cloud)
  - [The vehicle did not accept the command](#the-vehicle-did-not-accept-the-command)
  - [Command status 300 - Timeout](#command-status-300---timeout)
  - [Some entities are missing](#some-entities-are-missing)

| Fiat                            | Jeep                            | Alfa Romeo                                 | Maserati                                | Chrysler                                | Dodge                             | Ram                           |
|---------------------------------|---------------------------------|--------------------------------------------|-----------------------------------------|-----------------------------------------|-----------------------------------|-------------------------------|
| ![Fiat](../images/Fiat.png)     | ![Jeep](../images/Jeep.png)     | ![Alfa Romeo](../images/AlfaRomeo.png)     | ![Maserati](../images/Maserati.png)     | ![Chrysler](../images/Chrysler.png)     | ![Dodge](../images/Dodge.png)     | ![Ram](../images/Ram.png)     |

**The Uconnect cloud is served by the [py-uconnect](https://github.com/hass-uconnect/py-uconnect) library (Apache-2.0), the same of the [hass-uconnect](https://github.com/hass-uconnect/hass-uconnect) integration. Thanks to [@blind-oracle](https://github.com/blind-oracle) and the hass-uconnect contributors for their great work**

## Requirements
Get status:
- **Account of the official app** of the brand (Fiat, Jeep, Alfa Romeo, Maserati, Chrysler, Dodge, Ram), with the vehicle registered and connected services active;

Send remote commands:
- Get status requirements;
- **Vehicle PIN** (the one the official app asks for remote commands);
- The remote service of the command active for the vehicle (it depends on model, market and subscription).

> Stellantis does not provide public api credentials, this integration uses the mobile apps api and login flow.

## Features
|                                | Electric | Plug-in hybrid | Thermic | Vehicle PIN |
|--------------------------------|:--------:|:--------------:|:-------:|:-----------:|
| Get status                     |    ✔️    |       ✔️       |   ✔️    |             |
| Vehicle picture                |    ✔️    |       ✔️       |   ✔️    |             |
| Last trip / last charge \*     |    ✔️    |       ✔️       |   ✔️    |             |
| ABRP sync                      |    ✔️    |       ✔️       |         |             |
| Doors lock/unlock              |    ✔️    |       ✔️       |   ✔️    |     ✔️      |
| Horn and lights / Lights       |    ✔️    |       ✔️       |   ✔️    |     ✔️      |
| Air conditioning start/stop    |    ✔️    |       ✔️       |   ✔️    |     ✔️      |
| WakeUp (deep refresh)          |    ✔️    |       ✔️       |         |     ✔️      |
| Charging start                 |    ✔️    |       ✔️       |         |     ✔️      |

Command entities are created only for the commands the vehicle supports (its active remote services).

\* last charge for electric and plug-in hybrid vehicles only.

Sensors: battery, range, fuel level and range, mileage, days and distance to the next service, charging state, charging type, charging end, doors lock state, engine, air conditioning, privacy mode, position. Distances reported in miles are converted to km.

## Configuration
Choose **Uconnect** as vehicle mobile app, then brand and region, email, password and (optional) vehicle PIN. Reauthentication and **Reconfigure** use the same form.

### Brand and region
Each brand and region has its own app and login: choose the one of the official app you use.

| Brand      | Regions                                               |
|------------|-------------------------------------------------------|
| Fiat       | Europe, United States, Canada, Asia, Latin America    |
| Jeep       | Europe, United States, Asia, Latin America            |
| Alfa Romeo | Europe, United States and Canada, Asia                |
| Maserati   | Europe, United States and Canada, Asia                |
| Chrysler   | United States, Canada                                 |
| Dodge      | United States                                         |
| Ram        | United States, Latin America                          |

**Abarth** and **Lancia** vehicles use the Fiat app: choose Fiat. If the login is refused, try another region of the same brand.

Recent models built on the platforms of the other Stellantis brands may use a different cloud: if the vehicle is not found, check the app it uses (e.g. a PSA one).

### Vehicle PIN
Only needed for remote commands. Without it the vehicles are read-only and no command entity is created. To add it later use **Reconfigure**. A wrong PIN only refuses the commands, the vehicle status keeps updating.

## Commands
Every command is confirmed by the vehicle: the **command status** sensor shows `Complete` once the vehicle has carried it out, or `Timeout` if it did not answer in time (see [Command status 300](#command-status-300---timeout)).

| Command                     | Entity                                |
|-----------------------------|---------------------------------------|
| Doors lock / unlock         | Doors lock / Doors unlock buttons     |
| Horn and lights             | Horn button                           |
| Lights                      | Lights button                         |
| Air conditioning start/stop | Preconditioning start / stop buttons  |
| WakeUp (deep refresh)       | WakeUp button                         |
| Charging start              | Charge start button                   |

### WakeUp (deep refresh)
Asks the vehicle to send a fresh status to the cloud (electric and plug-in hybrid vehicles). As for the other brands it is limited to 6 per 20 minutes: a vehicle that does not answer keeps the request open for a while, and too many wakeups drain the 12V battery.

### Air conditioning Start/Stop
Uses the preconditioning of the vehicle, or its climate control when it has no preconditioning, with the default settings of the official app.

### Charging start
Starts charging now. Available when the vehicle is plugged in and not charging. Charge limit and charging schedules are not supported yet.

## Last trip / last charge
The **last trip** is built by the integration from the vehicle status, from the moment the engine is on to the moment it is off. It reports distance, duration and average speed.

- It is as precise as the refresh interval (5 minutes by default);
- It only covers trips made while Home Assistant is running: a trip in progress is lost if Home Assistant restarts.

The **last charge** works as for the other brands: it is built when the integration sees a charge start and end.

## Limits
- **No live updates**: the Uconnect cloud is polled every 5 minutes by default (configurable with the refresh interval entity) and only holds the last status the vehicle sent;
- **No real time tracking**: the position is the last one the vehicle reported;
- **Vehicle dependent data**: some vehicles do not report doors, windows or engine state;
- **Not tested on real vehicles yet**: please report what works and what does not on your vehicle;
- **Unofficial api**: Stellantis can change it at any time.

## Errors
<ins>Before any issue request, please check the integration log and the [diagnostics](https://www.home-assistant.io/integrations/diagnostics/), and look for solution below</ins>.

### Uconnect refused the email or password
The credentials are wrong, or they belong to another brand or region. Check them by signing in the official app, then check the brand and region chosen. Accounts created on the old Mopar portal may need to be migrated from the official app first.

### Could not reach the Uconnect cloud
The Uconnect cloud did not answer. Check the network of Home Assistant and try again later.

### The vehicle did not accept the command
The command was refused before reaching the vehicle; the reason is shown after the message:
- **PIN rejected**: the vehicle PIN is wrong, change it with **Reconfigure**;
- **Other reasons**: the remote service of the command is not active for the vehicle, or the cloud refused it (see the log for its answer).

### Command status 300 - Timeout
The cloud accepted the command but the vehicle did not confirm it in time, usually because it is offline (no coverage, deep sleep). The vehicle may still carry it out later: check its state at the next refresh.

### Some entities are missing
Command entities exist only for the remote services the vehicle has: check them in the diagnostics (`commands`, `services`). Sensors without a value from the vehicle stay unknown.
