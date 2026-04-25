"""Slack attachment deletion delivery."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from integrations.sdk import ChannelEvent, DeliveryReceipt, DispatchTarget
from integrations.slack.target import SlackTarget

logger = logging.getLogger(__name__)

DeleteSlackFile = Callable[[str, str], Awaitable[bool]]


async def _delete_slack_file(token: str, file_id: str) -> bool:
    from integrations.slack.uploads import delete_slack_file

    return await delete_slack_file(token, file_id)


class SlackAttachmentDelivery:
    """Delete Slack-hosted files for attachment deletion paths."""

    def __init__(
        self,
        *,
        delete_file: DeleteSlackFile = _delete_slack_file,
    ) -> None:
        self._delete_file = delete_file

    async def render(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        metadata = getattr(payload, "metadata", {}) or {}
        slack_file_id = metadata.get("slack_file_id")
        if not slack_file_id:
            return DeliveryReceipt.skipped("attachment_deleted without slack_file_id")
        try:
            ok = await self._delete_file(target.token, slack_file_id)
        except Exception as exc:
            logger.exception(
                "SlackAttachmentDelivery: file delete failed for %s",
                slack_file_id,
            )
            return DeliveryReceipt.failed(str(exc), retryable=True)
        return DeliveryReceipt.ok() if ok else DeliveryReceipt.failed(
            "delete_slack_file returned False", retryable=True,
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        if not isinstance(target, SlackTarget):
            return False
        slack_file_id = (attachment_metadata or {}).get("slack_file_id")
        if not target.token or not slack_file_id:
            return False
        try:
            return await self._delete_file(target.token, slack_file_id)
        except Exception:
            logger.exception(
                "SlackAttachmentDelivery.delete_attachment failed for %s",
                slack_file_id,
            )
            return False


__all__ = ["SlackAttachmentDelivery"]
