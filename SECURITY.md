# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Spindrel, please report it responsibly.

**Do not open a public issue.** Instead, email **mike@tothdev.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

You should receive a response within 48 hours. We'll work with you to understand the issue and coordinate a fix before any public disclosure.

## Scope

Spindrel is self-hosted operator software. The expected deployment today is a trusted user or small trusted group on localhost, LAN, VPN, or behind a private reverse proxy. It is not currently positioned as a hardened public multi-tenant SaaS platform.

Security concerns include but are not limited to:

- Authentication bypass for web sessions, scoped API keys, or admin routes
- Unauthorized access to bot data, channels, or workspaces
- Tool execution vulnerabilities (command injection, path traversal)
- MCP proxy security (credential leakage, SSRF)
- Docker sandbox escapes
- External harness misuse or credential exposure
- Local machine-control lease bypass or provider transport abuse
- Secret/credential exposure in logs or API responses

## Security Practices

- Local web accounts and scoped API keys protect authenticated surfaces; health checks, auth/setup routes, and some integration callback/pairing routes are intentionally public or token-protected outside the API-key path
- Provider API keys and integration secrets are encrypted at rest when `ENCRYPTION_KEY` is configured
- Use a persistent `JWT_SECRET` for real deployments; if unset, browser sessions are signed with an ephemeral secret and invalidate on restart
- Docker sandboxes can provide container isolation for selected command paths, but normal command execution and harness runtimes are remote code execution by design
- Automatic redaction protects known secrets in tool results, LLM output, and stored tool-call records
- No telemetry or external data collection

## High-Risk Operator Surfaces

- **External agent harnesses** run Claude Code today, with Codex planned. Spindrel supplies the browser UI, channel/session persistence, terminal drawer, workspace path, and auth-status surface; the external CLI/SDK owns tools, bash, file edits, permissions, and its own OAuth identity. Treat harness access as admin-level remote code execution.
- **Admin Terminal** opens a PTY inside the Spindrel runtime for admin setup tasks such as `claude login`, workspace seeding, and diagnostics.
- **Local Machine Control** grants a chat session a lease to a paired machine. Only grant leases to sessions and users you trust with that target.
- **Browser Live** controls a real logged-in browser profile after pairing. Pairing tokens and browser sessions should be treated as sensitive.

## Deployment Guidance

- Keep public releases behind localhost, LAN, VPN, or a private authenticated proxy unless you have reviewed and accepted the risk.
- Back up `.env`, `ENCRYPTION_KEY`, `JWT_SECRET`, provider credentials, and mounted workspaces.
- Do not bind-mount host credentials or broad host paths into the Spindrel container unless the operators using harnesses and tools should be able to use them.
- Prefer Docker sandboxes or local machine-control leases when a command should not run in the main server runtime.
- Review tool policies before exposing powerful tools to less-trusted bots or users.

## Supported Versions

As an early-access project, only the latest release receives security updates. We recommend always running the latest version.
