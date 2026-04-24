# ssh

`ssh` is the headless-machine machine-control provider for Spindrel.

It does not own the machine-control feature. Core owns the machine tools, leases, admin machine center, and transcript UX. This integration supplies one provider implementation: a strict non-interactive OpenSSH transport for leased machine targets such as LAN boxes or other reachable hosts.

## Architecture

```text
chat / plan session
    -> core machine_* tool
    -> execution-policy check
    -> core machine-control service
    -> ssh provider
    -> fresh ssh probe or command subprocess
    -> remote shell on the enrolled target
```

- `machine_control.py` implements the provider contract.
- Core tools live in `app/tools/local/machine_control.py` as `machine_status`, `machine_inspect_command`, and `machine_exec_command`.
- Core treats this provider as ready only after a fresh probe succeeds.

## Operator flow

1. Configure any provider-wide timeout/output settings in `Admin > Integrations > SSH`.
2. Go to `Admin > Machines`.
3. Under the `SSH` provider, create at least one profile containing:
   - private key
   - `known_hosts`
4. Enroll a target from `Admin > Machines`.
5. Provide:
   - profile
   - `host`
   - `username`
   - optional `port`
   - optional default `working_dir`
6. Use `Probe` in `Admin > Machines` to verify the target is reachable.
7. Grant that target to the session you want to use.
8. Use `machine_status`, `machine_inspect_command`, or `machine_exec_command` from that session.

The provider stores SSH profiles and target references in app-managed provider settings, so container rebuilds do not wipe setup. The runtime only creates short-lived temp files for the actual `ssh` subprocess.

## Safety

- Access is session-scoped through machine-target leases.
- The runtime requires a live signed-in admin user with active presence.
- Lease grant and lease-gated execution require a fresh SSH probe.
- The provider uses key-only auth with strict host verification.
- No password prompts, TTY allocation, forwarding, or interactive auth paths are allowed.
- Command subprocesses are bounded by timeouts and output caps.

## Limits

- This provider is shell-first.
- It opens a fresh SSH subprocess per probe or command; there is no persistent SSH session manager in this build.
- Password auth, TOFU host acceptance, file transfer, and port forwarding are intentionally out of scope.

The canonical architecture and end-user flow live in [docs/guides/local-machine-control.md](../../docs/guides/local-machine-control.md).
