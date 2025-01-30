---
name: Feedback
about: Bug report and feature request
title: ''
labels: ''
assignees: ''

---

Include on the request:
- Vehicle mark
- Vehicle model
- Vehicle year
- Log

Enable the debug log of this integration by your configuration.yaml:
```
logger:
    default: error
    logs:
        custom_components.stellantis_vehicles: debug
```
dont forget to hide any personal data (access_token, refresh_token, customer_id, vehicle_id, vin, coordinates, etc...)
