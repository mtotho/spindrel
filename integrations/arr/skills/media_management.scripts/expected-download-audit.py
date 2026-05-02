import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spindrel import tools


TRACKED_SHOWS = "data/tracked-shows.json"
TRACKED_MOVIES = "data/tracked-movies.json"


def load_jsonish(value):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        start = min([idx for idx in (text.find("{"), text.find("[")) if idx >= 0], default=-1)
        if start < 0:
            return {}
        try:
            parsed = json.loads(text[start:])
        except Exception:
            return {}
    if isinstance(parsed, dict):
        envelope = parsed.get("_envelope")
        if isinstance(envelope, dict) and "body" in envelope:
            return load_jsonish(envelope.get("body"))
        if "body" in parsed and len(parsed) <= 4:
            return load_jsonish(parsed.get("body"))
        if "content" in parsed and len(parsed) <= 4:
            return load_jsonish(parsed.get("content"))
    return parsed


def read_json(path):
    try:
        bot_root = Path.cwd().parents[1]
        local_path = bot_root / path
        if local_path.is_file():
            return load_jsonish(local_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        return load_jsonish(tools.file(operation="read", path=path, limit=200000))
    except Exception as exc:
        return {"_read_error": str(exc)}


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def entries(data):
    if isinstance(data, list):
        iterable = enumerate(data)
    elif isinstance(data, dict):
        for key in ("shows", "movies", "items", "entries", "tracked", "registry"):
            nested = data.get(key)
            if isinstance(nested, (dict, list)):
                return entries(nested)
        iterable = data.items()
    else:
        return []

    out = []
    for key, value in iterable:
        key_text = str(key)
        if key_text.startswith("_") or key_text in {"schema_version", "last_updated", "notes", "metadata"}:
            continue
        if not isinstance(value, dict):
            continue
        title = (
            value.get("title")
            or value.get("name")
            or value.get("series_title")
            or value.get("seriesTitle")
            or value.get("movieTitle")
            or key_text
        )
        tracking = value.get("tracking") if isinstance(value.get("tracking"), dict) else {}
        state = str(
            tracking.get("status")
            or value.get("state")
            or value.get("status")
            or value.get("lifecycle")
            or "active"
        ).lower()
        if state in {"dropped", "ignored", "inactive", "resolved", "complete"}:
            continue
        out.append({"key": key_text, "title": title, "norm": normalize(title), "raw": value})
    return out


def matches_tracked(title, tracked):
    norm = normalize(title)
    if not norm:
        return None
    for item in tracked:
        target = item["norm"]
        if target and (target in norm or norm in target):
            return item
    return None


def list_from(container, *keys):
    current = container
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def compact_item(item):
    return {k: v for k, v in item.items() if v not in (None, "", [], {})}


shows_data = read_json(TRACKED_SHOWS)
movies_data = read_json(TRACKED_MOVIES)
tracked_shows = entries(shows_data)
tracked_movies = entries(movies_data)
tracked_registry_empty = not tracked_shows and not tracked_movies

snapshot = load_jsonish(tools.arr_heartbeat_snapshot(
    include_services=["sonarr", "radarr"],
    days_ahead=28,
    wanted_limit=100,
    queue_limit=100,
))

now = datetime.now(timezone.utc).date()
items = []
counts = {
    "tracked_shows": len(tracked_shows),
    "tracked_movies": len(tracked_movies),
    "downloaded": 0,
    "queued": 0,
    "missing_now": 0,
    "missing_upcoming": 0,
    "untracked_wanted": 0,
    "registry_empty": 1 if tracked_registry_empty else 0,
}

for episode in list_from(snapshot, "sonarr", "calendar", "episodes"):
    show = matches_tracked(
        episode.get("series") or episode.get("series_title") or episode.get("seriesTitle"),
        tracked_shows,
    )
    if not show:
        continue
    has_file = bool(episode.get("has_file") or episode.get("hasFile"))
    air_raw = episode.get("air_date") or episode.get("airDate") or episode.get("airDateUtc")
    air_date = None
    if air_raw:
        try:
            air_date = datetime.fromisoformat(str(air_raw).replace("Z", "+00:00")).date()
        except Exception:
            pass
    if has_file:
        state = "downloaded"
        counts["downloaded"] += 1
    elif air_date and air_date <= now:
        state = "missing_now"
        counts["missing_now"] += 1
    else:
        state = "missing_upcoming"
        counts["missing_upcoming"] += 1
    items.append(compact_item({
        "kind": "episode",
        "state": state,
        "tracked": show["title"],
        "title": episode.get("title"),
        "season": episode.get("season") or episode.get("seasonNumber"),
        "episode": episode.get("episode") or episode.get("episodeNumber"),
        "air_date": str(air_date) if air_date else air_raw,
    }))

for episode in list_from(snapshot, "sonarr", "wanted", "episodes") + list_from(snapshot, "sonarr", "wanted", "items"):
    show = matches_tracked(
        episode.get("series") or episode.get("series_title") or episode.get("seriesTitle"),
        tracked_shows,
    )
    if show:
        counts["missing_now"] += 1
        items.append(compact_item({
            "kind": "episode",
            "state": "wanted_missing",
            "tracked": show["title"],
            "title": episode.get("title"),
            "season": episode.get("season") or episode.get("seasonNumber"),
            "episode": episode.get("episode") or episode.get("episodeNumber"),
        }))
    else:
        counts["untracked_wanted"] += 1

for movie in list_from(snapshot, "radarr", "wanted", "movies") + list_from(snapshot, "radarr", "wanted", "items"):
    tracked = matches_tracked(movie.get("title") or movie.get("movieTitle"), tracked_movies)
    if tracked:
        counts["missing_now"] += 1
        items.append(compact_item({
            "kind": "movie",
            "state": "wanted_missing",
            "tracked": tracked["title"],
            "title": movie.get("title") or movie.get("movieTitle"),
            "year": movie.get("year"),
        }))
    else:
        counts["untracked_wanted"] += 1

for service in ("sonarr", "radarr"):
    for queued in list_from(snapshot, service, "queue", "items"):
        title = queued.get("title") or queued.get("series") or queued.get("movie")
        tracked = matches_tracked(title, tracked_shows if service == "sonarr" else tracked_movies)
        if not tracked:
            continue
        counts["queued"] += 1
        items.append(compact_item({
            "kind": "queue",
            "state": "queued",
            "service": service,
            "tracked": tracked["title"],
            "title": title,
            "status": queued.get("status"),
            "tracked_status": queued.get("tracked_status") or queued.get("trackedDownloadStatus"),
        }))

problem_count = counts["missing_now"] + counts["registry_empty"]
status = "needs_attention" if problem_count else "ok"
if tracked_registry_empty:
    summary = (
        "Tracked ARR registry loaded empty; check data/tracked-shows.json and "
        "data/tracked-movies.json shape before trusting expected-download counts."
    )
else:
    summary = (
        f"{counts['tracked_shows']} tracked shows, {counts['tracked_movies']} tracked movies; "
        f"{counts['missing_now']} due/wanted missing, {counts['missing_upcoming']} upcoming missing, "
        f"{counts['queued']} queued, {counts['downloaded']} calendar entries already downloaded; "
        f"{counts['untracked_wanted']} untracked Sonarr/Radarr wanted items ignored."
    )

output = {
    "status": status,
    "summary": summary,
    "counts": counts,
    "items": items[:40],
    "truncated_items": max(0, len(items) - 40),
    "read_errors": {
        TRACKED_SHOWS: shows_data.get("_read_error") if isinstance(shows_data, dict) else None,
        TRACKED_MOVIES: movies_data.get("_read_error") if isinstance(movies_data, dict) else None,
    },
    "services": snapshot.get("services", {}) if isinstance(snapshot, dict) else {},
}

print(json.dumps(output, ensure_ascii=False, sort_keys=True))
