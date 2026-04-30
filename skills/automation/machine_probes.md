---
name: Machine Probes
description: Progressive discovery on a leased machine target using bounded read-only probes before raw shell commands
triggers: machine probe, progressive discovery, network debugging, docker debugging, port check, dns lookup, homelab troubleshooting, container can't connect, vlan troubleshooting
category: tool-use
---

# Machine Probes

Use this when the user gives a vague machine, network, Docker, or homelab
symptom and you need evidence before advice.

## Procedure

1. Call `machine_status()` if you do not know whether this session has a
   machine target lease.
2. Call `machine_probe_catalog()` to see available probe IDs and required
   arguments.
3. Run one cheap probe with `machine_run_probe()`. Start with:
   - `network_basics` for unknown network state.
   - `dns_lookup` when a name may be wrong.
   - `tcp_port` when reachability to a service matters.
   - `docker_summary` when containers, apps, or stacks are involved.
4. Report only what the probe proves. Separate:
   - evidence
   - likely cause
   - blocked or missing data
   - next probe
5. Follow `next_probe_ids` instead of jumping to a fixed runbook.

## Boundaries

- Do not use probes as proof of UniFi firewall, VLAN, or TrueNAS share
  configuration. Use the relevant integration tools when that state matters.
- Do not call `machine_exec_command()` just because a probe is available. Use
  probes first; use raw exec only when the user asks for a command outside the
  bounded probe set.
- Do not claim a service is down from one failed probe. Identify where the
  probe ran from and what path it tested.
- If a probe is blocked by missing machine lease, say that directly and stop
  that path.

## Response Shape

Use this concise structure:

1. `What I checked`
2. `What the evidence says`
3. `What is still unknown`
4. `Next probe`
