---
name: Bennie Loggins Health
description: Pet health tracking tools for Bennie — poop logs, puke logs, eating issues, eating/drinking, vet visits
---
# SKILL: Bennie Loggins Pet Health Tracker

## Overview
Track and query Bennie's health data: poop logs, puke logs, eating issues, eating/drinking events, and vet visits. Use the summary tool to orient first, then drill into specific log types or create new entries.

## Read Tools (Query Data)

### Summary
- `bennie_loggins_health_summary` — snapshot of recent health data across all log types, active medicines, food schedule. **Call this first** to orient before drilling into specifics. Optional `recent_count` to control how many entries per type.

### Poop Logs
- `bennie_loggins_health_poop_logs` — history with moisture, form (Bristol 1-7), size, hasDrips, hasMucus, hasBlood, strainLevel, notes, healthScore. Filter by `last_days` or `start_date`/`end_date`.

### Puke Logs
- `bennie_loggins_health_puke_logs` — history with pukeType, size, notes, healthScore. Filter by `last_days` or `start_date`/`end_date`.

### Vet Visits
- `bennie_loggins_health_vet_visits` — history with date, clinic, vet, weight, notable, procedures, treatments, nextAppointment, cost, notes. Filter by `last_days` or `start_date`/`end_date`.

## Write Tools (Log New Entries)

### Log Poop
- `bennie_loggins_log_poop` — required: `moisture` (0-10), `form` (0-10, Bristol Stool Chart), `size` (0-10). Optional: `color`, `location`, `notes`, `hasDrips`, `hasMucus`, `hasBlood`, `strainLevel` (normal/mild/moderate/severe), `createdAt`.

### Log Puke
- `bennie_loggins_log_puke` — required: `pukeType` (e.g. "liquid/mucus", "chunks", "other"), `size` (0-10). Optional: `notes`, `createdAt`.

### Log Eating Issue
- `bennie_loggins_log_eating_issue` — required: `eatingIssueType` (feeding-refused, partial-eating, slow-eating, picky). Optional: `notes`, `createdAt`.

### Log Eating/Drinking
- `bennie_loggins_log_eating_drinking` — required: `type` ("eating" or "drinking"), `amount` (0-10). Optional: `notes`, `createdAt`.

## Key Workflows

### Quick health check
1. `bennie_loggins_health_summary` — get the full picture
2. Look at healthScores and recent trends

### Log a bathroom event
1. Ask for details: what did it look like? (form, moisture, size)
2. `bennie_loggins_log_poop(moisture=5, form=4, size=6)` — log it
3. Add optional details if mentioned: color, location, blood/mucus/drips, strain level

### Track eating behavior
1. `bennie_loggins_log_eating_drinking(type="eating", amount=7)` — normal meal
2. `bennie_loggins_log_eating_issue(eatingIssueType="partial-eating", notes="Only ate half")` — if there's a problem

### Investigate a health concern
1. `bennie_loggins_health_summary` — overview
2. `bennie_loggins_health_poop_logs(last_days=7)` — recent poop trends
3. `bennie_loggins_health_puke_logs(last_days=7)` — recent puke events
4. `bennie_loggins_health_vet_visits(last_days=90)` — recent vet context

## Common Patterns
- **All 0-10 scales**: 0 = none/minimal, 10 = maximum
- **Bristol Stool Chart (form)**: 1-2 = constipated, 3-4 = ideal, 5-7 = loose/liquid
- **healthScore** in responses: server-calculated health indicator
- **User field**: optional on all write tools; fuzzy-matches name/email, falls back to first user
- **createdAt**: ISO timestamp override on all write tools for backdating entries
- **Unconfigured**: tools return clear errors if BENNIE_LOGGINS_BASE_URL not set
