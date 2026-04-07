"""Slack file upload helpers used by the task dispatcher (and any other non-Bolt code paths).

The Slack Bolt integration uses AsyncWebClient.files_upload_v2, which handles the
three-step upload flow internally.  For code paths that don't have a Bolt client
(e.g. the task worker) we replicate those three steps here using plain httpx.

Reference: https://api.slack.com/methods/files.getUploadURLExternal
"""
from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


_DEFAULT_UPLOAD_USERNAME = "Attachment"
_DEFAULT_UPLOAD_ICON = ":camera:"


async def upload_image(
    *,
    token: str,
    channel_id: str,
    thread_ts: str | None,
    reply_in_thread: bool,
    action: dict,
    username: str | None = None,
    icon_emoji: str | None = None,
) -> str | None:
    """Upload an upload_image client_action to a Slack channel.

    Args:
        token: Slack bot token (xoxb-…).
        channel_id: Target channel ID.
        thread_ts: Thread timestamp to reply into (or None for top-level).
        reply_in_thread: When True *and* thread_ts is set, post inside the thread.
        action: client_action dict with keys: data (base64), filename, caption.
        username: Display name for the caption message (default "Attachment").
        icon_emoji: Icon emoji for the caption message (default ":camera:").
    """
    raw = action.get("data")
    if not raw:
        return None
    try:
        img_bytes = base64.b64decode(raw)
    except Exception:
        logger.warning("slack_uploads: could not base64-decode image data")
        return None

    filename = action.get("filename") or "generated.png"
    caption = action.get("caption") or None
    headers = {"Authorization": f"Bearer {token}"}

    # Post caption as an attributed chat message (file uploads always show as the app)
    if caption:
        msg_payload: dict = {
            "channel": channel_id,
            "text": caption,
            "username": username or _DEFAULT_UPLOAD_USERNAME,
            "icon_emoji": icon_emoji or _DEFAULT_UPLOAD_ICON,
        }
        if thread_ts and reply_in_thread:
            msg_payload["thread_ts"] = thread_ts
        try:
            r = await _http.post(
                "https://slack.com/api/chat.postMessage",
                json=msg_payload,
                headers=headers,
            )
            r.raise_for_status()
        except Exception:
            logger.warning("slack_uploads: failed to post caption message", exc_info=True)

    # Step 1: request an upload URL
    # NOTE: files.getUploadURLExternal requires form-encoded (not JSON) body.
    try:
        r = await _http.post(
            "https://slack.com/api/files.getUploadURLExternal",
            data={"filename": filename, "length": str(len(img_bytes))},
            headers=headers,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            logger.error("slack_uploads: getUploadURLExternal failed: %s", payload.get("error"))
            return None
        upload_url: str = payload["upload_url"]
        file_id: str = payload["file_id"]
    except Exception:
        logger.exception("slack_uploads: failed to get upload URL")
        return None

    # Step 2: PUT/POST the raw bytes to the pre-signed URL
    try:
        r = await _http.post(upload_url, content=img_bytes)
        r.raise_for_status()
    except Exception:
        logger.exception("slack_uploads: failed to upload image bytes")
        return None

    # Step 3: complete the upload and share to the channel (no initial_comment — caption posted above)
    try:
        file_entry: dict = {"id": file_id}
        if caption:
            file_entry["title"] = caption
        complete: dict = {"files": [file_entry], "channel_id": channel_id}
        if thread_ts and reply_in_thread:
            complete["thread_ts"] = thread_ts
        r = await _http.post(
            "https://slack.com/api/files.completeUploadExternal",
            json=complete,
            headers=headers,
        )
        r.raise_for_status()
        result = r.json()
        if not result.get("ok"):
            logger.error("slack_uploads: completeUploadExternal failed: %s", result.get("error"))
            return None
    except Exception:
        logger.exception("slack_uploads: failed to complete upload")
        return None

    # Persist Slack file_id on the attachment so we can delete it later
    attachment_id = action.get("attachment_id")
    if attachment_id and file_id:
        try:
            await _store_slack_file_id(attachment_id, file_id)
        except Exception:
            logger.warning("slack_uploads: failed to store file_id on attachment %s", attachment_id, exc_info=True)

    return file_id


async def _store_slack_file_id(attachment_id: str, slack_file_id: str) -> None:
    """Save the Slack file_id in the attachment's metadata for later deletion."""
    import copy
    import uuid

    from sqlalchemy.orm.attributes import flag_modified

    from app.db.engine import async_session
    from app.db.models import Attachment

    att_uuid = uuid.UUID(attachment_id)
    async with async_session() as db:
        att = await db.get(Attachment, att_uuid)
        if att:
            meta = copy.deepcopy(att.metadata_) if att.metadata_ else {}
            meta["slack_file_id"] = slack_file_id
            att.metadata_ = meta
            flag_modified(att, "metadata_")
            await db.commit()


async def delete_slack_file(token: str, file_id: str) -> bool:
    """Delete a file from Slack via files.delete API."""
    try:
        r = await _http.post(
            "https://slack.com/api/files.delete",
            data={"file": file_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        result = r.json()
        if not result.get("ok"):
            logger.error("slack_uploads: files.delete failed: %s", result.get("error"))
            return False
        return True
    except Exception:
        logger.exception("slack_uploads: failed to delete file %s", file_id)
        return False
