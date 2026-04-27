"""Parse plain-text and JSONL log streams into structured error findings.

Used by:
- ``app/tools/local/get_recent_server_errors.py`` (bot-callable read tool)
- ``app/services/system_health_summary.py`` (deterministic daily generator)

Both paths must agree on the same dedupe signature so a finding from the
nightly sweep matches the same ``WorkspaceAttentionItem`` dedupe key the
60s structured detector creates. ``_error_signature`` from
``app/services/workspace_attention.py:665`` is the authoritative function;
we re-import it rather than re-implementing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.workspace_attention import _error_signature, derive_dedupe_key

_TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\):\s*$")
_TRACEBACK_CONT = re.compile(
    r"^("
    r"  File "
    r"|    "
    r"|During handling"
    r"|The above exception"
    r")"
)
_TRACEBACK_FRAME = re.compile(r"^\s+File \"([^\"]+)\", line (\d+)")
_TRACEBACK_LAST_FRAME_RE = re.compile(r"^([A-Za-z_][\w\.]*Error|[A-Za-z_][\w\.]*Exception)(:.*)?$")
_LEVEL_LINE = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b")
_PG_ERROR_LINE = re.compile(r"\b(LOG|ERROR|FATAL):\s")
_ASYNCIO_TASK_RE = re.compile(r"Task exception was never retrieved")


def _classify_severity(text: str) -> str:
    upper = text[:200].upper()
    if "CRITICAL" in upper or "FATAL" in upper:
        return "critical"
    if "ERROR" in upper or "Exception" in text or "Traceback" in text:
        return "error"
    return "warning"


@dataclass
class LogFinding:
    service: str
    severity: str  # info | warning | error | critical
    signature: str
    title: str
    sample: str
    first_seen: datetime
    last_seen: datetime
    count: int = 1
    dedupe_key: str = ""
    extra: dict = field(default_factory=dict)


def _summarize_traceback(block: list[str]) -> tuple[str, str]:
    """Return (title, signature_seed) for a traceback block.

    Title prefers the final ``ExceptionName: message`` line; signature
    seed is ``ExceptionName at last-frame-path:line`` so log-message
    interpolation (request ids, timestamps) doesn't shatter the dedupe.
    """
    title = "Traceback"
    last_frame = ""
    for line in block:
        m = _TRACEBACK_FRAME.match(line)
        if m:
            last_frame = f"{m.group(1)}:{m.group(2)}"
        if _TRACEBACK_LAST_FRAME_RE.match(line.strip()):
            title = line.strip()
    seed = title
    if last_frame:
        seed = f"{title} @ {last_frame}"
    return title[:200], seed[:240]


def parse_text_lines(
    service: str,
    lines: list[str],
    *,
    now: datetime | None = None,
) -> dict[str, LogFinding]:
    """Walk ``lines`` (a chunk of plain log text already split) and return
    ``{dedupe_key: LogFinding}``. Tracebacks are accumulated as blocks; a
    bare ERROR/CRITICAL line becomes its own one-line finding.

    Timestamps come from ``now`` because plain ``docker logs`` lines
    don't always carry a parseable prefix. The summary generator passes
    its run time; the bot-callable tool does the same. Per-line precision
    isn't load-bearing — the dedupe key absorbs repetition.
    """
    when = now or datetime.now(timezone.utc)
    findings: dict[str, LogFinding] = {}

    in_tb = False
    tb_lines: list[str] = []

    def _flush_traceback() -> None:
        nonlocal tb_lines
        if not tb_lines:
            return
        title, seed = _summarize_traceback(tb_lines)
        sig_seed = _error_signature(seed)
        key = derive_dedupe_key("log", service, sig_seed)
        sample = "\n".join(tb_lines[-30:])
        existing = findings.get(key)
        if existing:
            existing.count += 1
            existing.last_seen = when
            existing.sample = sample
        else:
            findings[key] = LogFinding(
                service=service,
                severity="error",
                signature=sig_seed,
                title=title,
                sample=sample,
                first_seen=when,
                last_seen=when,
                dedupe_key=key,
                extra={"kind": "traceback"},
            )
        tb_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            if in_tb:
                _flush_traceback()
                in_tb = False
            continue
        if _TRACEBACK_START.match(line):
            if in_tb:
                _flush_traceback()
            in_tb = True
            tb_lines = [line]
            continue
        if in_tb:
            # Stay inside the traceback while we see continuation markers.
            if _TRACEBACK_CONT.match(line) or _TRACEBACK_LAST_FRAME_RE.match(line.strip()):
                tb_lines.append(line)
                # Final-line heuristic: the exception line itself is the
                # last legal block content. Flush after appending.
                if _TRACEBACK_LAST_FRAME_RE.match(line.strip()):
                    _flush_traceback()
                    in_tb = False
                continue
            # Anything else ends the traceback.
            _flush_traceback()
            in_tb = False
            # Fall through so this line gets ERROR/CRITICAL classification.

        # Non-traceback: ERROR/CRITICAL/FATAL or ``Task exception was never retrieved``.
        if _ASYNCIO_TASK_RE.search(line) or _LEVEL_LINE.search(line) or _PG_ERROR_LINE.search(line):
            severity = _classify_severity(line)
            sig_seed = _error_signature(line)
            key = derive_dedupe_key("log", service, sig_seed)
            existing = findings.get(key)
            if existing:
                existing.count += 1
                existing.last_seen = when
                existing.sample = line[:1000]
            else:
                title = line[:120]
                findings[key] = LogFinding(
                    service=service,
                    severity=severity,
                    signature=sig_seed,
                    title=title,
                    sample=line[:1000],
                    first_seen=when,
                    last_seen=when,
                    dedupe_key=key,
                    extra={"kind": "level_line"},
                )

    if in_tb:
        _flush_traceback()

    return findings


def parse_jsonl_entries(
    service: str,
    entries: list[dict],
) -> dict[str, LogFinding]:
    """Walk JSONL log entries (already parsed) and return findings.

    Operates on the schema written by ``app/services/log_file.py`` —
    ``{ts, level, logger, message, exc_info?}``. Stack traces show up
    in ``exc_info``; we feed them through the same plain-text parser.
    """
    findings: dict[str, LogFinding] = {}
    for entry in entries:
        msg = entry.get("message") or ""
        level = (entry.get("level") or "").upper()
        ts_raw = entry.get("ts")
        when = datetime.now(timezone.utc)
        if isinstance(ts_raw, str):
            try:
                when = datetime.fromisoformat(ts_raw)
            except ValueError:
                pass
        text = msg
        exc = entry.get("exc_info") or ""
        if exc:
            text = f"{msg}\n{exc}"
            sub = parse_text_lines(service, text.splitlines(), now=when)
            for k, f in sub.items():
                if k in findings:
                    findings[k].count += f.count
                    findings[k].last_seen = max(findings[k].last_seen, f.last_seen)
                    findings[k].sample = f.sample
                else:
                    findings[k] = f
            continue
        if level not in {"ERROR", "CRITICAL", "FATAL"}:
            continue
        sig_seed = _error_signature(text)
        key = derive_dedupe_key("log", service, sig_seed)
        existing = findings.get(key)
        if existing:
            existing.count += 1
            existing.last_seen = max(existing.last_seen, when)
        else:
            findings[key] = LogFinding(
                service=service,
                severity="critical" if level in {"CRITICAL", "FATAL"} else "error",
                signature=sig_seed,
                title=text[:120],
                sample=text[:1000],
                first_seen=when,
                last_seen=when,
                dedupe_key=key,
                extra={"kind": "jsonl", "logger": entry.get("logger")},
            )
    return findings


def merge_findings(*sources: dict[str, LogFinding]) -> list[LogFinding]:
    out: dict[str, LogFinding] = {}
    for source in sources:
        for k, f in source.items():
            if k in out:
                out[k].count += f.count
                out[k].first_seen = min(out[k].first_seen, f.first_seen)
                out[k].last_seen = max(out[k].last_seen, f.last_seen)
                if not out[k].sample:
                    out[k].sample = f.sample
            else:
                out[k] = LogFinding(**f.__dict__)
    return sorted(out.values(), key=lambda f: (-f.count, -f.last_seen.timestamp()))
