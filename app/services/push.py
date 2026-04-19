"""Web Push delivery.

One entry point — `send_push(user_id, title, body, ...)` — used by both
the bot-callable `send_push_notification` tool and the external
`POST /api/v1/push/send` endpoint. VAPID credentials come from
`app.config.settings.VAPID_*` (generated via
`scripts/generate_vapid_keys.py`). When unset, the service raises
`PushDisabledError` so callers can surface a clean message instead of
silently dropping.

Endpoint hygiene: a 404 or 410 response from the push service means the
subscription is dead (user cleared site data, denied permission, etc.);
those rows are pruned inline so repeated sends don't keep pounding a
gone endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import PushSubscription
from app.services import presence

logger = logging.getLogger(__name__)


class PushDisabledError(RuntimeError):
    """Raised when VAPID is not configured."""


class UserSkippedActiveError(RuntimeError):
    """Raised when `only_if_inactive=True` and the user is currently active."""


@dataclass
class PushResult:
    sent: int
    pruned: int
    failed: int
    skipped_active: bool = False


def _require_vapid() -> tuple[str, str, str]:
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY or not settings.VAPID_SUBJECT:
        raise PushDisabledError(
            "Web Push is not configured. Run `python scripts/generate_vapid_keys.py` "
            "and paste the output into .env, then restart the server."
        )
    return settings.VAPID_PRIVATE_KEY, settings.VAPID_PUBLIC_KEY, settings.VAPID_SUBJECT


def _pywebpush_send(
    subscription_info: dict,
    payload: str,
    vapid_private_key: str,
    vapid_subject: str,
) -> int:
    """Blocking wire send. Called via `asyncio.to_thread`. Returns the HTTP
    status code; raises `WebPushException` on transport error. """
    # Imported lazily — pywebpush is an optional dep that won't be present
    # in test/dev envs that never hit push code.
    from pywebpush import webpush
    resp = webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims={"sub": vapid_subject},
    )
    return resp.status_code


async def send_push(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    body: str,
    *,
    url: str | None = None,
    tag: str | None = None,
    icon: str | None = None,
    badge: str | None = None,
    data: dict | None = None,
    only_if_inactive: bool = True,
) -> PushResult:
    """Send a push notification to every device the user has subscribed.

    When `only_if_inactive` is True (the default) and the user's frontend
    has pinged presence within the last ~2 minutes, skips the send and
    returns `PushResult(skipped_active=True)`. """
    vapid_private, _vapid_public, vapid_subject = _require_vapid()

    if only_if_inactive and presence.is_active(user_id):
        logger.debug("push skipped: user %s is active", user_id)
        return PushResult(sent=0, pruned=0, failed=0, skipped_active=True)

    rows = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
    ).scalars().all()
    if not rows:
        return PushResult(sent=0, pruned=0, failed=0)

    payload_obj = {"title": title, "body": body}
    if url: payload_obj["url"] = url
    if tag: payload_obj["tag"] = tag
    if icon: payload_obj["icon"] = icon
    if badge: payload_obj["badge"] = badge
    if data: payload_obj["data"] = data
    payload = json.dumps(payload_obj, separators=(",", ":"))

    # Import once; failures surface per-row below.
    try:
        from pywebpush import WebPushException  # noqa: F401
    except ImportError:
        raise PushDisabledError("pywebpush not installed. Run `pip install pywebpush`.")

    sent = 0
    pruned = 0
    failed = 0
    prune_ids: list[uuid.UUID] = []

    for row in rows:
        sub = {
            "endpoint": row.endpoint,
            "keys": {"p256dh": row.p256dh, "auth": row.auth},
        }
        try:
            status = await asyncio.to_thread(
                _pywebpush_send, sub, payload, vapid_private, vapid_subject,
            )
            if 200 <= status < 300:
                sent += 1
            elif status in (404, 410):
                # Subscription expired — prune
                prune_ids.append(row.id)
                pruned += 1
            else:
                logger.warning("push status %s for subscription %s", status, row.id)
                failed += 1
        except Exception as e:  # noqa: BLE001
            # pywebpush raises WebPushException(response=...) on HTTP errors.
            resp = getattr(e, "response", None)
            if resp is not None and getattr(resp, "status_code", None) in (404, 410):
                prune_ids.append(row.id)
                pruned += 1
            else:
                logger.warning("push send failed for %s: %s", row.id, e)
                failed += 1

    if prune_ids:
        await db.execute(
            delete(PushSubscription).where(PushSubscription.id.in_(prune_ids))
        )

    if sent:
        from datetime import datetime, timezone as _tz
        await db.execute(
            update(PushSubscription)
            .where(PushSubscription.user_id == user_id)
            .where(~PushSubscription.id.in_(prune_ids) if prune_ids else PushSubscription.id.is_not(None))
            .values(last_used_at=datetime.now(_tz.utc))
        )

    await db.commit()
    return PushResult(sent=sent, pruned=pruned, failed=failed)
