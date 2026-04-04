---
name: "Sales / CRM"
description: "Sales pipeline management — deal tracking, contact management, follow-up scheduling, and revenue forecasting."
category: workspace_schema
compatible_integrations:
  - mission_control
mc_min_version: "2.0"
tags:
  - sales
  - crm
  - pipeline
  - deals
  - mission-control
group: "Business"
recommended_heartbeat:
  prompt: "Review the sales pipeline in tasks.md. Check for deals with overdue follow-ups or stale in any stage >2 weeks. Update status.md with pipeline summary and forecast. Log any stage changes or notable activity to timeline. Flag deals at risk."
  interval: "weekly"
  quiet_start: "20:00"
  quiet_end: "08:00"
---

## Workspace File Organization — Sales / CRM

Organize channel workspace files to track your sales pipeline and customer relationships. This schema is Mission Control compatible — deal tracking, status reporting, and activity logging follow the MC protocol.

Root files are living documents injected into every context — keep them concise.

### Root Files (auto-injected)

- **tasks.md** — Sales pipeline kanban (Mission Control compatible)
  - Deals as task cards flowing through pipeline stages
  - Each card: company, contact, value, next action, follow-up date
  - Use `create_task_card` and `move_task_card` tools

- **status.md** — Pipeline health and forecast (Mission Control compatible)
  - Phase/health/owner header block
  - Pipeline summary: deals per stage, total weighted value
  - This week's priorities and follow-ups due
  - Forecast: expected closes this month/quarter

- **contacts.md** — Contact and company directory
  - Key contacts: name, company, role, email, phone, relationship notes
  - Company profiles: size, industry, decision process, budget cycle
  - Interaction history highlights (last meeting, last email, sentiment)

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: deal stage changes, new deals, won/lost outcomes
  - Manual entries: meetings, calls, emails sent, proposals delivered
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

- **notes.md** — Meeting notes, call summaries, and strategy
  - Date-stamped entries: `## YYYY-MM-DD — Topic`
  - Objection handling notes
  - Competitive intelligence
  - Pricing discussions and discount approvals

Create files as needed — start with tasks.md and contacts.md, expand as the pipeline grows.

### Archive (`archive/`)

Closed deals (won and lost), old meeting notes. Searchable via `search_channel_archive`.

---

## File Formats

### tasks.md — Sales Pipeline Kanban (Mission Control Format)

Pipeline stages as kanban columns. Each deal is a task card.

```markdown
## Prospect

### Acme Corp — Enterprise Platform License
- **id**: mc-a1b2c3
- **priority**: high
- **tags**: enterprise, SaaS, inbound
- **assigned**: Sarah
- **due**: 2026-04-15
- contact: Jane Smith (VP Engineering) — jane@acme.com
- value: $120,000/yr
- next_action: Discovery call scheduled April 8
- source: Website demo request

### TechStart Inc — Team Plan
- **id**: mc-d4e5f6
- **priority**: medium
- **tags**: SMB, SaaS, referral
- **assigned**: Mike
- contact: Tom Chen (CTO) — tom@techstart.io
- value: $24,000/yr
- next_action: Send case study by April 5
- source: Referral from existing customer

## Qualified

### Global Retail Co — Analytics Add-on
- **id**: mc-g7h8i9
- **priority**: high
- **tags**: enterprise, analytics, expansion
- **assigned**: Sarah
- **started**: 2026-03-20
- contact: Lisa Park (Head of Data) — lisa@globalretail.com
- value: $85,000/yr
- next_action: Technical demo with their data team April 10
- budget_confirmed: yes
- decision_timeline: Q2 2026

## Proposal

### MedTech Solutions — Full Suite
- **id**: mc-j0k1l2
- **priority**: critical
- **tags**: enterprise, healthcare, competitive
- **assigned**: Sarah
- **started**: 2026-03-15
- contact: Dr. Ray Kumar (CIO) — ray@medtech.com
- value: $200,000/yr
- next_action: Proposal review meeting April 7
- competitor: Competing with Vendor X on price
- proposal_sent: 2026-03-28

## Negotiation

### DataFlow Labs — Platform Migration
- **id**: mc-m3n4o5
- **priority**: high
- **tags**: enterprise, migration, technical
- **assigned**: Mike
- **started**: 2026-03-10
- contact: Alex Rivera (VP Product) — alex@dataflow.io
- value: $150,000/yr
- next_action: Legal review of contract terms
- discount_approved: 10% (manager approved)

## Closed Won

### CloudFirst — Annual Renewal
- **id**: mc-p6q7r8
- **priority**: medium
- **completed**: 2026-03-25
- value: $45,000/yr
- notes: Renewed with 5% increase, added 2 seats

## Closed Lost

### RetailMax — Chose competitor
- **id**: mc-s9t0u1
- **priority**: high
- **completed**: 2026-03-22
- value: $95,000/yr (lost)
- reason: Price — competitor undercut by 30%
- notes: Maintain relationship, revisit at renewal
```

