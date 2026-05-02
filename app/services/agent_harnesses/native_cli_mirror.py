"""Mirror native CLI transcript records back into Spindrel sessions.

The embedded native CLI view is a real PTY, not a fake chat renderer. To keep
Spindrel history useful after a user switches into that view, mirror structured
Codex/Claude transcript JSONL records instead of scraping terminal bytes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from app.agent.bots import get_bot
from app.db.engine import async_session
from app.db.models import Message, Session
from app.services.sessions import store_passive_message
from app.services.terminal import get_session as get_terminal_session

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC = 1.5
_MAX_IDLE_POLLS_AFTER_TERMINAL_EXIT = 4
_MIRROR_TASKS: set[asyncio.Task] = set()
_INPUT_SYNC_TASKS: set[asyncio.Task] = set()
_INPUT_SYNCERS: dict[str, "_NativeCliInputSyncer"] = {}
_SPINDREL_BLOCK_RE = re.compile(
    r"<spindrel_(?:host_instructions|context_hints|tool_guidance)>.*?</spindrel_(?:host_instructions|context_hints|tool_guidance)>",
    re.DOTALL,
)
_ENV_CONTEXT_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL)
_NATIVE_CLI_SYNTHETIC_TEXT = {
    "Continue from where you left off.",
    "No response requested.",
}
_NATIVE_CLI_MODEL_RE = re.compile(r"^/model(?:\s+(?P<model>\S.*?))?\s*$", re.IGNORECASE)
_NATIVE_CLI_EFFORT_RE = re.compile(r"^/effort(?:\s+(?P<effort>\S+))?\s*$", re.IGNORECASE)
_NATIVE_CLI_CLEAR_VALUES = {"default", "runtime-default", "runtime_default", "clear", "none", "null", "off"}
_NATIVE_CLI_SETTINGS_ACK_RE = re.compile(r"^Using\s+`?[^`\n]+`?\s+for this turn\.\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class NativeCliMirrorRecord:
    key: str
    role: str
    content: str


@dataclass
class _NativeCliInputSyncer:
    spindrel_session_id: uuid.UUID
    runtime_name: str
    buffer: str = ""

    def feed(self, data: bytes) -> list[str]:
        """Return complete command lines typed into the embedded PTY."""

        text = data.decode("utf-8", errors="ignore")
        lines: list[str] = []
        for char in text:
            if char in {"\r", "\n"}:
                line = self.buffer.strip()
                self.buffer = ""
                if line:
                    lines.append(line)
                continue
            if char == "\x03":  # Ctrl-C clears the active input line.
                self.buffer = ""
                continue
            if char in {"\b", "\x7f"}:
                self.buffer = self.buffer[:-1]
                continue
            if char == "\x1b":
                continue
            if char.isprintable() or char == "\t":
                self.buffer = (self.buffer + char)[-2048:]
        return lines


def start_native_cli_mirror(
    *,
    terminal_session_id: str,
    spindrel_session_id: uuid.UUID,
    runtime_name: str,
    native_session_id: str | None,
    cwd: str,
    bot_id: str,
    channel_id: uuid.UUID | None,
) -> None:
    """Start a best-effort mirror task for one embedded native CLI session."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("native cli mirror skipped: no running event loop")
        return

    _INPUT_SYNCERS[terminal_session_id] = _NativeCliInputSyncer(
        spindrel_session_id=spindrel_session_id,
        runtime_name=runtime_name,
    )
    task = loop.create_task(
        _mirror_loop(
            terminal_session_id=terminal_session_id,
            spindrel_session_id=spindrel_session_id,
            runtime_name=runtime_name,
            native_session_id=native_session_id,
            cwd=cwd,
            bot_id=bot_id,
            channel_id=channel_id,
        )
    )
    _MIRROR_TASKS.add(task)
    task.add_done_callback(_MIRROR_TASKS.discard)


def record_native_cli_terminal_input(terminal_session_id: str, data: bytes) -> None:
    """Observe embedded native CLI input and sync simple settings immediately.

    Transcript polling remains the durable history path. This hook only watches
    user-submitted slash commands that change runtime settings so the Spindrel
    composer does not lag behind the real CLI after switching surfaces.
    """

    syncer = _INPUT_SYNCERS.get(terminal_session_id)
    if syncer is None:
        return
    lines = syncer.feed(data)
    if not lines:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for line in lines:
        if not _native_cli_settings_patch(line):
            continue
        task = loop.create_task(
            _sync_native_cli_input_command(
                spindrel_session_id=syncer.spindrel_session_id,
                runtime_name=syncer.runtime_name,
                line=line,
            )
        )
        _INPUT_SYNC_TASKS.add(task)
        task.add_done_callback(_INPUT_SYNC_TASKS.discard)


