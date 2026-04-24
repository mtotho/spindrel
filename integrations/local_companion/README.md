# local_companion

`local_companion` is the paired-machine machine-control provider for Spindrel.

It does not own the machine-control feature. Core owns the machine tools, leases, admin machine center, and transcript UX. This integration supplies one provider implementation: a paired companion process that runs on the target machine, opens an outbound WebSocket to the server, and executes bounded shell requests for the leased target. `ssh` is the sibling headless-machine provider on the same core contract.

## Architecture

```text
chat / plan session
    -> core machine_* tool
    -> execution-policy check
    -> core machine-control service
    -> local_companion provider
    -> websocket bridge
    -> paired companion client
    -> local shell on the enrolled target
```

- `machine_control.py` implements the provider contract.
- `router.py` exposes the companion WebSocket endpoint.
- `bridge.py` keeps the live target connection registry in memory.
- `client.py` is the companion process you run on the target machine.
- Core tools live in `app/tools/local/machine_control.py` as `machine_status`, `machine_inspect_command`, and `machine_exec_command`.
- Core treats this provider as ready when the live companion connection is present and fresh.

## Operator flow

1. Enroll a target from `Admin > Machines`:

   ```bash
   curl -X POST \
     -H "Authorization: Bearer $ADMIN_KEY" \
     -H "Content-Type: application/json" \
     http://localhost:8000/api/v1/admin/machines/providers/local_companion/enroll
   ```

2. Copy the returned launch command and run it on the target machine.
3. Verify the target appears in the machine center:

   ```bash
   curl -H "Authorization: Bearer $ADMIN_KEY" \
     http://localhost:8000/api/v1/admin/machines
   ```

4. In the web UI, grant that target to the session you want to use.
5. Use `machine_status`, `machine_inspect_command`, or `machine_exec_command` from that session.

The canonical architecture and end-user flow live in [docs/guides/local-machine-control.md](../../docs/guides/local-machine-control.md).

## Client launch

The enrollment response includes `target_id`, `token`, and an example command. The current bootstrap path downloads the companion script directly from the server, then runs it locally with Python.

```bash
curl -fsSL http://localhost:8000/integrations/local_companion/client.py \
  -o /tmp/spindrel-local-companion.py && \
python /tmp/spindrel-local-companion.py \
  --server-url http://localhost:8000 \
  --target-id <target_id> \
  --token <token>
```

Run it in the foreground first so you can verify pairing, then wrap it in your own user service if you want reconnect behavior.

## Tool UX

- `machine_status` renders a native machine-status card and can refresh while pinned.
- `machine_inspect_command` and `machine_exec_command` render terminal-style command result cards.
- Lease denials in chat return a `core.machine_access_required` rich result so the transcript can offer inline grant/revoke actions.

## Safety

- Companion access is session-scoped through machine-target leases.
- The runtime requires a live signed-in admin user with active presence.
- Autonomous origins such as tasks, heartbeats, subagents, and hygiene runs are denied by default.
- The companion still enforces local guardrails such as allowed roots, inspect prefixes, blocked patterns, timeouts, and output caps.

## Limits

- Bridge state is in-memory in this build; multi-worker deployments need an external broker before this becomes horizontally safe.
- `driver="companion"` is one shipped machine-target driver. `ssh` is the sibling headless-machine driver, not part of this integration.
- This integration is shell-first. File and desktop capabilities should reuse the same target + lease model rather than bypassing it.
- Machine enrollment/removal still live under `Admin > Machines`; the integration detail page now offers a provider-specific helper that calls the same core enroll flow and can generate a ready launch command or remote-enroll curl.
