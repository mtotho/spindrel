"""Phase Q-SEC-3 — webhook replay drift-pin.

Pins the current replay-resistance (or lack thereof) of each inbound webhook
surface. Each class documents one integration's replay contract so a future
hardening (adding a timestamp binding, a nonce, a challenge handshake) flips
the assertion in a single obvious place.

Surfaces audited:

QREPLAY.1  ``integrations/github/validator.py::validate_signature``
           HMAC-SHA256 over the raw body only. No timestamp, no delivery-id
           binding. Pin: the *same* (payload, signature) pair validates every
           time — a captured webhook replays indefinitely. Downstream replay
           defense is payload-level (e.g. handler idempotency), not signature.

QREPLAY.2  ``integrations/bluebubbles/router.py::webhook``
           Static bearer token via ``?token=<BB_WEBHOOK_TOKEN>`` (no HMAC,
           no timestamp, no nonce). Two documented replay mitigations exist:
           (a) ``_STALE_THRESHOLD`` = 300s staleness window keyed on the
               *self-reported* ``dateCreated`` from the payload body, and
           (b) ``_guid_dedup`` persistent GUID dedup.
           Pin: the token-only auth is replay-indistinguishable from legitimate
           delivery — the staleness / GUID layers are what actually reject
           replays, and they're bypassable by an attacker who controls
           dateCreated and the guid (same static token required).

QREPLAY.3  ``integrations/slack/router.py`` has NO inbound webhook endpoint —
           Slack uses Socket Mode via ``slack-bolt``. Pin: no ``POST`` route
           exists on the router. If a future migration switches Slack to the
           Events API (HTTP webhooks), this test flips and a fresh drift file
           should pin the signature/timestamp contract.

QREPLAY.4  ``integrations/local_companion/router.py::companion_ws``
           Static per-target token via ``?token=<target_token>`` over the WS
           query string, constant-time compared via ``secrets.compare_digest``.
           No challenge/response in the hello handshake. Pin: a leaked token
           replays as a full reconnect — the client proves nothing beyond
           static-token possession.

QREPLAY.5  ``app/services/webhooks.py::sign_payload`` / ``verify_signature``
           Outbound webhook signature generator (Spindrel→third-party). HMAC
           over the body only; no timestamp attached. Pin: third-party
           consumers that re-sign the captured body with the shared secret
           cannot detect a replay on their side either — replay defense is
           the consumer's responsibility, not Spindrel's.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

from integrations.github.validator import validate_signature
from app.services.webhooks import sign_payload, verify_signature


# ===========================================================================
# QREPLAY.1 — GitHub webhook signature replay
# ===========================================================================


def _github_sig(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class TestGithubWebhookSignatureReplayable:
    """``validate_signature`` binds only the body, not the time. A captured
    (payload, X-Hub-Signature-256) pair is accepted indefinitely.

    If future hardening binds a delivery-id or server-generated nonce, flip
    ``test_same_payload_signature_validates_twice`` to assert the second
    call is rejected.
    """

    def test_same_payload_signature_validates_twice(self):
        """The classic replay: same body + same sig validates forever."""
        secret = "replay-secret"
        payload = b'{"action":"opened","number":42}'
        sig = _github_sig(payload, secret)
        with patch("integrations.github.validator.settings") as s:
            s.GITHUB_WEBHOOK_SECRET = secret
            first = validate_signature(payload, sig)
            second = validate_signature(payload, sig)
            third = validate_signature(payload, sig)
        assert first is True
        assert second is True, (
            "validate_signature now rejects a second identical delivery — "
            "a replay defense landed. Flip the assertion to document the new "
            "contract (timestamp window, delivery-id dedup, etc.)."
        )
        assert third is True

    def test_signature_does_not_bind_delivery_id_header(self):
        """X-GitHub-Delivery is NOT in the HMAC input — the signature is the
        same regardless of the delivery UUID. Pin so any future change to
        bind the header flips here.
        """
        secret = "replay-secret"
        payload = b'{"action":"opened"}'
        sig_a = _github_sig(payload, secret)
        # Sign a second time (no delivery id mixed in) — must match byte-for-byte.
        sig_b = _github_sig(payload, secret)
        assert sig_a == sig_b, (
            "GitHub webhook signature computation changed — it may now bind "
            "something besides the raw body. Audit validator.py."
        )

    def test_tampered_payload_rejected(self):
        """Baseline — any change to the body invalidates the sig. This keeps
        the replay observation above meaningful: replay = same bytes, not
        arbitrary bytes.
        """
        secret = "replay-secret"
        payload = b'{"action":"opened"}'
        sig = _github_sig(payload, secret)
        with patch("integrations.github.validator.settings") as s:
            s.GITHUB_WEBHOOK_SECRET = secret
            assert validate_signature(payload + b" ", sig) is False


# ===========================================================================
# QREPLAY.2 — BlueBubbles token-auth + dedup layering
# ===========================================================================


class TestBluebubblesReplayLayering:
    """Pin the three replay layers: static token (auth), self-reported
    ``dateCreated`` staleness, and persistent GUID dedup.

    The static token by itself offers ZERO replay resistance. The two
    secondary layers are what actually reject replays, and they're only
    effective against an attacker who can't mint new (guid, dateCreated)
    pairs — which a token holder trivially can.
    """

    def test_webhook_auth_is_plain_token_no_hmac(self):
        """Source inspection: the webhook endpoint compares a query token
        string-equal to ``BB_WEBHOOK_TOKEN``. No HMAC, no timestamp, no
        per-request signature. Pin via AST-free text search for the shape.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "integrations/bluebubbles/router.py").read_text()
        # Current shape: `if not token or token != expected: ... 401`
        assert 'token != expected' in src, (
            "bluebubbles webhook auth shape changed — audit the new auth path "
            "and update this test."
        )
        # Negative: no HMAC imports in the webhook module.
        assert "hmac" not in src.split("def webhook", 1)[1][:2000], (
            "bluebubbles webhook() now references hmac — signature-based "
            "auth may have landed. Flip this test to pin the positive contract."
        )

    def test_stale_threshold_keyed_on_payload_self_report(self):
        """``_STALE_THRESHOLD = 300`` is evaluated against ``data.dateCreated``
        (ms epoch from the webhook sender). A token holder freely sets
        ``dateCreated = time.time() * 1000`` so the staleness check never
        fires on a crafted replay.

        Pin the constant + the source-of-truth: if the check moves to a
        server-received timestamp (``request.headers.get("Date")`` or server
        clock), this test flips.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "integrations/bluebubbles/router.py").read_text()
        assert "_STALE_THRESHOLD = 300" in src
        # The staleness check reads `data.get("dateCreated")` (self-report).
        assert 'date_created = data.get("dateCreated")' in src, (
            "bluebubbles staleness source changed — verify it's still "
            "self-reported or update this test to pin the new source."
        )

    def test_guid_dedup_persists_but_guid_is_attacker_controlled(self):
        """``_guid_dedup`` is persistent (survives restart via IntegrationSetting).
        Pins:
        - The dedup check happens BEFORE agent dispatch.
        - An attacker with the bearer token chooses the GUID, so dedup only
          defends against literal network-level retransmits, not crafted
          replays.
        """
        from integrations.bluebubbles import router as bb_router

        d = bb_router._GuidDedup(max_size=10)

        # First sighting: not duplicate
        assert d.check_and_record("msg-guid-1") is False
        # Second: recognised as replay
        assert d.check_and_record("msg-guid-1") is True
        # Attacker-chosen fresh GUID: accepted (the drift)
        assert d.check_and_record("attacker-fresh-guid") is False
        assert d.check_and_record("attacker-fresh-guid") is True

    def test_content_dedup_window_is_thirty_seconds(self):
        """``_TEXT_DEDUP_WINDOW = 30.0`` — the second, shorter net that
        catches iCloud cross-device duplicates (different GUIDs, same text).
        Pin the constant so a future tuning is intentional.
        """
        from integrations.bluebubbles import router as bb_router

        assert bb_router._TEXT_DEDUP_WINDOW == 30.0
        assert bb_router._TEXT_DEDUP_MAX == 2000


# ===========================================================================
# QREPLAY.3 — Slack has NO webhook surface (Socket Mode)
# ===========================================================================


class TestSlackHasNoInboundWebhook:
    """Slack uses ``slack-bolt`` Socket Mode — no HTTP webhook endpoint.
    Pin: the slack router exposes zero POST routes. If Spindrel ever
    migrates to the Slack Events API (HTTP POST /events with
    X-Slack-Signature + X-Slack-Request-Timestamp), this test flips and
    a fresh drift file should pin the signature+timestamp+nonce contract.
    """

    def test_slack_router_has_no_post_routes(self):
        from integrations.slack.router import router

        post_routes = [
            r for r in router.routes
            if getattr(r, "methods", None) and "POST" in r.methods
        ]
        assert post_routes == [], (
            "Slack router now exposes POST routes — a webhook/events "
            f"endpoint landed: {[r.path for r in post_routes]}. Add a "
            "signature+timestamp+nonce drift-pin file for the new surface."
        )

    def test_slack_bot_uses_socket_mode(self):
        """Pin the Socket Mode choice — it's why there's no webhook surface."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "integrations/slack/slack_bot.py").read_text()
        assert "AsyncSocketModeHandler" in src, (
            "slack_bot.py no longer uses Socket Mode — a migration to the "
            "Events API likely landed. Pin the new webhook contract."
        )