def unregister_native_cli_terminal_input(terminal_session_id: str) -> None:
    _INPUT_SYNCERS.pop(terminal_session_id, None)


async def _mirror_loop(
    *,
    terminal_session_id: str,
    spindrel_session_id: uuid.UUID,
    runtime_name: str,
    native_session_id: str | None,
    cwd: str,
    bot_id: str,
    channel_id: uuid.UUID | None,
) -> None:
    try:
        path: Path | None = None
        offset = 0
        initialized = False
        seen: set[str] = set()
        idle_after_exit = 0
        skip_existing = bool(native_session_id)
        started_at = time.time()

        while True:
            terminal = get_terminal_session(terminal_session_id)
            if terminal is None or terminal.closed:
                idle_after_exit += 1
            else:
                idle_after_exit = 0

            if path is None:
                path = _find_native_transcript(
                    runtime_name,
                    native_session_id,
                    cwd,
                    started_after=started_at - 2,
                )
                if path is not None and skip_existing and not initialized:
                    try:
                        offset = path.stat().st_size
                    except OSError:
                        offset = 0
                    initialized = True

            if path is not None:
                try:
                    offset, records = _read_new_records(
                        path,
                        offset=offset,
                        runtime_name=runtime_name,
                    )
                except Exception:
                    logger.warning(
                        "native cli mirror failed reading %s transcript %s",
                        runtime_name,
                        path,
                        exc_info=True,
                    )
                    records = []
                for record in records:
                    if record.key in seen:
                        continue
                    seen.add(record.key)
                    await _persist_mirrored_record(
                        spindrel_session_id=spindrel_session_id,
                        bot_id=bot_id,
                        channel_id=channel_id,
                        runtime_name=runtime_name,
                        native_session_id=native_session_id,
                        transcript_path=path,
                        record=record,
                    )

            if idle_after_exit >= _MAX_IDLE_POLLS_AFTER_TERMINAL_EXIT:
                return
            await asyncio.sleep(_POLL_INTERVAL_SEC)
    finally:
        unregister_native_cli_terminal_input(terminal_session_id)


def _find_native_transcript(
    runtime_name: str,
    native_session_id: str | None,
    cwd: str,
    *,
    started_after: float = 0,
) -> Path | None:
    if runtime_name == "codex":
        return _find_codex_transcript(native_session_id, cwd=cwd, started_after=started_after)
    if runtime_name == "claude-code":
        return _find_claude_transcript(native_session_id, cwd, started_after=started_after)
    return None


