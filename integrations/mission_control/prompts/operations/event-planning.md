---
name: "Event Planning"
description: "Event planning and coordination — venue, speakers, schedule, budget, attendees, and logistics tracking."
category: workspace_schema
compatible_integrations:
  - mission_control
mc_min_version: "2.0"
tags:
  - events
  - planning
  - coordination
  - logistics
  - mission-control
group: "Operations"
recommended_heartbeat:
  prompt: "Review the event planning task board. Check for overdue prep tasks and upcoming deadlines. Update status.md with current event health, countdown, and budget status. Flag any logistics gaps or vendor confirmations still pending. Log activity to timeline."
  interval: "weekly"
  quiet_start: "20:00"
  quiet_end: "08:00"
---

## Workspace File Organization — Event Planning

Organize channel workspace files to plan and coordinate events. This schema is Mission Control compatible — task tracking, status reporting, and activity logging follow the MC protocol.

Root files are living documents injected into every context — keep them concise.

### Root Files (auto-injected)

- **tasks.md** — Planning kanban (Mission Control compatible)
  - Prep tasks flowing through planning stages
  - Each card: owner, category, deadline, dependencies
  - Use `create_task_card` and `move_task_card` tools

- **status.md** — Event health and countdown (Mission Control compatible)
  - Phase/health/owner header block
  - Event overview: date, venue, expected attendance
  - Budget tracking: allocated vs spent
  - Countdown: days until event, critical path items

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: task completions, booking confirmations, budget changes
  - Manual entries: vendor calls, site visits, sponsor commitments
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

- **notes.md** — Meeting notes, sponsor communications, and scratch space

### Additional Files (create as needed)

These are NOT auto-injected — create them when the event planning matures. Reference via `search_channel_workspace`.

- **schedule.md** — Event day schedule and run-of-show (setup through teardown, speaker slots, staff assignments)
- **venue.md** — Venue details and logistics (address, rooms, AV, catering, vendor contacts)
- **attendees.md** — Guest list and RSVP tracking (name, company, RSVP status, dietary needs, VIPs)
- **budget.md** — Budget breakdown and expense tracking (category budgets, expense log, running totals)

Create files as needed — start with tasks.md and status.md, expand as planning progresses.

### Archive (`archive/`)

Past event materials, vendor evaluations, post-event surveys. Searchable via `search_channel_archive`.

---

## File Formats

### tasks.md — Planning Kanban (Mission Control Format)

Planning stages as kanban columns.

```markdown
## Backlog

### Book photographer for event day
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: vendor, photography
- **assigned**: Lisa
- **due**: 2026-04-20
- budget: $1,500 allocated
- notes: Need headshots + candid coverage, 4 hours

### Order branded name badges
- **id**: mc-d4e5f6
- **priority**: low
- **tags**: materials, branding
- **assigned**: Mike
- **due**: 2026-04-25
- depends: mc-x1y2z3 (finalize attendee list)
- budget: $200 estimated

## In Progress

### Confirm catering menu and headcount
- **id**: mc-g7h8i9
- **priority**: high
- **tags**: catering, vendor
- **assigned**: Sarah
- **started**: 2026-03-25
- **due**: 2026-04-10
- vendor: Good Eats Catering — Maria (555-234-5678)
- dietary: 3 vegetarian, 1 vegan, 2 gluten-free (from attendees.md)
- budget: $4,500 allocated

### Finalize speaker presentations and AV requirements
- **id**: mc-j0k1l2
- **priority**: high
- **tags**: speakers, av, content
- **assigned**: Sarah
- **started**: 2026-03-28
- **due**: 2026-04-15
- status: 3/5 speakers confirmed slides, waiting on 2

## Review

### Draft day-of schedule and run sheet
- **id**: mc-m3n4o5
- **priority**: high
- **tags**: schedule, logistics
- **assigned**: Lisa
- **started**: 2026-03-20
- status: V2 draft ready for team review

## Done

### Book venue — Grand Conference Center
- **id**: mc-p6q7r8
- **priority**: critical
- **completed**: 2026-03-15
- notes: Main hall + 2 breakout rooms, deposit paid $2,000

### Send save-the-date to attendee list
- **id**: mc-s9t0u1
- **priority**: high
- **completed**: 2026-03-18
- notes: 85 emails sent, 47 RSVPs so far
```

**Planning stages:**
- **Backlog** — Identified but not started
- **In Progress** — Actively being worked on
- **Review** — Needs approval or sign-off
- **Done** — Completed (archive after event)

Use `create_task_card` and `move_task_card` tools — tasks.md is read-only from the database.

