# UniFi Network Integration

Read-only UniFi Network tools, widgets, and a troubleshooting skill for homelab network issues.

This integration targets the official local UniFi Network Integration API. Generate an API key in UniFi Network under **Settings > Control Plane > Integrations** when available on your Network version.

## Settings

| Setting | Required | Notes |
|---|---:|---|
| `UNIFI_URL` | Yes | Local console/controller URL, for example `https://192.168.1.1`. |
| `UNIFI_API_KEY` | Yes | Stored as a secret; sent as `X-API-KEY`. |
| `UNIFI_SITE_ID` | No | Leave blank to use the first site returned by `/sites`. |
| `UNIFI_VERIFY_SSL` | No | Default `true`; set `false` only for self-signed local certificates. |
| `UNIFI_API_BASE_PATH` | No | Default `/proxy/network/integration/v1`; fallback paths are tried automatically. |

## Tools

- `unifi_test_connection`
- `unifi_sites`
- `unifi_network_snapshot`
- `unifi_devices`
- `unifi_clients`
- `unifi_networks`
- `unifi_wifi`
- `unifi_firewall_zones`
- `unifi_vlan_advisor`
- `unifi_site_options`

All v1 tools are read-only. They do not restart devices, edit VLANs, change WiFi, block clients, or mutate firewall policy.

## Widgets

Presets include connection diagnostics, network health overview, VLAN/SSID map, device inventory, and client inventory.

## Security Notes

- Use a dedicated UniFi API key with the minimum permissions needed for read-only Network data.
- Do not expose the local UniFi console to the public internet for this integration.
- Payloads are recursively redacted for common secret fields before returning through tools.

