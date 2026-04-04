"""BlueBubbles integration background process declaration.

The Socket.IO client (bb_client.py) is DISABLED. Message intake is handled
entirely by the webhook endpoint in router.py, which has proper echo
tracking, GUID dedup, circuit breakers, and staleness checks.

Running both Socket.IO and webhook simultaneously causes an infinite
echo loop: both paths process the same incoming message, each sends a
reply, and the two independent EchoTracker instances can't see each
other's sent messages — so echoes slip through and trigger more replies.
"""

# No CMD = no background process launched.
# All message intake goes through the /webhook endpoint.
DESCRIPTION = "BlueBubbles iMessage bridge (webhook-only — Socket.IO disabled)"
CMD = None
WATCH_PATHS = ["integrations/bluebubbles/"]
REQUIRED_ENV = ["BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"]
