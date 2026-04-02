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

Spindrel is designed to be self-hosted. Security concerns include but are not limited to:

- Authentication bypass (API key validation)
- Unauthorized access to bot data, channels, or workspaces
- Tool execution vulnerabilities (command injection, path traversal)
- MCP proxy security (credential leakage, SSRF)
- Docker sandbox escapes
- Secret/credential exposure in logs or API responses

## Security Practices

- API keys are required for all endpoints
- Provider API keys and integration secrets are encrypted at rest (when `ENCRYPTION_KEY` is configured)
- Docker sandboxes run with restricted capabilities
- Automatic redaction of secrets in LLM responses
- No telemetry or external data collection

## Supported Versions

As an early-access project, only the latest release receives security updates. We recommend always running the latest version.