### status.md — Event Health (Mission Control Format)

```markdown
- **phase**: Active Planning — 32 days to event
- **health**: yellow
- **updated**: 2026-03-28
- **owner**: Event Committee

## Event Overview
- **event**: Annual Tech Summit 2026
- **date**: April 30, 2026 (Wednesday)
- **time**: 9:00 AM – 6:00 PM
- **venue**: Grand Conference Center — Main Hall + Breakout A/B
- **expected attendance**: 85 (47 confirmed, 38 pending)

## Budget
- **Allocated**: $19,000 | **Committed**: $9,150 | **Paid**: $3,050 | **Remaining**: $9,850
- See `budget.md` for full category breakdown and expense log

## Critical Path (Next 2 Weeks)
1. **April 5** — Final headcount to caterer (mc-g7h8i9)
2. **April 10** — Catering menu sign-off
3. **April 15** — All speaker slides due (mc-j0k1l2)
4. **April 20** — Book photographer (mc-a1b2c3)

## Blockers
- 2 speakers haven't submitted slides — need follow-up
- Photographer not yet booked — limited availability for April 30

## Recent Milestones
- 2026-03-28: 47 RSVPs received (55% response rate)
- 2026-03-18: Save-the-date sent to 85 invitees
- 2026-03-15: Venue booked, deposit paid
```

Health values: `green` (on track, critical path clear), `yellow` (deadlines approaching, pending confirmations), `red` (critical vendor unconfirmed, budget overrun, or major logistics gap).

### schedule.md — Day-of Schedule

```markdown
## Event Day — April 30, 2026

### Setup (7:00 – 9:00)
| Time | Activity | Owner | Location | Notes |
|------|----------|-------|----------|-------|
| 7:00 | Venue access, load-in begins | Lisa | Main Hall | AV vendor arrives at 7:00 |
| 7:30 | AV setup and test | AV Team | Main Hall + Breakouts | Projector, mics, streaming |
| 8:00 | Catering setup | Caterer | Foyer | Coffee station live by 8:30 |
| 8:30 | Registration desk setup | Mike | Entrance | Name badges, programs, swag |
| 8:45 | Speaker green room ready | Sarah | Room 201 | Water, snacks, presentation check |

### Morning Program (9:00 – 12:00)
| Time | Activity | Speaker | Location | Duration |
|------|----------|---------|----------|----------|
| 9:00 | Welcome & opening remarks | CEO | Main Hall | 15 min |
| 9:15 | Keynote: "The Future of X" | Dr. Jane Doe | Main Hall | 45 min |
| 10:00 | Coffee break | — | Foyer | 30 min |
| 10:30 | Panel: Industry Trends | Moderator + 3 panelists | Main Hall | 60 min |
| 11:30 | Breakout: Workshop A | Alice | Breakout A | 60 min |
| 11:30 | Breakout: Workshop B | Bob | Breakout B | 60 min |

### Afternoon Program (12:00 – 18:00)
| Time | Activity | Speaker | Location | Duration |
|------|----------|---------|----------|----------|
| 12:00 | Lunch | — | Foyer | 60 min |
| 13:00 | Lightning talks (5 × 10 min) | Various | Main Hall | 50 min |
| 13:50 | Break | — | Foyer | 20 min |
| 14:10 | Keynote: "Building for Scale" | John Smith | Main Hall | 45 min |
| 15:00 | Breakout: Workshop C | Carol | Breakout A | 60 min |
| 15:00 | Breakout: Workshop D | Dave | Breakout B | 60 min |
| 16:00 | Afternoon break | — | Foyer | 15 min |
| 16:15 | Closing panel & Q&A | All speakers | Main Hall | 45 min |
| 17:00 | Networking reception | — | Foyer | 60 min |
| 18:00 | Event ends, teardown begins | Lisa | All | |

### Staff Assignments
- **Registration**: Mike (8:30–10:00), then roaming
- **AV / Tech**: AV vendor on-site all day, Sarah as point of contact
- **Speaker liaison**: Sarah (green room, transitions, time keeping)
- **Logistics / catering**: Lisa (setup, vendor coordination, teardown)
- **Photography**: Photographer (9:00–17:00)
```

### attendees.md — Guest List

