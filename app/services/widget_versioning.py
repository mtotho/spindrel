from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.context import current_channel_id, current_session_id
from app.services.widget_paths import scope_root

logger = logging.getLogger(__name__)

_GIT_USER_NAME = "Widget Bot"
_GIT_USER_EMAIL = "widget-bot@local"


@dataclass(frozen=True)
class WidgetBundleRef:
    scope: str
    name: str
    library_root: str

    @property
    def widget_ref(self) -> str:
        return f"{self.scope}/{self.name}"

    @property
    def bundle_relpath(self) -> str:
        return self.name

    @property
    def bundle_path(self) -> str:
        return os.path.join(self.library_root, self.name)


def _git(repo_root: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_root, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _ensure_repo(library_root: str) -> None:
    Path(library_root).mkdir(parents=True, exist_ok=True)
    if not os.path.isdir(os.path.join(library_root, ".git")):
        _git(library_root, "init")
    _git(library_root, "config", "user.name", _GIT_USER_NAME)
    _git(library_root, "config", "user.email", _GIT_USER_EMAIL)


def classify_widget_bundle(
    path: str | None,
    *,
    ws_root: str | None,
    shared_root: str | None,
) -> WidgetBundleRef | None:
    if not path:
        return None
    real = os.path.realpath(path)
    candidates = (
        ("bot", scope_root("bot", ws_root=ws_root, shared_root=shared_root)),
        ("workspace", scope_root("workspace", ws_root=ws_root, shared_root=shared_root)),
    )
    for scope, root in candidates:
        if not root:
            continue
        root_real = os.path.realpath(root)
        try:
            rel = os.path.relpath(real, root_real)
        except ValueError:
            continue
        if rel == ".":
            return None
        if rel.startswith(".."):
            continue
        bundle = rel.split(os.sep, 1)[0].strip()
        if bundle in {"", ".git"}:
            return None
        return WidgetBundleRef(scope=scope, name=bundle, library_root=root_real)
    return None


def _diffstat_for_head(repo_root: str, revision: str) -> dict[str, int]:
    proc = _git(repo_root, "show", "--stat", "--format=", revision)
    files = 0
    additions = 0
    deletions = 0
    for line in proc.stdout.splitlines():
        text = line.strip()
        if not text or "|" not in text:
            continue
        files += 1
        additions += text.count("+")
        deletions += text.count("-")
    return {"files": files, "additions": additions, "deletions": deletions}


def get_widget_head_revision(
    widget_ref: str,
    *,
    ws_root: str | None,
    shared_root: str | None,
) -> str | None:
    bundle = resolve_widget_ref(widget_ref, ws_root=ws_root, shared_root=shared_root)
    if bundle is None or not os.path.isdir(os.path.join(bundle.library_root, ".git")):
        return None
    proc = _git(bundle.library_root, "rev-parse", "HEAD", check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def resolve_widget_ref(
    widget_ref: str,
    *,
    ws_root: str | None,
    shared_root: str | None,
) -> WidgetBundleRef | None:
    text = widget_ref.strip().removeprefix("widget://").strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None
    scope, name = parts[0], parts[1]
    if scope not in {"bot", "workspace"}:
        return None
    root = scope_root(scope, ws_root=ws_root, shared_root=shared_root)
    if not root:
        return None
    return WidgetBundleRef(scope=scope, name=name, library_root=os.path.realpath(root))


def _commit_bundle_change(
    bundle: WidgetBundleRef,
    *,
    operation: str,
    bot_id: str | None,
    session_id: str | None,
    channel_id: str | None,
    target_revision: str | None = None,
) -> dict[str, Any] | None:
    _ensure_repo(bundle.library_root)
    _git(bundle.library_root, "add", "-A", "--", bundle.bundle_relpath, check=False)
    if _git(bundle.library_root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    message_lines = [
        f"widget {bundle.widget_ref}: {operation}",
        "",
        f"Widget-Ref: {bundle.widget_ref}",
        f"Operation: {operation}",
    ]
    if bot_id:
        message_lines.append(f"Bot-Id: {bot_id}")
    if session_id:
        message_lines.append(f"Session-Id: {session_id}")
    if channel_id:
        message_lines.append(f"Channel-Id: {channel_id}")
    if target_revision:
        message_lines.append(f"Target-Revision: {target_revision}")
    _git(bundle.library_root, "commit", "-m", "\n".join(message_lines))
    revision = _git(bundle.library_root, "rev-parse", "HEAD").stdout.strip()
    return {
        "widget_ref": bundle.widget_ref,
        "scope": bundle.scope,
        "name": bundle.name,
        "revision": revision,
        "operation": operation,
        "diffstat": _diffstat_for_head(bundle.library_root, revision),
    }


async def append_widget_artifacts(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    session_id = current_session_id.get()
    if session_id is None:
        return
    try:
        from app.db.engine import async_session
        from app.db.models import Session
        from app.services.session_plan_mode import (
            PLAN_MODE_BLOCKED,
            PLAN_MODE_DONE,
            PLAN_MODE_EXECUTING,
            PLAN_MODE_PLANNING,
            append_plan_artifact,
            get_session_plan_mode,
        )

        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session is None:
                return
            if get_session_plan_mode(session) not in {
                PLAN_MODE_PLANNING,
                PLAN_MODE_EXECUTING,
                PLAN_MODE_BLOCKED,
                PLAN_MODE_DONE,
            }:
                return
            for record in records:
                append_plan_artifact(
                    session,
                    kind="widget_revision",
                    label=f"widget {record['widget_ref']} @ {record['revision'][:7]}",
                    ref=record["widget_ref"],
                    metadata={
                        "revision": record["revision"],
                        "operation": record["operation"],
                        "diffstat": record.get("diffstat") or {},
                    },
                )
            await db.commit()
    except Exception:
        logger.exception("Failed appending widget plan artifacts")


async def record_widget_mutation(
    *,
    operation: str,
    resolved_path: str | None,
    resolved_destination: str | None,
    ws_root: str | None,
    shared_root: str | None,
    bot_id: str | None,
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    bundles: list[WidgetBundleRef] = []
    for path in (resolved_path, resolved_destination):
        bundle = classify_widget_bundle(path, ws_root=ws_root, shared_root=shared_root)
        if bundle is None:
            continue
        key = (bundle.scope, bundle.name)
        if key in seen:
            continue
        seen.add(key)
        bundles.append(bundle)
    session_id = str(current_session_id.get()) if current_session_id.get() else None
    channel_id = str(current_channel_id.get()) if current_channel_id.get() else None
    records = [
        record
        for bundle in bundles
        if (record := _commit_bundle_change(
            bundle,
            operation=operation,
            bot_id=bot_id,
            session_id=session_id,
            channel_id=channel_id,
        )) is not None
    ]
    await append_widget_artifacts(records)
    return records


def widget_version_history(
    widget_ref: str,
    *,
    ws_root: str | None,
    shared_root: str | None,
    limit: int = 10,
    include_diffstat: bool = True,
) -> list[dict[str, Any]]:
    bundle = resolve_widget_ref(widget_ref, ws_root=ws_root, shared_root=shared_root)
    if bundle is None or not os.path.isdir(os.path.join(bundle.library_root, ".git")):
        return []
    proc = _git(
        bundle.library_root,
        "log",
        f"-n{max(1, min(limit, 50))}",
        "--format=%H%x1f%cI%x1f%s",
        "--",
        bundle.bundle_relpath,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    out: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        revision, committed_at, subject = line.split("\x1f", 2)
        item = {
            "revision": revision,
            "committed_at": committed_at,
            "summary": subject,
            "widget_ref": bundle.widget_ref,
        }
        if include_diffstat:
            item["diffstat"] = _diffstat_for_head(bundle.library_root, revision)
        out.append(item)
    return out


async def rollback_widget_to_revision(
    widget_ref: str,
    revision: str,
    *,
    ws_root: str | None,
    shared_root: str | None,
    bot_id: str | None,
) -> dict[str, Any]:
    bundle = resolve_widget_ref(widget_ref, ws_root=ws_root, shared_root=shared_root)
    if bundle is None:
        raise ValueError(f"Unknown widget ref: {widget_ref}")
    if not os.path.isdir(os.path.join(bundle.library_root, ".git")):
        raise ValueError(f"Widget has no version history: {widget_ref}")
    if _git(bundle.library_root, "rev-parse", "--verify", revision, check=False).returncode != 0:
        raise ValueError(f"Unknown revision: {revision}")

    exists_at_revision = _git(
        bundle.library_root,
        "ls-tree",
        "--name-only",
        revision,
        "--",
        bundle.bundle_relpath,
        check=False,
    )
    if exists_at_revision.stdout.strip():
        _git(bundle.library_root, "checkout", revision, "--", bundle.bundle_relpath)
    else:
        shutil.rmtree(bundle.bundle_path, ignore_errors=True)
    record = _commit_bundle_change(
        bundle,
        operation="rollback",
        bot_id=bot_id,
        session_id=str(current_session_id.get()) if current_session_id.get() else None,
        channel_id=str(current_channel_id.get()) if current_channel_id.get() else None,
        target_revision=revision,
    )
    if record is None:
        head = get_widget_head_revision(widget_ref, ws_root=ws_root, shared_root=shared_root)
        record = {
            "widget_ref": bundle.widget_ref,
            "scope": bundle.scope,
            "name": bundle.name,
            "revision": head,
            "operation": "rollback",
            "diffstat": {"files": 0, "additions": 0, "deletions": 0},
        }
    await append_widget_artifacts([record])
    return record
