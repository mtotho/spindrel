# TrueNAS Operations

Use the TrueNAS tools for storage health checks, alerts, recent jobs, disk temperatures, services, shares, snapshots, and guarded basic operations.

Start with `truenas_health_snapshot` for broad status. It is read-only and returns partial section errors, so use it before deeper follow-up tools.

Use focused read tools when the user asks about a specific area:

- `truenas_pool_status` for pool state and scrub schedules.
- `truenas_alerts` for active alerts.
- `truenas_jobs` for running, failed, or recent jobs.
- `truenas_disk_temperatures` for drive temperature checks.
- `truenas_services` for service status.
- `truenas_shares` for SMB/NFS shares.
- `truenas_snapshots` for recent ZFS snapshots.

Treat TrueNAS operations as infrastructure work. Do not start a scrub or control a service unless the user clearly asks for it. The tools `truenas_start_scrub` and `truenas_control_service` require `confirmed: true`; explain the action first and only pass confirmation when the user's intent is explicit.

The canonical v1 path is the direct TrueNAS JSON-RPC API. The official TrueNAS MCP server is research-preview and currently better suited as a future optional advanced tool family than as the default integration backend.