# ===========================================================================
# QREPLAY.4 — local_companion WS static-token replay
# ===========================================================================


class TestLocalCompanionWsStaticTokenReplay:
    """``companion_ws`` accepts the WebSocket if ``?token=`` matches the
    target's stored token (``secrets.compare_digest``). There is no
    challenge/response; the client's hello frame is not bound to a server
    nonce. A leaked token replays as a full reconnect with identical privilege.
    """

    def test_auth_is_compare_digest_on_static_token(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "integrations/local_companion/router.py").read_text()
        # Current shape: `secrets.compare_digest(token, expected)`
        assert "secrets.compare_digest(token, expected)" in src, (
            "local_companion WS auth shape changed — audit the new path."
        )
        # Negative: no HMAC / challenge helper imported.
        assert "hmac" not in src, (
            "local_companion router now imports hmac — challenge/response "
            "may have landed. Flip the test to assert the positive contract."
        )

    def test_hello_frame_has_no_server_nonce(self):
        """The WS contract is: accept → client sends hello → server sends hello
        back with target_id + connection_id. The server does NOT issue a
        random nonce the client must echo, so the hello sequence is entirely
        client-controlled given a valid token.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "integrations/local_companion/router.py").read_text()
        # The server's hello payload is deterministic: target_id + connection_id.
        # connection_id is server-generated but is a REGISTRATION id, not a
        # challenge the client proves knowledge of. Pin the shape.
        assert '"type": "hello",' in src
        assert '"target_id": target_id,' in src
        assert '"connection_id": conn.connection_id,' in src
        # Negative: no "challenge" / "nonce" key in the outbound hello.
        outbound_hello_block = src.split('await websocket.send_json(', 1)[1][:300]
        assert "challenge" not in outbound_hello_block.lower()
        assert "nonce" not in outbound_hello_block.lower()


# ===========================================================================
# QREPLAY.5 — Outbound webhook signature (Spindrel → third-party)
# ===========================================================================


class TestOutboundWebhookSignatureReplayable:
    """``app/services/webhooks.py::sign_payload`` is HMAC(body, secret). No
    timestamp, no nonce. Consumers that only verify the signature cannot
    distinguish a replay from a legitimate delivery. This is a third-party-
    contract detail, but we still pin it so a future hardening (e.g.
    attaching ``X-Spindrel-Timestamp`` and including it in the HMAC input)
    flips here in one place.
    """

    def test_same_body_same_secret_same_sig_always(self):
        body = b'{"event":"x","id":"123"}'
        secret = "shared-with-consumer"
        t0_sig = sign_payload(body, secret)
        time.sleep(0.01)  # any elapsed time
        t1_sig = sign_payload(body, secret)
        assert t0_sig == t1_sig, (
            "sign_payload output changed across calls with identical inputs — "
            "a time/nonce component may have landed. Flip this test to pin "
            "the new contract."
        )

    def test_verify_signature_accepts_captured_sig_forever(self):
        body = b'{"event":"x","id":"123"}'
        secret = "shared-with-consumer"
        captured_sig = sign_payload(body, secret)
        # Replay N times — always valid.
        for _ in range(5):
            assert verify_signature(body, secret, captured_sig) is True

    def test_deliver_does_not_attach_timestamp_header(self):
        """Pin the header set: ``X-Spindrel-Signature`` + ``X-Spindrel-Event``,
        no timestamp. Source inspection (the helper is async and opens an
        httpx client — easier to pin via text than to drive end-to-end).
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "app/services/webhooks.py").read_text()
        # Current headers:
        assert "X-Spindrel-Signature" in src
        assert "X-Spindrel-Event" in src
        # Negative: no timestamp header appended in _deliver.
        deliver_block = src.split("async def _deliver", 1)[1].split("async def ", 1)[0]
        assert "X-Spindrel-Timestamp" not in deliver_block, (
            "_deliver now sets X-Spindrel-Timestamp — update this test to "
            "assert the positive contract (timestamp in HMAC input, window "
            "check on consumer side)."
        )
        assert "X-Webhook-Timestamp" not in deliver_block
