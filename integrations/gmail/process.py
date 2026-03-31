"""Gmail integration background process declaration."""

DESCRIPTION = "Gmail IMAP poller (email content feed)"
CMD = ["python", "integrations/gmail/poller.py"]
WATCH_PATHS = ["integrations/gmail/"]
REQUIRED_ENV = ["GMAIL_EMAIL", "GMAIL_APP_PASSWORD"]
