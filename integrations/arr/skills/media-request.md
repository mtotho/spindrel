---
id: integrations/arr/media-request
title: Media Request Procedure
description: Step-by-step flow for "can you get X on Jellyfin?" — checks availability, confirms match, creates Jellyseerr request
tags: [media, request, arr]
---

# Media Request Procedure

Follow this procedure when a user asks to get a movie or TV show on Jellyfin. Call tools inline and share findings as you go.

## Title Matching (important)

Titles differ across platforms — "Paradise" might be "Paradise (2025)" in Sonarr, just "Paradise" in Jellyfin. Always:
- Search with the shortest unambiguous form first
- If multiple results, pick the most likely match based on context
- Try without year, then with year if ambiguous

## Step 1: Check Jellyfin

Search Jellyfin first — it may already be available.

```
jellyfin_library(action="search", search="TITLE")
```

- Try a few title variations if no results.
- **If FOUND**: Tell the user it's already available — include quality and full title. You're done.
- **If NOT FOUND**: Continue to Step 2.

## Step 2: Check Jellyseerr

Search TMDB via Jellyseerr to check if already requested:

```
jellyseerr_search(query="TITLE")
```

Check the `status` field on each matching result:
- `available` — already on the server (may be a Jellyfin indexing issue if Step 1 missed it)
- `pending` or `processing` — already requested, in progress. Tell the user and you're done.
- No status — not yet requested. Continue to Step 3.

## Step 3: Confirm and Request

From the Jellyseerr search results, pick the best TMDB match:
- Match by title + year (prefer exact matches)
- If ambiguous (multiple similar titles), ask the user which one
- If TV show: ask which seasons (or request all)

Create the request:
- **Movie**: `jellyseerr_manage(action="request", media_id=TMDB_ID, media_type="movie")`
- **TV show**: `jellyseerr_manage(action="request", media_id=TMDB_ID, media_type="tv")`
  - With specific seasons: add `seasons=[1,2,3]`
  - No seasons specified: request all (omit the seasons param)

Quality note: Requests go through quality profiles configured in Sonarr/Radarr. Default target is 1080p.

## Step 4: Report

Write a conversational summary:
- What you found (already available, already requested, or newly requested)
- If newly requested: title, year, type, and next steps ("Sonarr/Radarr will search for it automatically, should start downloading soon")
- If already available: where to find it
- If already requested: current status and who requested it

Example tone: "Done — requested The Bear (2022) on Jellyseerr. All 3 seasons. Sonarr will pick it up and start searching for releases. Should be on Jellyfin within a few hours depending on availability."
