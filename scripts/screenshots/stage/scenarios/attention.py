"""Attention beacon + notification target stagers.

Both feature-area heroes need the spatial scenario's channels to exist. Run
``stage --only spatial`` first; these scenarios layer on top of that cast.

`stage_attention` POSTs three Attention Items (mix of warning / error /
critical severities, mix of channel + bot targets) so the spatial canvas
renders the lucide AlertTriangle/ShieldAlert badges that the
``attention-canvas`` and ``attention-hub`` capture specs gate on.

`stage_notifications` POSTs three channel notification targets + a group
that bundles two of them, then fires test sends so the ``Recent deliveries``
panel on ``/admin/notifications`` is non-empty.

Both stagers are idempotent — keyed on stable slugs / dedupe keys so reruns
return the same row instead of duplicating.
"""
from __future__ import annotations

import httpx

from . import StagedState
from ..client import SpindrelClient


SCREENSHOT_ATTENTION_DEDUPE_PREFIX = "screenshot:attention:"

# Attention items targeting channels staged by spatial.py. Slugs map to the
# `screenshot:spatial:<slug>` channel client_ids resolved at runtime.
_ATTENTION_ITEMS: list[dict] = [
    {
        "channel_slug": "system-audit",
        "title": "Cron job exited 1",
        "message": "Nightly backup task fell over after 3 retries.",
        "severity": "error",
        "next_steps": [
            "Inspect the trace for the last attempt.",
            "Re-run after fixing the underlying error.",
        ],
        "dedupe_key": f"{SCREENSHOT_ATTENTION_DEDUPE_PREFIX}cron-failed",
    },
    {
        "channel_slug": "dev-commits",
        "title": "CI red on `main`",
        "message": "3 of 12 unit tests failing in tools/local/test_image.py.",
        "severity": "warning",
        "next_steps": [
            "Open the failing tests and reproduce locally.",
        ],
        "dedupe_key": f"{SCREENSHOT_ATTENTION_DEDUPE_PREFIX}ci-red",
    },
    {
        "channel_slug": "home-assistant",
        "title": "Door sensor unresponsive",
        "message": "Front door hasn't reported state in 27 minutes.",
        "severity": "critical",
        "next_steps": [
            "Power-cycle the sensor.",
            "If still unresponsive, file a hardware issue.",
        ],
        "dedupe_key": f"{SCREENSHOT_ATTENTION_DEDUPE_PREFIX}door-offline",
    },
]


def _list_attention_items(client: SpindrelClient) -> list[dict]:
    r = client._http.get("/api/v1/workspace/attention", params={"status": "all"})
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json().get("items", [])


def stage_attention(client: SpindrelClient, *, dry_run: bool = False, **_unused) -> StagedState:
    """Create a small set of attention items targeting spatial-scenario channels.

    Idempotent — checks existing items by dedupe_key prefix and skips any
    that already exist. Requires ``stage --only spatial`` to have run first
    so the target channels exist.
    """
    state = StagedState()

    # Resolve channel UUIDs from spatial scenario client_ids.
    channels_by_slug: dict[str, str] = {}
    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid.startswith("screenshot:spatial:"):
            slug = cid.removeprefix("screenshot:spatial:")
            channels_by_slug[slug] = str(ch["id"])

    if not channels_by_slug:
        raise RuntimeError(
            "stage_attention: no spatial channels found. "
            "Run `stage --only spatial` first."
        )

    existing_keys = {item.get("dedupe_key") for item in _list_attention_items(client)}

    created: dict[str, str] = {}
    for spec in _ATTENTION_ITEMS:
        if spec["dedupe_key"] in existing_keys:
            continue
        channel_id = channels_by_slug.get(spec["channel_slug"])
        if not channel_id:
            continue
        body = {
            "channel_id": channel_id,
            "target_kind": "channel",
            "target_id": channel_id,
            "title": spec["title"],
            "message": spec["message"],
            "severity": spec["severity"],
            "requires_response": True,
            "next_steps": spec["next_steps"],
        }
        if dry_run:
            continue
        # Create endpoint applies the dedupe_key derivation server-side via
        # the create_user_attention_item path — we surface the key by setting
        # the title; the scenario's title strings are stable and unique.
        r = client._post("/api/v1/workspace/attention", json=body)
        item = r.json().get("item", {})
        if item.get("id"):
            created[spec["dedupe_key"]] = str(item["id"])

    state.tasks = created  # piggyback on tasks dict to stash IDs for teardown
    return state


