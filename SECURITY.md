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

## Threat Model by Deployment Tier

| Tier | Expected posture | Minimum hardening |
|---|---|---|
| Localhost | Trusted operator on one machine | Persistent `JWT_SECRET`, `ENCRYPTION_KEY`, scoped bot keys, tool policy enabled |
| LAN | Trusted household/lab network | Localhost controls plus separate `ADMIN_API_KEY`, review bot API scopes, review host exec/harness/local-machine access |
| VPN/private proxy | Trusted remote operators | LAN controls plus TLS/proxy auth, rate limiting, backup of secrets, audit high-risk bots before granting access |
| Internet-exposed | Not recommended today | Requires a dedicated review of auth, callback routes, widget/harness/local-machine surfaces, rate limits, and deployment-specific logging before use |
| Multi-user/public | Out of scope today | Requires tenant isolation, row-level ownership review, public registration policy, stronger workflow around third-party skills/widgets/plugins |

## Agentic-AI Risk Classes

The current hardening model tracks traditional web/API risks and agentic risks. In practice, the highest-risk failures are not bad text outputs; they are unauthorized or excessive actions through delegated identity, tools, persistent memory, widgets, integrations, harnesses, and local-machine/browser control.

When reviewing new features, check at least these classes:

- Goal or instruction hijack through untrusted content, tool output, documents, web pages, or integration messages
- Tool misuse, unsafe tool chaining, or policy bypass
- Identity and privilege abuse through inherited API scopes, widget JWTs, harness OAuth, local-machine leases, or integration credentials
- Skill/plugin/widget supply-chain exposure from user-authored or third-party bundles
- Unexpected code execution through harnesses, terminal/admin operations, bot-authored handlers, widget Python/SQLite paths, or command tools
- Memory, RAG, and context poisoning across sessions, channels, Projects, bot knowledge bases, or skill bodies
- Inter-agent spoofing or unsafe cross-bot/channel behavior
- Cascading failures from heartbeats, scheduled tasks, widget crons/events, standing orders, or repeated bot pings
- Human-trust exploitation through approval prompts, repair actions, or bot-generated admin guidance
- Rogue or compromised agents expanding their own effective power

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

## Security Audit Surface

The admin security audit is read-only and currently checks baseline config/tool-policy state plus agentic boundary signals:

- Encryption/admin key separation/tool policy/rate-limit/redaction settings
- Dangerous tool tiers, exec/control-plane tool exposure, stale approvals, and MCP server count
- Bots with `cross_workspace_access`
- Bots with high-risk API scopes such as `admin`, wildcard, `tools:execute`, secret/provider/settings/API-key writes, and broad file writes
- Widget action API dispatch allowlist breadth
- WorkSurface isolation static findings and inbound integration callback auth/replay contracts
- Local machine-control tool gate contracts, lease state, and browser-live pairing exposure

## Deployment Guidance

- Keep public releases behind localhost, LAN, VPN, or a private authenticated proxy unless you have reviewed and accepted the risk.
- Back up `.env`, `ENCRYPTION_KEY`, `JWT_SECRET`, provider credentials, and mounted workspaces.
- Do not bind-mount host credentials or broad host paths into the Spindrel container unless the operators using harnesses and tools should be able to use them.
- Prefer Docker sandboxes or local machine-control leases when a command should not run in the main server runtime.
- Review tool policies before exposing powerful tools to less-trusted bots or users.

## Supported Versions

As an early-access project, only the latest release receives security updates. We recommend always running the latest version.
