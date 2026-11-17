# Leapmotor vehicles (beta)
[← Back to README](../README.md)

- [Requirements](#requirements)
- [Features](#features)
- [Configuration](#configuration)
  - [Second account](#second-account)
  - [Vehicle PIN](#vehicle-pin)
  - [App certificate](#app-certificate)
- [Commands](#commands)
  - [Charge limit](#charge-limit)
  - [Scheduled charging](#scheduled-charging)
  - [Air conditioning Start/Stop](#air-conditioning-startstop)
  - [Battery preheating](#battery-preheating)
- [Last trip / last charge](#last-trip--last-charge)
- [Limits](#limits)
- [Errors](#errors)
  - [Leapmotor refused the email or password](#leapmotor-refused-the-email-or-password)
  - [The Leapmotor app certificate could not be downloaded or is not valid](#the-leapmotor-app-certificate-could-not-be-downloaded-or-is-not-valid)
  - [Could not reach the Leapmotor cloud](#could-not-reach-the-leapmotor-cloud)
  - [The official app logs out](#the-official-app-logs-out)
  - [The vehicle did not accept the command](#the-vehicle-did-not-accept-the-command)
  - [Command status 300 - Timeout](#command-status-300---timeout)
  - [The vehicle did not report its whole charging plan](#the-vehicle-did-not-report-its-whole-charging-plan)

| Leapmotor                                |
|------------------------------------------|
| ![Leapmotor](../images/Leapmotor.png)    |

**The Leapmotor cloud protocol follows the work of [kerniger/leapmotor-ha](https://github.com/kerniger/leapmotor-ha) (MIT) and [markoceri/leapmotor-api](https://github.com/markoceri/leapmotor-api), the app certificate comes from [markoceri/leapmotor-certs](https://github.com/markoceri/leapmotor-certs). Thanks to [@kerniger](https://github.com/kerniger) and [@markoceri](https://github.com/markoceri) for their great work**

## Requirements
Get status:
- **Leapmotor account** of the international app (European and other non-Chinese markets);
- **A second Leapmotor account** with the vehicle shared to it (see [Second account](#second-account));

Send remote commands:
- Get status requirements;
- **Vehicle PIN** (the one the official app asks for remote commands);

> Leapmotor does not provide public api credentials, this integration uses the mobile app api and login flow. Chinese-market accounts are not supported.

## Features
|                              | Electric (BEV) | Range extender (REEV) | Vehicle PIN |
|------------------------------|:--------------:|:---------------------:|:-----------:|
| Get status                   |       ✔️       |          ✔️           |             |
| Vehicle picture              |       ✔️       |          ✔️           |             |
| Last trip / last charge      |       ✔️       |          ✔️           |             |
| ABRP sync                    |       ✔️       |          ✔️           |             |
| Doors lock/unlock            |       ✔️       |          ✔️           |     ✔️      |
| Find my car (horn + lights)  |       ✔️       |          ✔️           |     ✔️      |
| Air conditioning start/stop  |       ✔️       |          ✔️           |     ✔️      |
| Battery preheating           |       ✔️       |          ✔️           |     ✔️      |
| Charging limit \*            |       ✔️       |          ✔️           |     ✔️      |
| Scheduled charging \*        |       ✔️       |          ✔️           |     ✔️      |

\* not available on T03, see [Limits](#limits).

Sensors: battery, battery energy, range, fuel level and range (REEV), mileage, speed, outside temperature, charging state, charging type, charging end, doors, lock state, position.

## Configuration
Choose **Leapmotor** as vehicle mobile app, then enter email, password and (optional) vehicle PIN. Reauthentication and **Reconfigure** use the same form.

### Second account
Leapmotor allows one session per account: using here the account of the official app logs the app out, and the two keep taking the session from each other.

1. Create a second Leapmotor account;
2. From the official app, share the vehicle with the second account with **all permissions** and **no expiry** (a temporary share stops the integration when it expires);
3. Optionally sign in the official app with the second account once to check the vehicle is there, then sign out;
4. Use the second account in this integration.

### Vehicle PIN
Only needed for remote commands. Without it the vehicle is read-only and no command entity is created. To add it later use **Reconfigure**.

### App certificate
The Leapmotor login only answers clients presenting the TLS certificate of the official app. It is the same for every user and **is not shipped with this integration**: it is downloaded once, during the first Leapmotor setup, from [markoceri/leapmotor-certs](https://github.com/markoceri/leapmotor-certs) and stored in:

```
config/.storage/stellantis_vehicles/leapmotor/app_cert.pem
config/.storage/stellantis_vehicles/leapmotor/app_key.pem
```

Files already in that folder are used as they are, so they can also be provided by hand.

## Commands
Every command is confirmed by the vehicle: the **command status** sensor shows `Complete` once the vehicle has carried it out, or `Timeout` if it did not answer in time (see [Command status 300](#command-status-300---timeout)).

| Command                     | Entity                                    |
|-----------------------------|-------------------------------------------|
| Doors lock / unlock         | Doors lock / Doors unlock buttons         |
| Find my car                 | Horn button (horn and lights)             |
| Air conditioning start/stop | Preconditioning start / stop buttons      |
| Battery preheating          | Battery preheating switch                 |
| Charging limit              | Battery charging limit slider             |
| Scheduled charging          | Battery charging start time, Scheduled charging switch |

### Charge limit
The slider sets the limit **held by the vehicle** (from 15% to 100%), the same one of the official app. It is not the limit managed by the integration used for PSA vehicles: the vehicle stops the charge by itself.

The new value is shown at once and kept until the vehicle reports it; if the vehicle does not apply it, the slider goes back to the vehicle value.

### Scheduled charging
The vehicle charging plan has a start time and an on / off state:
- **Battery charging start**: sets the start time and turns the schedule on (a start time does nothing while the schedule is off);
- **Scheduled charging** switch: turns the schedule on / off, keeping its start time.

Charge limit, start time and schedule are written together as one charging plan: only the changed value is modified, the rest (end time, days) stays as set in the official app.

### Air conditioning Start/Stop
Starts the air conditioning with the default settings of the official app (24°C), or stops it.

### Battery preheating
Starts or stops the battery heating, useful before a fast charge in cold weather. The switch shows the heating state reported by the vehicle.

## Last trip / last charge
Leapmotor has no trips service: the **last trip** is built by the integration from the vehicle status, from the moment the vehicle is ready or moving to the moment it stops. It reports distance, duration, average and top speed and, when the vehicle reports its available energy, the consumption.

- It is as precise as the refresh interval (60 seconds by default);
- It only covers trips made while Home Assistant is running: a trip in progress is lost if Home Assistant restarts.

The **last charge** works as for the other brands: it is built when the integration sees a charge start and end.

## Limits
- **No live updates**: the Leapmotor cloud is polled, a change made in the official app or on the vehicle shows up at the next refresh;
- **T03**: charge limit and scheduled charging are not created, the vehicle does not apply them when written this way;
- **Commands**: confirmed on some models only; the vehicle can refuse a command it does not support or that the shared account is not allowed to send;
- **Doors lock/unlock**: reported not working on some vehicles, under investigation;
- **Shared account permissions**: the account sees and controls only what the owner granted when sharing the vehicle;
- **Unofficial api**: Leapmotor can change it at any time.

## Errors
<ins>Before any issue request, please check the integration log and the [diagnostics](https://www.home-assistant.io/integrations/diagnostics/), and look for solution below</ins>.

### Leapmotor refused the email or password
The credentials are wrong, or the account is locked after too many attempts. Check them by signing in the official app with the same account, reset the password there if needed, then sign out and try again.

### The Leapmotor app certificate could not be downloaded or is not valid
The certificate download failed (network, GitHub unreachable) or the files in `config/.storage/stellantis_vehicles/leapmotor/` are not a valid certificate and key. Delete the folder and try again, or put `app_cert.pem` and `app_key.pem` there by hand (see [App certificate](#app-certificate)).

### Could not reach the Leapmotor cloud
The Leapmotor cloud did not answer. Check the network of Home Assistant and try again later.

### The official app logs out
The integration and the official app are using the same account. Use a [second account](#second-account).

### The vehicle did not accept the command
The command was refused before reaching the vehicle; the reason is shown after the message:
- **PIN check failed**: the vehicle PIN is wrong, change it with **Reconfigure**;
- **Permission / not supported**: the shared account is not allowed to send this command, or the model does not support it. Share the vehicle again with all permissions.

### Command status 300 - Timeout
The cloud accepted the command but the vehicle did not confirm it in time, usually because it is offline (no coverage, deep sleep). The vehicle may still carry it out later: check its state at the next refresh.

### The vehicle did not report its whole charging plan
Charge limit and scheduled charging are written as a whole charging plan, and some vehicles do not report all of it. Set the charging schedule once from the official app, then try again.