```markdown
## RSVPs

| Name | Company | RSVP | Dietary | VIP | Notes |
|------|---------|------|---------|-----|-------|
| Jane Doe | Keynote Speaker | confirmed | none | yes | Arriving 8:30, needs podium mic |
| John Smith | Keynote Speaker | confirmed | vegetarian | yes | Remote backup slides on USB |
| Alice Wong | Workshop A | confirmed | none | yes | Needs whiteboard in Breakout A |
| Bob Park | Workshop B | confirmed | gluten-free | yes | Bringing own laptop for demo |
| Sarah Johnson | Acme Corp | confirmed | none | no | |
| Mike Chen | TechStart | confirmed | vegan | no | |
| Lisa Rivera | DataFlow | pending | unknown | no | Follow up by April 10 |

## Summary
- **Confirmed**: 47
- **Pending**: 38
- **Declined**: 0
- **Capacity**: 120 (Main Hall)

## Dietary Summary
- Vegetarian: 3
- Vegan: 1
- Gluten-free: 2
- None/unknown: 79
```

### budget.md — Budget Tracking

```markdown
## Budget Allocation

| Category | Allocated | Notes |
|----------|-----------|-------|
| Venue | $5,000 | Main hall + 2 breakouts, full day |
| Catering | $4,500 | Lunch + 2 coffee breaks + reception |
| AV & Tech | $2,000 | Projector, mics, streaming setup |
| Speakers | $3,000 | Honorariums + travel for 2 external |
| Marketing | $1,000 | Email campaign, social, printed programs |
| Photography | $1,500 | 4 hours, headshots + candid |
| Materials | $500 | Name badges, programs, swag bags |
| Contingency | $1,500 | 8% buffer |
| **Total** | **$19,000** | |

## Expense Log

| Date | Vendor | Category | Amount | Status | Notes |
|------|--------|----------|--------|--------|-------|
| 2026-03-15 | Grand Conference Center | Venue | $2,000 | paid | Deposit (50%) |
| 2026-03-20 | TechAV Solutions | AV & Tech | $600 | paid | Deposit for equipment rental |
| 2026-03-22 | MailChimp | Marketing | $50 | paid | Email campaign send |
| 2026-03-25 | PrintShop | Marketing | $400 | committed | Programs + banners, due April 20 |
| 2026-03-28 | Grand Conference Center | Venue | $3,000 | committed | Balance due April 25 |
| 2026-03-28 | TechAV Solutions | AV & Tech | $600 | committed | Balance due event day |
| — | Good Eats Catering | Catering | $4,500 | estimated | Pending menu confirmation |
| — | Dr. Jane Doe | Speakers | $1,500 | committed | Keynote honorarium |
| — | John Smith | Speakers | $1,000 | committed | Keynote + travel |

## Running Totals
- **Committed**: $9,150
- **Paid**: $3,050
- **Remaining budget**: $9,850
- **Estimated final**: ~$18,250 (under budget by ~$750)
```

### timeline.md — Activity Log (Mission Control Format)

```markdown
## 2026-03-28

- 15:00 — RSVP update: 47 confirmed, 38 pending (55% response rate)
- 14:00 — Card mc-j0k1l2 moved to **In Progress** — "Finalize speaker slides"
- 11:00 — Catering call with Maria (Good Eats) — menu options reviewed, dietary needs shared
- 09:00 — AV deposit paid ($600) — TechAV Solutions confirmed for April 30

## 2026-03-27

- 16:00 — Budget update: $9,150 committed of $19,000 allocated
- 14:00 — 2 more RSVPs received (total: 45 at that point)

## 2026-03-18

- 10:00 — Save-the-date emails sent to 85 invitees
- 09:00 — Card mc-s9t0u1 moved to **Done** — "Send save-the-date"

## 2026-03-15

- 14:00 — Venue booked: Grand Conference Center, deposit $2,000 paid
- 10:00 — Card mc-p6q7r8 moved to **Done** — "Book venue"
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` for vendor confirmations, RSVP milestones, budget changes, and planning decisions.

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.

---

## Guidelines

- **Critical path focus**: Always track the next 2-3 deadlines that would delay the event if missed. Surface them in status.md.
- **Vendor confirmations**: Every vendor commitment gets an `append_timeline_event` entry and a task card if action is needed.
- **RSVP tracking**: Update attendees.md after each batch of responses. Log milestones (50% response, final count) to timeline.
- **Budget discipline**: Log every expense commitment in budget.md immediately. Update status.md budget line when totals change.
- **Day-of schedule**: Create schedule.md when speakers/agenda are mostly confirmed. Don't over-detail too early.
- **Post-event**: After the event, archive all files and create a retrospective note with what went well/poorly.
- **Tool reference**: `create_task_card` (new prep task), `move_task_card` (task completion), `append_timeline_event` (vendor confirmations, RSVPs, budget changes, decisions).
