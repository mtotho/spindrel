# UniFi Network Troubleshooting

Use this skill when helping with UniFi Network health, VLANs, WiFi, client connectivity, AP/switch/gateway status, firewall zones, or homelab network design questions.

## Operating Rules

- Start with tools before advice. Use `unifi_network_snapshot` for broad context unless the user only asks to test the connection.
- Keep v1 read-only. Do not claim you can change UniFi config, restart devices, block clients, power-cycle PoE, create VLANs, edit firewall rules, or change WiFi settings.
- Do not ask the user to make broad risky changes such as disabling firewall rules globally, flattening VLANs, or moving all ports to one network.
- When the API lacks a field needed to prove a diagnosis, say which UniFi UI page to inspect instead of guessing.
- Treat UniFi terms carefully:
  - A Network usually represents an IP subnet and may have a VLAN ID.
  - A WiFi/SSID can map clients into a Network/VLAN.
  - Switch/AP uplink ports must carry the VLAN if an SSID or downstream port uses it.
  - Primary/Native Network is untagged traffic on a port. Tagged VLANs are separate.
  - VLAN 1/default/untagged behavior is special and should not be treated as an ordinary tagged VLAN.
  - Firewall/Zones can block inter-network traffic even when DHCP and VLAN tagging are correct.

## Tool Order

1. `unifi_test_connection`
   - Use if setup may be wrong, widgets show unavailable, or the user asks if UniFi is connected.
   - Read diagnostics: base URL, API base path, site ID, and attempted endpoints.

2. `unifi_network_snapshot`
   - Default first tool for troubleshooting.
   - Use the returned `errors` to identify missing API sections. Partial data is still useful.
   - Review `devices`, `clients`, `networks`, `wifi`, `firewall_zones`, and the generated tiles.

3. `unifi_clients`
   - Use when the user names a device, MAC, IP, hostname, or affected network.
   - Search with `query` when possible.
   - Interpret:
     - no client found: client may be offline, wrong name/MAC, or never connected.
     - `169.254.x.x`: likely DHCP failure.
     - wrong subnet/network: likely SSID/network mapping or VLAN tagging.
     - unauthorized: captive portal/hotspot/access-policy issue.

4. `unifi_devices`
   - Use for AP/switch/gateway offline, adopting, isolated, update, uplink, or topology issues.
   - Offline or isolated APs/switches can make VLAN symptoms misleading.

5. `unifi_networks` and `unifi_wifi`
   - Use together for VLAN/SSID mapping.
   - Confirm intended SSID -> network/VLAN relationship.

6. `unifi_firewall_zones`
   - Use when the client has the right IP/subnet but cannot reach another VLAN, LAN resource, or the internet.
   - Zone data may be unavailable from some API versions. If so, ask for a manual check in UniFi Firewall/Zones.

7. `unifi_vlan_advisor`
   - Use when the user gives a symptom, especially "wrong VLAN", "no IP", "can't reach X", "IoT VLAN", "guest network", or "inter-VLAN".
   - Pass `symptom` and `target_client` if available.
   - Present the advisor output under:
     - likely causes
     - evidence from tools
     - missing manual checks
     - safe next steps
     - do not change yet

## Diagnostic Flow

### Client Cannot Join WiFi

Use `unifi_network_snapshot`, then `unifi_clients` if the client appears.

Check:
- Is the SSID enabled and mapped to the expected network/VLAN?
- Is the client unauthorized rather than disconnected?
- Is the client IoT/legacy and possibly incompatible with WPA mode, band steering, minimum RSSI, or PMF settings?
- Does the AP serving the SSID appear online?

Safe next checks:
- UniFi UI: Settings > WiFi for SSID security and network mapping.
- UniFi UI: Client page for association/auth failures.
- UniFi UI: AP page for radios, channels, and SSID broadcast scope.

### Client Joins But Has No IP

Use `unifi_clients` for the client and `unifi_vlan_advisor`.