**Pipeline stages:**
- **Prospect** — Initial interest, no qualification yet
- **Qualified** — Budget, authority, need, and timeline confirmed (BANT)
- **Proposal** — Proposal or quote delivered, awaiting response
- **Negotiation** — Terms being discussed, contract in review
- **Closed Won** — Deal signed (archive after 30 days)
- **Closed Lost** — Deal lost (log reason, archive after 30 days)

**Card fields:**
- Standard MC fields: id, priority, assigned, tags, due, started, completed
- Sales-specific: contact, value, next_action, source, budget_confirmed, decision_timeline, competitor, discount_approved, proposal_sent, reason (for lost)

Use `create_task_card` and `move_task_card` tools — tasks.md is read-only from the database.

### status.md — Pipeline Health (Mission Control Format)

```markdown
- **phase**: Q2 2026 — Growth Push
- **health**: green
- **updated**: 2026-03-28
- **owner**: Sales Team

## Pipeline Summary

| Stage | Deals | Total Value | Weighted Value |
|-------|-------|-------------|----------------|
| Prospect | 2 | $144,000 | $14,400 (10%) |
| Qualified | 1 | $85,000 | $25,500 (30%) |
| Proposal | 1 | $200,000 | $100,000 (50%) |
| Negotiation | 1 | $150,000 | $120,000 (80%) |
| **Active Total** | **5** | **$579,000** | **$259,900** |

## This Week's Priorities
1. MedTech proposal review meeting (April 7) — $200K deal
2. DataFlow contract negotiation — legal review pending
3. Acme Corp discovery call (April 8) — new enterprise lead
4. Send TechStart case study by April 5

## Forecast
- **April closes (likely)**: DataFlow Labs $150K (80% confidence)
- **Q2 target**: $500K — currently $259K weighted pipeline
- **At risk**: MedTech — competitive pressure from Vendor X on pricing

## Recent Milestones
- 2026-03-25: CloudFirst renewed — $45K/yr (+5%)
- 2026-03-22: Lost RetailMax to competitor (price)
- 2026-03-20: Global Retail moved to Qualified — budget confirmed
```

**Health values:**
- `green` — pipeline healthy, forecast on track, no stale deals
- `yellow` — deals stale >2 weeks in any stage, forecast below target, follow-ups overdue
- `red` — multiple deals at risk, forecast significantly below target, key deals lost

**Weighted value formula:** Prospect 10%, Qualified 30%, Proposal 50%, Negotiation 80%.

### contacts.md — Contact Directory

```markdown
## Key Contacts

### Jane Smith — Acme Corp
- **role**: VP Engineering
- **email**: jane@acme.com
- **phone**: (555) 123-4567
- **company**: Acme Corp (Enterprise, 500+ employees, SaaS)
- **relationship**: New — inbound demo request March 2026
- **notes**: Technical buyer, cares about API integrations. Reports to CTO.
- **last contact**: 2026-03-28 — initial email exchange

### Lisa Park — Global Retail Co
- **role**: Head of Data
- **email**: lisa@globalretail.com
- **company**: Global Retail (Enterprise, 2000+ employees, Retail)
- **relationship**: Existing customer — expanding into analytics
- **notes**: Champion internally. Budget approved by CFO. Decision by end of Q2.
- **last contact**: 2026-03-25 — qualification call (45 min)

## Companies

### Acme Corp
- **industry**: Technology / SaaS
- **size**: 500+ employees
- **budget cycle**: Annual (January)
- **decision process**: VP → CTO → CFO sign-off above $100K
- **current tools**: Competitor Y for basic features
```

### timeline.md — Activity Log (Mission Control Format)

```markdown
## 2026-03-28

- 16:00 — Proposal sent to MedTech — Full Suite, $200K/yr
- 14:30 — Card mc-j0k1l2 moved to **Proposal** (was: Qualified) — "MedTech Full Suite"
- 11:00 — Discovery call with Jane Smith (Acme) — strong interest, scheduling follow-up
- 09:00 — New card created: mc-a1b2c3 "Acme Corp Enterprise Platform License"

## 2026-03-27

- 17:00 — DataFlow Labs: legal review started on contract terms
- 15:30 — Card mc-m3n4o5 moved to **Negotiation** — "DataFlow Platform Migration"
- 10:00 — Weekly pipeline review — 5 active deals, $260K weighted
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` for calls, meetings, emails sent, proposals delivered, and deal outcomes.

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.

---

## Guidelines

- **Pipeline hygiene**: Review pipeline weekly. Deals stale >2 weeks in any stage → update or mark at risk.
- **Stage progression**: Use `move_task_card` for all stage changes — this auto-timestamps and logs to timeline.
- **Contact tracking**: Update contacts.md `last contact` field after every meaningful interaction.
- **Weighted forecasting**: Prospect 10%, Qualified 30%, Proposal 50%, Negotiation 80%. Update status.md pipeline summary on every stage change.
- **Win/loss logging**: When closing, always record the reason. `append_timeline_event` for the outcome. Archive after 30 days.
- **Follow-up deadlines**: Set `due` on every card to the next follow-up date. Heartbeat flags overdue items.
- **Tool reference**: `create_task_card` (new deal), `move_task_card` (stage change), `append_timeline_event` (calls, meetings, proposals, outcomes).
