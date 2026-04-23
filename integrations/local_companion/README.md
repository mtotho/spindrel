# local_companion

Paired local-machine control for Spindrel. The server does not SSH into your workstation; a small companion process runs on the target machine, opens an outbound WebSocket to the server, and executes bounded shell requests only when a live admin user has granted that session a lease.

## Architecture

```text
chat / plan session
    -> lease-gated local tool
    -> execution-policy check
    -> local_companion bridge
    -> paired companion client
    -> local shell on the enrolled target
```

- `router.py` exposes enrollment, status, revoke, and the WebSocket endpoint.
- `bridge.py` keeps the live target connection registry in memory.
- `client.py` is the companion process you run on the target machine.
- `tools/local_companion.py` exposes `local_status`, `local_inspect_command`, and `local_exec_command`.

## Operator flow

1. Enroll a target:

   ```bash
   curl -X POST \
     -H "Authorization: Bearer $ADMIN_KEY" \
     -H "Content-Type: application/json" \
     http://localhost:8000/integrations/local_companion/admin/enroll
   ```

2. Copy the returned launch command and run it on the target machine.
3. Verify the target appears in:

   ```bash
   curl -H "Authorization: Bearer $ADMIN_KEY" \
     http://localhost:8000/integrations/local_companion/admin/status
   ```

4. In the web UI, grant that target to the session you want to use.
5. Use `local_status`, `local_inspect_command`, or `local_exec_command` from that session.

The canonical architecture and end-user flow live in [docs/guides/local-machine-control.md](../../docs/guides/local-machine-control.md).

## Client launch

The enrollment response includes `target_id`, `token`, and an example command. The companion is a Python entrypoint:

```bash
python -m integrations.local_companion.client \
  --server http://localhost:8000 \
  --target-id <target_id> \
  --token <token>
```

Run it in the foreground first so you can verify pairing, then wrap it in your own user service if you want reconnect behavior.

## Tool UX

- `local_status` renders a native machine-status card and can refresh while pinned.
- `local_inspect_command` and `local_exec_command` render terminal-style command result cards.
- Lease denials in chat return a `core.machine_access_required` rich result so the transcript can offer inline grant/revoke actions.

## Safety

- Companion access is session-scoped through machine-target leases.
- The runtime requires a live signed-in admin user with active presence.
- Autonomous origins such as tasks, heartbeats, subagents, and hygiene runs are denied by default.
- The companion still enforces local guardrails such as allowed roots, inspect prefixes, blocked patterns, timeouts, and output caps.

## Limits

- Bridge state is in-memory in this build; multi-worker deployments need an external broker before this becomes horizontally safe.
- `driver="companion"` is the only shipped machine-target driver right now. SSH is a future sibling driver, not part of this integration.
- This integration is shell-first. File and desktop capabilities should reuse the same target + lease model rather than bypassing it.
