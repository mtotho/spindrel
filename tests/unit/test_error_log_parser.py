"""Tests for the shared traceback / level-line parser."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.error_log_parser import (
    LogFinding,
    merge_findings,
    parse_jsonl_entries,
    parse_text_lines,
)
from app.services.workspace_attention import _error_signature, derive_dedupe_key


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)


def test_parse_text_lines_captures_traceback_block():
    lines = [
        "12:00:01 INFO  [app] starting",
        "Traceback (most recent call last):",
        '  File "/app/x.py", line 42, in f',
        "    do_thing()",
        '  File "/app/y.py", line 7, in do_thing',
        "    raise ValueError('bad')",
        "ValueError: bad",
        "12:00:03 INFO  [app] continuing",
    ]
    findings = parse_text_lines("svc", lines, now=_now())
    assert len(findings) == 1
    f = next(iter(findings.values()))
    assert f.severity == "error"
    assert "ValueError: bad" in f.title
    assert "/app/y.py" in f.sample
    assert f.extra.get("kind") == "traceback"


def test_parse_text_lines_handles_chained_exception():
    lines = [
        "Traceback (most recent call last):",
        '  File "/app/a.py", line 10, in f',
        "    1/0",
        "ZeroDivisionError: division by zero",
        "",
        "During handling of the above exception, another exception occurred:",
        "",
        "Traceback (most recent call last):",
        '  File "/app/b.py", line 20, in g',
        "    raise RuntimeError('wrapped')",
        "RuntimeError: wrapped",
    ]
    findings = parse_text_lines("svc", lines, now=_now())
    # Two distinct tracebacks → two distinct dedupe keys.
    assert len(findings) == 2
    titles = sorted(f.title for f in findings.values())
    assert any("ZeroDivisionError" in t for t in titles)
    assert any("RuntimeError" in t for t in titles)


def test_parse_text_lines_picks_up_postgres_error():
    lines = [
        "2026-04-26 12:00:00.001 UTC [42] ERROR:  duplicate key value violates unique constraint \"pk_x\"",
        "2026-04-26 12:00:00.002 UTC [42] STATEMENT:  INSERT INTO x ...",
    ]
    findings = parse_text_lines("postgres", lines, now=_now())
    assert findings, "expected at least one finding for postgres ERROR line"
    f = next(iter(findings.values()))
    assert f.severity == "error"
    assert f.service == "postgres"


def test_parse_text_lines_dedupes_repeats_into_count():
    lines = [
        "ERROR connection reset by peer",
        "ERROR connection reset by peer",
        "ERROR connection reset by peer",
    ]
    findings = parse_text_lines("svc", lines, now=_now())
    assert len(findings) == 1
    f = next(iter(findings.values()))
    assert f.count == 3


def test_parse_text_lines_ignores_normal_info_lines():
    lines = [
        "12:00:01 INFO  [app] healthy",
        "12:00:02 DEBUG [app] heartbeat",
    ]
    assert parse_text_lines("svc", lines, now=_now()) == {}


def test_parse_text_lines_catches_asyncio_unretrieved_task():
    lines = [
        "Task exception was never retrieved",
        "future: <Task finished coro=<...> exception=RuntimeError('boom')>",
    ]
    findings = parse_text_lines("svc", lines, now=_now())
    assert findings


def test_parse_jsonl_entries_uses_exc_info_for_signature():
    entries = [
        {
            "ts": "2026-04-26T12:00:00+00:00",
            "level": "ERROR",
            "logger": "app.x",
            "message": "request failed",
            "exc_info": (
                "Traceback (most recent call last):\n"
                '  File "/app/x.py", line 42, in f\n'
                "    do_thing()\n"
                "ValueError: oops"
            ),
        },
    ]
    findings = parse_jsonl_entries("agent-server", entries)
    assert len(findings) == 1
    f = next(iter(findings.values()))
    assert "ValueError" in f.title
    assert f.severity == "error"


def test_parse_jsonl_entries_skips_info_without_exc_info():
    entries = [
        {"ts": "2026-04-26T12:00:00+00:00", "level": "INFO", "logger": "app", "message": "hi"},
    ]
    assert parse_jsonl_entries("agent-server", entries) == {}


def test_dedupe_key_uses_shared_error_signature():
    """Cross-system contract: log-derived dedupe keys must use the same
    `_error_signature` helper as the 60s structured-attention detector,
    so the daily summary's matching logic finds attention items keyed on
    the equivalent text.
    """
    line = "ERROR ValueError: timeout after 30s"
    expected = derive_dedupe_key("log", "agent-server", _error_signature(line))
    findings = parse_text_lines("agent-server", [line], now=_now())
    assert expected in findings, sorted(findings)


def test_merge_findings_aggregates_counts():
    first = parse_text_lines("agent-server", ["ERROR boom"], now=_now())
    second = parse_text_lines("agent-server", ["ERROR boom", "ERROR boom"], now=_now())
    merged = merge_findings(first, second)
    assert len(merged) == 1
    assert merged[0].count == 3
