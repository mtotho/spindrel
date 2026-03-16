---
name: Home Assistant
description: Home Assistant automation, configuration, and integration management
---

# Home Assistant

## Configuration

Home Assistant configuration lives in `/config/configuration.yaml` (or split across multiple files with `!include`).

Key config patterns:
- Split config: `automation: !include automations.yaml`
- Packages: group related config in `packages/` directory
- Secrets: store sensitive values in `secrets.yaml`, reference with `!secret my_key`
- Validate config before restarting: Settings > System > check configuration

## Automations

Automations have three parts: trigger, condition, action.

Example automation structure:
```yaml
automation:
  - alias: "Turn on lights at sunset"
    trigger:
      - platform: sun
        event: sunset
        offset: "-00:30:00"
    condition:
      - condition: state
        entity_id: binary_sensor.someone_home
        state: "on"
    action:
      - service: light.turn_on
        target:
          area_id: living_room
        data:
          brightness_pct: 80
```

Common trigger platforms: `state`, `time`, `sun`, `mqtt`, `webhook`, `zone`, `device`.
Common action services: `light.turn_on`, `switch.toggle`, `notify.mobile_app`, `scene.turn_on`.

## Integrations

Integrations connect HA to devices and services. Most are configured through the UI (Settings > Devices & Services > Add Integration).

Popular integrations:
- **MQTT**: For Zigbee2MQTT, Tasmota, and custom devices
- **ESPHome**: For DIY ESP8266/ESP32 devices
- **Z-Wave JS**: For Z-Wave devices via Z-Wave JS UI
- **Google Home / Alexa**: Voice assistant bridges
- **HACS**: Community store for custom integrations and frontend cards

## REST API

HA exposes a REST API at `http://<host>:8123/api/`:
- `GET /api/states` — all entity states
- `GET /api/states/<entity_id>` — single entity state
- `POST /api/services/<domain>/<service>` — call a service
- Auth: `Authorization: Bearer <long_lived_access_token>`

## Troubleshooting

- Check logs: Settings > System > Logs (or `home-assistant.log`)
- Restart types: Quick reload (YAML only), Restart (full), Rebuild (containers)
- Entity unavailable: Check integration, device connectivity, and logs
- Automation not firing: Check trace (Settings > Automations > trace icon)
