"""Gmail content feed — IMAP polling with ingestion pipeline integration.

Uses stdlib imaplib (sync, wrapped in asyncio.to_thread) to avoid
adding async IMAP dependencies.
"""

from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import imaplib
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from integrations.ingestion.envelope import ExternalMessage, RawMessage
from integrations.ingestion.feed import ContentFeed, CycleResult, FeedItem
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------


def _decode_header(raw: str | None) -> str:
    """Decode an RFC 2047 encoded email header to plain text."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded.append(data.decode("utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _safe_decode(data: bytes, charset: str | None) -> str:
    """Decode bytes with charset, falling back to utf-8 on unknown codec."""
    try:
        return data.decode(charset or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def _extract_body(msg: email.message.Message) -> str:
    """Extract the best plain-text body from a MIME message.

    Prefers text/plain, falls back to text/html (stripped by pipeline).
    """
    if msg.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    plain_parts.append(_safe_decode(payload, part.get_content_charset()))
            elif ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    html_parts.append(_safe_decode(payload, part.get_content_charset()))
        if plain_parts:
            return "\n\n".join(plain_parts)
        if html_parts:
            return "\n\n".join(html_parts)
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return _safe_decode(payload, msg.get_content_charset())
        return ""


def _extract_attachments(msg: email.message.Message) -> list[dict]:
    """Extract attachment metadata (no content download)."""
    attachments: list[dict] = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            filename = part.get_filename()
            if filename:
                filename = _decode_header(filename)
            attachments.append({
                "filename": filename or "unnamed",
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            })
    return attachments


def _safe_filename(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug.

    Falls back to a short hash for non-Latin text that produces no ASCII chars.
    """
    import hashlib

    # Normalize unicode
    normalized = unicodedata.normalize("NFKD", text)
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower())
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    # Truncate
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    # If nothing survived (e.g. CJK/Arabic subject), use a short hash
    if not slug:
        slug = hashlib.sha256(text.encode()).hexdigest()[:12]
    return slug


def _date_slug(date_str: str | None) -> str:
    """Extract YYYY-MM-DD from an email Date header, fallback to today."""
    if date_str:
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            return parsed.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# GmailFeed
# ---------------------------------------------------------------------------