def _find_codex_transcript(
    native_session_id: str | None,
    *,
    cwd: str = "",
    started_after: float = 0,
) -> Path | None:
    root = Path.home() / ".codex" / "sessions"
    if not root.exists():
        return None
    if native_session_id:
        matches = sorted(
            root.glob(f"**/*{native_session_id}*.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if matches:
            return matches[0]
    candidates = sorted(
        (
            path
            for path in root.glob("**/*.jsonl")
            if _is_recent_transcript_for_cwd(path, cwd=cwd, started_after=started_after)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _find_claude_transcript(
    native_session_id: str | None,
    cwd: str,
    *,
    started_after: float = 0,
) -> Path | None:
    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return None
    if native_session_id:
        project_dir = root / _claude_project_dir_name(cwd)
        exact = project_dir / f"{native_session_id}.jsonl"
        if exact.exists():
            return exact
        matches = sorted(
            root.glob(f"**/{native_session_id}.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if matches:
            return matches[0]
    candidates = sorted(
        (
            path
            for path in root.glob("**/*.jsonl")
            if _is_recent_transcript_for_cwd(path, cwd=cwd, started_after=started_after)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _claude_project_dir_name(cwd: str) -> str:
    raw = os.path.realpath(cwd or "")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    return f"-{slug}" if slug else "-"


def _is_recent_transcript_for_cwd(path: Path, *, cwd: str, started_after: float) -> bool:
    try:
        if path.stat().st_mtime < started_after:
            return False
    except OSError:
        return False
    if not cwd:
        return True
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:12000]
    except OSError:
        return False
    return os.path.realpath(cwd) in sample or cwd in sample


def _read_new_records(
    path: Path,
    *,
    offset: int,
    runtime_name: str,
) -> tuple[int, list[NativeCliMirrorRecord]]:
    records: list[NativeCliMirrorRecord] = []
    with path.open("rb") as handle:
        handle.seek(offset)
        for raw_line in handle:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if runtime_name == "codex":
                records.extend(_parse_codex_jsonl_record(payload))
            elif runtime_name == "claude-code":
                parsed = _parse_claude_jsonl_record(payload)
                if parsed is not None:
                    records.append(parsed)
        return handle.tell(), records


def _native_session_id_from_transcript(path: Path, *, runtime_name: str) -> str | None:
    """Best-effort native session id discovery from a CLI transcript file."""

    if runtime_name == "claude-code":
        stem = path.stem.strip()
        return stem or None

    if runtime_name != "codex":
        return None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(20), handle):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") != "session_meta":
                    continue
                meta = payload.get("payload")
                if not isinstance(meta, dict):
                    continue
                session_id = meta.get("id")
                if isinstance(session_id, str) and session_id.strip():
                    return session_id.strip()
    except OSError:
        return None
    return None


def _parse_codex_jsonl_record(payload: dict) -> Iterable[NativeCliMirrorRecord]:
    if payload.get("type") != "response_item":
        return ()
    item = payload.get("payload")
    if not isinstance(item, dict) or item.get("type") != "message":
        return ()
    role = item.get("role")
    if role not in {"user", "assistant"}:
        return ()
    text = _extract_content_text(item.get("content"), text_types={"input_text", "output_text", "text"})
    text = _clean_native_text(text)
    if not text:
        return ()
    key = str(item.get("id") or f"{payload.get('timestamp', '')}:{role}:{hash(text)}")
    return (NativeCliMirrorRecord(key=f"codex:{key}", role=role, content=text),)


def _parse_claude_jsonl_record(payload: dict) -> NativeCliMirrorRecord | None:
    role = payload.get("type")
    if role not in {"user", "assistant"}:
        return None
    message = payload.get("message")
    if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
        return None
    text = _extract_content_text(message.get("content"), text_types={"text"})
    text = _clean_native_text(text)
    if not text:
        return None
    key = str(payload.get("uuid") or message.get("id") or f"{payload.get('timestamp', '')}:{role}:{hash(text)}")
    return NativeCliMirrorRecord(key=f"claude:{key}", role=message["role"], content=text)


def _extract_content_text(content: object, *, text_types: set[str]) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") not in text_types:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def _clean_native_text(text: str) -> str:
    if not text:
        return ""
    cleaned = _SPINDREL_BLOCK_RE.sub("", text)
    cleaned = _ENV_CONTEXT_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if cleaned in _NATIVE_CLI_SYNTHETIC_TEXT:
        return ""
    return cleaned


async def _persist_mirrored_record(
    *,
    spindrel_session_id: uuid.UUID,
    bot_id: str,
    channel_id: uuid.UUID | None,
    runtime_name: str,
    native_session_id: str | None,
    transcript_path: Path,
    record: NativeCliMirrorRecord,
) -> None:
    effective_native_session_id = native_session_id or _native_session_id_from_transcript(
        transcript_path,
        runtime_name=runtime_name,
    )
    metadata = {
        "harness_native_cli": {
            "runtime": runtime_name,
            "native_session_id": effective_native_session_id,
            "record_key": record.key,
            "transcript_path": str(transcript_path),
        },
        "source": "harness_native_cli",
        "include_in_memory": True,
        "trigger_rag": False,
    }
    if effective_native_session_id:
        metadata["harness"] = {
            "runtime": runtime_name,
            "session_id": effective_native_session_id,
            "source": "harness_native_cli",
        }
    if record.role == "assistant" and effective_native_session_id:
        try:
            bot = get_bot(bot_id)
            display = bot.display_name or bot.name or bot_id
        except Exception:
            display = bot_id
        metadata.update(
            {
                "sender_type": "bot",
                "sender_id": f"bot:{bot_id}",
                "sender_display_name": display,
            }
        )
    async with async_session() as db:
        session = await db.get(Session, spindrel_session_id)
        if session is None:
            return
        await _sync_native_cli_settings(
            db,
            spindrel_session_id=spindrel_session_id,
            runtime_name=runtime_name,
            record=record,
        )
        if await _has_mirrored_record(db, spindrel_session_id=spindrel_session_id, record_key=record.key):
            return
        if _is_native_cli_settings_management_record(record):
            await db.commit()
            return
        if await _has_host_persisted_duplicate(
            db,
            spindrel_session_id=spindrel_session_id,
            record=record,
        ):
            await db.commit()
            return
        await store_passive_message(
            db,
            spindrel_session_id,
            record.content,
            metadata,
            channel_id=channel_id or session.channel_id,
            role=record.role,
        )


async def _has_mirrored_record(db, *, spindrel_session_id: uuid.UUID, record_key: str) -> bool:
    existing = await db.scalar(
        select(Message.id)
        .where(Message.session_id == spindrel_session_id)
        .where(Message.metadata_["harness_native_cli"]["record_key"].astext == record_key)
        .limit(1)
    )
    return existing is not None


async def _has_host_persisted_duplicate(
    db,
    *,
    spindrel_session_id: uuid.UUID,
    record: NativeCliMirrorRecord,
) -> bool:
    """Skip mirror echo for native CLI records that came from Spindrel chat.

    Native non-interactive surfaces such as ``codex exec resume`` append to the
    same CLI transcript files the embedded terminal mirror watches. The chat
    turn already persisted those user/assistant rows, so the mirror should not
    echo them back a second time.
    """

    rows = (
        await db.scalars(
            select(Message)
            .where(Message.session_id == spindrel_session_id)
            .where(Message.role == record.role)
            .where(Message.content == record.content)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
    ).all()
    for row in rows:
        metadata = row.metadata_ or {}
        if metadata.get("source") != "harness_native_cli":
            return True
        harness = metadata.get("harness")
        if isinstance(harness, dict) and harness.get("codex_resume_surface") == "exec_resume":
            return True
    return False


def _is_native_cli_settings_management_record(record: NativeCliMirrorRecord) -> bool:
    if record.role == "user":
        return bool(_native_cli_settings_patch(record.content))
    if record.role == "assistant":
        return bool(_NATIVE_CLI_SETTINGS_ACK_RE.match((record.content or "").strip()))
    return False


async def _sync_native_cli_settings(
    db,
    *,
    spindrel_session_id: uuid.UUID,
    runtime_name: str,
    record: NativeCliMirrorRecord,
) -> None:
    """Reflect simple native CLI model/effort commands into Spindrel settings.

    The terminal view is allowed to be a real runtime CLI. If the user changes
    runtime knobs there, the Spindrel composer and the next chat-mode turn need
    to inherit the same setting instead of drifting back to "default".
    """

    if record.role != "user":
        return
    patch = _native_cli_settings_patch(record.content)
    if not patch:
        return

    try:
        from app.services.agent_harnesses.settings import patch_session_settings

        await patch_session_settings(db, spindrel_session_id, patch=patch)
    except Exception:
        logger.warning(
            "native cli mirror failed to sync %s settings from record %s",
            runtime_name,
            record.key,
            exc_info=True,
        )


def _native_cli_settings_patch(text: str | None) -> dict[str, str | None]:
    patch: dict[str, str | None] = {}
    text = (text or "").strip()
    model_match = _NATIVE_CLI_MODEL_RE.match(text)
    if model_match:
        raw_model = (model_match.group("model") or "").strip()
        model = raw_model.strip("\"'")
        if model:
            patch["model"] = None if model.lower() in _NATIVE_CLI_CLEAR_VALUES else model
    effort_match = _NATIVE_CLI_EFFORT_RE.match(text)
    if effort_match:
        raw_effort = (effort_match.group("effort") or "").strip()
        effort = raw_effort.strip("\"'")
        if effort:
            patch["effort"] = None if effort.lower() in _NATIVE_CLI_CLEAR_VALUES else effort
    return patch


async def _sync_native_cli_input_command(
    *,
    spindrel_session_id: uuid.UUID,
    runtime_name: str,
    line: str,
) -> None:
    patch = _native_cli_settings_patch(line)
    if not patch:
        return
    try:
        from app.services.agent_harnesses.settings import patch_session_settings

        async with async_session() as db:
            await patch_session_settings(db, spindrel_session_id, patch=patch)
    except Exception:
        logger.warning(
            "native cli terminal input failed to sync %s settings from line %r",
            runtime_name,
            line,
            exc_info=True,
        )