Interpret:
- APIPA `169.254.x.x` means DHCP did not complete.
- Correct SSID but no IP often means the VLAN is not carried from AP to gateway/DHCP.
- If only one wired port fails, suspect access-port/native-network config.
- If all clients on a VLAN fail, suspect DHCP server, gateway interface, or trunk/uplink VLAN allow list.

Safe next checks:
- UniFi VLAN Viewer: verify the VLAN exists along every uplink from client/AP/switch to gateway.
- Ports tab: verify the AP uplink port does not use the SSID VLAN as its Primary/Native Network.
- Settings > Networks: verify DHCP is enabled where expected.

### Client Gets Wrong Subnet Or Wrong VLAN

Use `unifi_clients`, `unifi_networks`, and `unifi_wifi`.

Likely causes:
- SSID mapped to the wrong Network.
- Wired port Primary/Native Network is wrong.
- Device Network Override conflicts with the expected native network.
- VLAN 1/default behavior is being confused with a tagged VLAN.

Safe next checks:
- Settings > WiFi: SSID network mapping.
- Ports tab: port profile/native network for the client or AP uplink.
- VLAN Viewer: where the VLAN is allowed/tagged.

### Client Has IP But Cannot Reach Internet

Use `unifi_network_snapshot`, then check gateway/device status and firewall zones.

Separate:
- WAN/gateway issue: many networks affected.
- VLAN-specific issue: one network affected.
- DNS issue: IP pings work but names fail.
- Firewall/zone issue: client has correct IP but outbound policy blocks traffic.

Safe next checks:
- Gateway/WAN health.
- Settings > Networks for DNS and gateway.
- Firewall/Zones from client network to Internet/WAN.

### Client Has IP But Cannot Reach Another VLAN

Use `unifi_firewall_zones` if available and `unifi_vlan_advisor`.

Interpret:
- Correct IP/subnet means DHCP and VLAN tagging likely work.
- Inter-VLAN failures usually involve zone/firewall policy, network isolation, client isolation, or ACLs.
- Check both directions. A return path or destination-to-source deny can still break the flow.

Safe next checks:
- Firewall/Zones: source zone/network to destination zone/network.
- Network Isolation and client isolation settings.
- Destination host firewall, especially for Windows/macOS/Linux local firewalls.

### UniFi Device Offline, Isolated, Or Adoption Problem

Use `unifi_devices`.

Check:
- Gateway/switch/AP state.
- Whether an AP or switch is isolated from the controller.
- Whether a device's management network/native VLAN is reachable from the console.
- Whether a device Network Override put management on a VLAN not carried upstream.

Safe next checks:
- Device page in UniFi UI for adoption/isolation detail.
- Ports tab for management/native network and allowed VLANs.
- Physical uplink/cabling/PoE before assuming VLAN config.

## Response Shape

For troubleshooting answers, use this structure:

1. `What I checked`
   - Name the tools and the exact client/site/network if applicable.

2. `Most likely causes`
   - Rank causes by evidence. Do not list every generic possibility.

3. `Evidence`
   - Cite tool data: client status, IP/subnet, SSID/network, offline devices, API partial errors.

4. `Manual checks needed`
   - Only include UI checks the tools cannot prove.
   - Prefer specific places: VLAN Viewer, Ports tab, Settings > Networks, Settings > WiFi, Firewall/Zones, client details, device details.

5. `Safe next steps`
   - Give small reversible checks first.
   - Avoid config changes unless the evidence clearly points there.

6. `Do not change yet`
   - Warn against broad changes that would hide the root cause.

## Common Pitfalls

- Do not assume "connected to WiFi" means DHCP worked.
- Do not assume "right VLAN exists" means it is carried on the AP/switch uplink.
- Do not assume firewall is the issue when the client has no IP.
- Do not assume VLAN tagging is the issue when the client has the correct IP but only one destination fails.
- Do not use private UniFi endpoints or browser-session APIs unless the user explicitly asks for a future design discussion; v1 tools are official-API only.