class GmailFeed(ContentFeed):
    """Gmail IMAP content feed."""

    source = "gmail"

    def __init__(
        self,
        pipeline: IngestionPipeline,
        store: IngestionStore,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        email_addr: str = "",
        password: str = "",
        folders: list[str] | None = None,
        max_per_poll: int = 25,
        initial_fetch: str = "new",
    ) -> None:
        super().__init__(pipeline, store)
        self.host = host
        self.port = port
        self.email_addr = email_addr
        self.password = password
        self.folders = folders or ["INBOX"]
        self.max_per_poll = max_per_poll
        self.initial_fetch = initial_fetch
        self._imap: imaplib.IMAP4_SSL | None = None

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Establish IMAP connection (sync)."""
        if self._imap:
            try:
                self._imap.noop()
                return self._imap
            except Exception:
                self._disconnect()
        conn = imaplib.IMAP4_SSL(self.host, self.port)
        conn.login(self.email_addr, self.password)
        self._imap = conn
        return conn

    def _disconnect(self) -> None:
        """Close IMAP connection safely."""
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    async def fetch_items(self) -> list[RawMessage]:
        """Fetch new emails via IMAP, starting from last cursor UID."""
        return await asyncio.to_thread(self._fetch_items_sync)

    def _fetch_items_sync(
        self,
        *,
        since_days: int | None = None,
        max_items: int | None = None,
        folders_override: list[str] | None = None,
    ) -> list[RawMessage]:
        """Synchronous IMAP fetch.

        Args:
            since_days: Override — fetch emails from the last N days
                        (ignores cursor, uses IMAP SINCE).
            max_items: Override — max emails to fetch this call.
            folders_override: Override — folders to poll this call.
        """
        conn = self._connect()
        items: list[RawMessage] = []
        effective_folders = folders_override or self.folders
        effective_max = max_items if max_items is not None else self.max_per_poll

        for folder in effective_folders:
            try:
                status, _ = conn.select(folder, readonly=True)
                if status != "OK":
                    logger.warning("Cannot select folder %s", folder)
                    continue

                cursor_key = f"gmail:{folder}"
                last_uid = self.store.get_cursor(cursor_key)

                # Build search criteria
                if since_days is not None:
                    # Explicit override — date-based search, ignore cursor
                    since_date = (
                        datetime.now(timezone.utc) - timedelta(days=since_days)
                    ).strftime("%d-%b-%Y")
                    search_criteria = f"SINCE {since_date}"
                elif last_uid:
                    search_criteria = f"UID {int(last_uid) + 1}:*"
                elif self.initial_fetch == "new":
                    # Seed cursor to highest UID, skip existing mail
                    max_uid_val = self._get_max_uid(conn)
                    if max_uid_val:
                        self.store.set_cursor(cursor_key, str(max_uid_val))
                        logger.info(
                            "Initial fetch=new: seeded %s cursor to UID %s",
                            folder, max_uid_val,
                        )
                    continue
                elif self.initial_fetch.startswith("recent:"):
                    days = int(self.initial_fetch.split(":")[1])
                    since_date = (
                        datetime.now(timezone.utc) - timedelta(days=days)
                    ).strftime("%d-%b-%Y")
                    search_criteria = f"SINCE {since_date}"
                else:  # "all" or anything else
                    search_criteria = "ALL"

                status, data = conn.uid("search", None, search_criteria)
                if status != "OK":
                    logger.warning("IMAP search failed for %s", folder)
                    continue

                uid_list = data[0].split() if data[0] else []

                # Filter out the cursor UID itself (IMAP range is inclusive)
                if last_uid and since_days is None:
                    uid_list = [u for u in uid_list if int(u) > int(last_uid)]

                # Limit per poll
                uid_list = uid_list[:effective_max]

                max_uid = last_uid

                for uid_bytes in uid_list:
                    uid = uid_bytes.decode() if isinstance(uid_bytes, bytes) else str(uid_bytes)
                    try:
                        status, msg_data = conn.uid("fetch", uid, "(RFC822)")
                        if status != "OK" or not msg_data or not msg_data[0]:
                            continue

                        raw_email = msg_data[0][1]
                        if isinstance(raw_email, bytes):
                            raw_email = raw_email.decode("utf-8", errors="replace")

                        msg = email.message_from_string(raw_email)
                        body = _extract_body(msg)
                        attachments = _extract_attachments(msg)

                        metadata = {
                            "from": _decode_header(msg.get("From")),
                            "to": _decode_header(msg.get("To")),
                            "subject": _decode_header(msg.get("Subject")),
                            "date": msg.get("Date", ""),
                            "message_id": msg.get("Message-ID", ""),
                            "folder": folder,
                        }
                        if attachments:
                            metadata["attachments"] = attachments

                        items.append(RawMessage(
                            source="gmail",
                            source_id=f"gmail:{folder}:{uid}",
                            raw_content=body,
                            metadata=metadata,
                        ))

                        if max_uid is None or int(uid) > int(max_uid):
                            max_uid = uid

                    except Exception:
                        logger.exception("Failed to fetch UID %s from %s", uid, folder)

                # Update cursor to the highest UID we successfully fetched
                if max_uid and max_uid != last_uid:
                    self.store.set_cursor(cursor_key, str(max_uid))

            except Exception:
                logger.exception("Error processing folder %s", folder)

        return items

    @staticmethod
    def _get_max_uid(conn: imaplib.IMAP4_SSL) -> int | None:
        """Find the highest UID in the currently selected folder."""
        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data[0]:
            return None
        uid_list = data[0].split()
        return max(int(u) for u in uid_list) if uid_list else None

    async def fetch_items_with_overrides(
        self,
        *,
        since_days: int | None = None,
        max_items: int | None = None,
        folders: list[str] | None = None,
    ) -> list[RawMessage]:
        """Fetch items with per-call overrides (used by trigger_gmail_poll tool)."""
        return await asyncio.to_thread(
            self._fetch_items_sync,
            since_days=since_days,
            max_items=max_items,
            folders_override=folders,
        )

    async def _run_pipeline(self, raw_items: list[RawMessage]) -> CycleResult:
        """Process pre-fetched raw items through the ingestion pipeline.

        Same logic as ContentFeed.run_cycle() but skips the fetch step,
        allowing the caller to provide items from an override fetch.
        """
        result = CycleResult()
        result.fetched = len(raw_items)

        for raw in raw_items:
            try:
                if self.store.already_processed(raw.source, raw.source_id):
                    result.skipped += 1
                    continue

                envelope = await self.pipeline.process(raw)
                if envelope is None:
                    result.quarantined += 1
                    continue

                item = self.format_item(envelope)
                result.items.append(item)
                result.passed += 1
            except Exception as exc:
                result.errors.append(f"item {raw.source_id}: {exc}")

        return result

    def format_item(self, envelope: ExternalMessage) -> FeedItem:
        """Convert processed email envelope to a FeedItem with markdown formatting."""
        meta = envelope.metadata
        subject = meta.get("subject", "No Subject")
        from_addr = meta.get("from", "Unknown")
        to_addr = meta.get("to", "")
        date_str = meta.get("date", "")
        date_slug = _date_slug(date_str)
        attachments = meta.get("attachments", [])

        # Build markdown body
        lines = [
            f"# {subject}",
            "",
            f"- **From**: {from_addr}",
            f"- **To**: {to_addr}",
            f"- **Date**: {date_str}",
        ]

        if attachments:
            lines.append(f"- **Attachments**: {len(attachments)}")
            for att in attachments:
                lines.append(f"  - {att['filename']} ({att['content_type']}, {att['size']} bytes)")

        lines.append(f"- **Risk**: {envelope.risk.risk_level}")
        if envelope.risk.layer2_flags:
            lines.append(f"- **Security flags**: {', '.join(envelope.risk.layer2_flags)}")

        lines.extend(["", "---", "", envelope.body])

        filename = _safe_filename(subject)
        suggested_path = f"data/gmail/{date_slug}-{filename}.md"

        return FeedItem(
            title=subject,
            body="\n".join(lines),
            source_id=envelope.source_id,
            metadata=envelope.metadata,
            suggested_path=suggested_path,
            risk_level=envelope.risk.risk_level,
        )
