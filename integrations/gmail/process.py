"""Gmail integration background process declaration.

Note: AGENT_API_KEY is NOT in REQUIRED_ENV because the process manager
auto-injects a scoped API key when the integration declares api_permissions
in setup.py. The key is provisioned automatically when settings are saved.
"""

DESCRIPTION = "Gmail IMAP poller (email content feed)"
CMD = ["python", "integrations/gmail/poller.py"]
WATCH_PATHS = ["integrations/gmail/"]
REQUIRED_ENV = ["GMAIL_EMAIL", "GMAIL_APP_PASSWORD"]