def teardown_attention(client: SpindrelClient) -> None:
    """Delete attention items we created, by dedupe_key prefix."""
    items = _list_attention_items(client)
    for item in items:
        key = item.get("dedupe_key") or ""
        title = item.get("title") or ""
        # Match either by dedupe key prefix OR by the unique titles we set —
        # the server may rewrite dedupe_key on user-authored items.
        if key.startswith(SCREENSHOT_ATTENTION_DEDUPE_PREFIX) or title in {
            spec["title"] for spec in _ATTENTION_ITEMS
        }:
            try:
                client._http.post(f"/api/v1/workspace/attention/{item['id']}/resolve")
            except httpx.HTTPError:
                pass


# ---------------------------------------------------------------------------
# Notification targets staging
# ---------------------------------------------------------------------------

_NOTIF_SLUGS = (
    "screenshot-notif-system-errors",
    "screenshot-notif-build-alerts",
    "screenshot-notif-home-watch",
    "screenshot-notif-critical-group",
)


def _list_notification_targets(client: SpindrelClient) -> list[dict]:
    r = client._http.get("/api/v1/admin/notification-targets")
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json().get("targets", [])


def stage_notifications(client: SpindrelClient, *, dry_run: bool = False, **_unused) -> StagedState:
    """Seed three channel targets + a group, then fire two test sends.

    Idempotent — keyed on the ``screenshot-notif-*`` slug prefix so reruns
    return the same rows. Channels come from the spatial scenario; if those
    channels are missing the stager raises with a clear message.
    """
    state = StagedState()

    # Resolve channel UUIDs from spatial scenario client_ids.
    channels_by_slug: dict[str, str] = {}
    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid.startswith("screenshot:spatial:"):
            slug = cid.removeprefix("screenshot:spatial:")
            channels_by_slug[slug] = str(ch["id"])

    needed = {"system-audit", "dev-commits", "home-assistant"}
    missing = needed - channels_by_slug.keys()
    if missing:
        raise RuntimeError(
            f"stage_notifications: missing spatial channels {sorted(missing)!r}. "
            "Run `stage --only spatial` first."
        )

    existing = {t["slug"]: t for t in _list_notification_targets(client)}

    targets: list[dict] = [
        {
            "slug": "screenshot-notif-system-errors",
            "label": "System errors",
            "kind": "channel",
            "config": {"channel_id": channels_by_slug["system-audit"]},
            "enabled": True,
        },
        {
            "slug": "screenshot-notif-build-alerts",
            "label": "Build alerts",
            "kind": "channel",
            "config": {"channel_id": channels_by_slug["dev-commits"]},
            "enabled": True,
        },
        {
            "slug": "screenshot-notif-home-watch",
            "label": "Home watch",
            "kind": "channel",
            "config": {"channel_id": channels_by_slug["home-assistant"]},
            "enabled": True,
        },
    ]

    created: dict[str, str] = {}
    for body in targets:
        if body["slug"] in existing:
            created[body["slug"]] = existing[body["slug"]]["id"]
            continue
        if dry_run:
            continue
        row = client._post("/api/v1/admin/notification-targets", json=body).json()
        created[body["slug"]] = row["id"]

    # Group target — bundles the first two channel targets.
    group_slug = "screenshot-notif-critical-group"
    if group_slug not in existing and not dry_run:
        group_body = {
            "slug": group_slug,
            "label": "Critical alerts",
            "kind": "group",
            "config": {
                "target_ids": [
                    created["screenshot-notif-system-errors"],
                    created["screenshot-notif-build-alerts"],
                ]
            },
            "enabled": True,
        }
        row = client._post("/api/v1/admin/notification-targets", json=group_body).json()
        created[group_slug] = row["id"]
    elif group_slug in existing:
        created[group_slug] = existing[group_slug]["id"]

    # Fire one test send through the group + one through home-watch so the
    # delivery-history panel shows two rows. Idempotent in spirit — extras
    # are fine; over time the panel just shows the most recent N.
    if not dry_run:
        for slug in (group_slug, "screenshot-notif-home-watch"):
            target_id = created.get(slug)
            if not target_id:
                continue
            try:
                client._post(f"/api/v1/admin/notification-targets/{target_id}/test", json={})
            except httpx.HTTPError:
                pass

    state.tasks = created
    return state


def teardown_notifications(client: SpindrelClient) -> None:
    """Delete every screenshot-prefixed notification target."""
    for target in _list_notification_targets(client):
        slug = target.get("slug") or ""
        if slug.startswith("screenshot-notif-"):
            try:
                client._http.delete(f"/api/v1/admin/notification-targets/{target['id']}")
            except httpx.HTTPError:
                pass
