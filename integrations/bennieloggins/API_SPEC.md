  ---
  Agent POST API Spec

  Base URL: {BASE_URL}/api/agent
  Auth: Authorization: Bearer {AI_API_KEY}
  Content-Type: application/json

  All endpoints strip null fields from responses to save tokens.

  ---
  POST /api/agent/pooplogs

  Body:

  ┌─────────────┬────────────┬──────────┬───────────────────────────────────────────────────────────────────┐
  │    Field    │    Type    │ Required │                            Description                            │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ user        │ string     │ no       │ Fuzzy user hint (name/email substring). Falls back to first user. │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ moisture    │ int        │ yes      │ 0-10 scale                                                        │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ form        │ int        │ yes      │ 0-10 scale (Bristol Stool Chart)                                  │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ size        │ int        │ yes      │ 0-10 scale                                                        │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ color       │ string     │ no       │ Color description                                                 │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ location    │ string     │ no       │ Where it happened                                                 │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ notes       │ string     │ no       │ Additional notes                                                  │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ hasDrips    │ boolean    │ no       │ Drippy at end (default false)                                     │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ hasMucus    │ boolean    │ no       │ Contains mucus (default false)                                    │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ hasBlood    │ boolean    │ no       │ Contains blood (default false)                                    │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ strainLevel │ string     │ no       │ "normal", "mild", "moderate", "severe"                            │
  ├─────────────┼────────────┼──────────┼───────────────────────────────────────────────────────────────────┤
  │ createdAt   │ ISO string │ no       │ Override timestamp                                                │
  └─────────────┴────────────┴──────────┴───────────────────────────────────────────────────────────────────┘

  Response (201):
  {
    "id": "clxyz...",
    "date": "2026-03-24T12:00:00.000Z",
    "moisture": 5,
    "form": 4,
    "bristolChartDescription": "Smooth, soft sausage",
    "size": 6,
    "color": "brown",
    "location": "backyard",
    "hasDrips": false,
    "hasMucus": false,
    "hasBlood": false,
    "strainLevel": "normal",
    "notes": "Normal looking stool",
    "healthScore": 10
  }

  ---
  POST /api/agent/pukelogs

  Body:

  ┌───────────┬────────────┬──────────┬────────────────────────────────────────┐
  │   Field   │    Type    │ Required │              Description               │
  ├───────────┼────────────┼──────────┼────────────────────────────────────────┤
  │ user      │ string     │ no       │ Fuzzy user hint                        │
  ├───────────┼────────────┼──────────┼────────────────────────────────────────┤
  │ pukeType  │ string     │ yes      │ e.g. "liquid/mucus", "chunks", "other" │
  ├───────────┼────────────┼──────────┼────────────────────────────────────────┤
  │ size      │ int        │ yes      │ 0-10 scale                             │
  ├───────────┼────────────┼──────────┼────────────────────────────────────────┤
  │ notes     │ string     │ no       │ Additional notes                       │
  ├───────────┼────────────┼──────────┼────────────────────────────────────────┤
  │ createdAt │ ISO string │ no       │ Override timestamp                     │
  └───────────┴────────────┴──────────┴────────────────────────────────────────┘

  Response (201):
  {
    "id": "clxyz...",
    "date": "2026-03-24T12:00:00.000Z",
    "pukeType": "liquid/mucus",
    "size": 3,
    "notes": "Small amount after eating grass",
    "healthScore": 8
  }

  ---
  POST /api/agent/eating-issues

  Body:

  ┌─────────────────┬────────────┬──────────┬──────────────────────────────────────────────────────────────────┐
  │      Field      │    Type    │ Required │                           Description                            │
  ├─────────────────┼────────────┼──────────┼──────────────────────────────────────────────────────────────────┤
  │ user            │ string     │ no       │ Fuzzy user hint                                                  │
  ├─────────────────┼────────────┼──────────┼──────────────────────────────────────────────────────────────────┤
  │ eatingIssueType │ string     │ yes      │ e.g. "feeding-refused", "partial-eating", "slow-eating", "picky" │
  ├─────────────────┼────────────┼──────────┼──────────────────────────────────────────────────────────────────┤
  │ notes           │ string     │ no       │ Additional notes                                                 │
  ├─────────────────┼────────────┼──────────┼──────────────────────────────────────────────────────────────────┤
  │ createdAt       │ ISO string │ no       │ Override timestamp                                               │
  └─────────────────┴────────────┴──────────┴──────────────────────────────────────────────────────────────────┘

  Response (201):
  {
    "id": "clxyz...",
    "date": "2026-03-24T12:00:00.000Z",
    "eatingIssueType": "partial-eating",
    "notes": "Only ate half of breakfast",
    "healthScore": 8
  }

  ---
  POST /api/agent/eating-drinking

  Body:

  ┌───────────┬────────────┬──────────┬────────────────────────┐
  │   Field   │    Type    │ Required │      Description       │
  ├───────────┼────────────┼──────────┼────────────────────────┤
  │ user      │ string     │ no       │ Fuzzy user hint        │
  ├───────────┼────────────┼──────────┼────────────────────────┤
  │ type      │ string     │ yes      │ "eating" or "drinking" │
  ├───────────┼────────────┼──────────┼────────────────────────┤
  │ amount    │ int        │ yes      │ 0-10 scale             │
  ├───────────┼────────────┼──────────┼────────────────────────┤
  │ notes     │ string     │ no       │ Additional notes       │
  ├───────────┼────────────┼──────────┼────────────────────────┤
  │ createdAt │ ISO string │ no       │ Override timestamp     │
  └───────────┴────────────┴──────────┴────────────────────────┘

  Response (201):
  {
    "id": "clxyz...",
    "date": "2026-03-24T12:00:00.000Z",
    "type": "eating",
    "amount": 7,
    "notes": "Ate most of dinner bowl"
  }

  ---
  Common Error Responses

  ┌────────┬──────────────────────────────────────────────┬──────────────────────────┐
  │ Status │                     Body                     │           When           │
  ├────────┼──────────────────────────────────────────────┼──────────────────────────┤
  │ 400    │ {"error": "Missing required fields: ..."}    │ Required fields missing  │
  ├────────┼──────────────────────────────────────────────┼──────────────────────────┤
  │ 400    │ {"error": "Values must be between 0 and 10"} │ Range validation failed  │
  ├────────┼──────────────────────────────────────────────┼──────────────────────────┤
  │ 401    │ {"error": "Unauthorized"}                    │ Bad/missing Bearer token │
  ├────────┼──────────────────────────────────────────────┼──────────────────────────┤
  │ 500    │ {"error": "Internal server error"}           │ Server error             │
  └────────┴──────────────────────────────────────────────┴──────────────────────────┘

  User Resolution (user field)

  The optional user field is resolved fuzzy in this order:
  1. Case-insensitive substring match on name or email
  2. First-letter match on email (e.g. "michael" → email starting with "m")
  3. Fallback: first user in DB


