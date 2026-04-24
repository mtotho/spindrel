# UI Design — Canonical Spec

> This is the target spec for UI work in Spindrel. Consult it before writing or reviewing any UI change.
> The execution log lives in `vault/Projects/agent-server/Track - UI Polish.md`; this doc is where that work is going.

## North Star

- **Low chrome.** Spacing and surface tints separate regions. Borders are the exception, not the default.
- **Calm color.** Color carries meaning; it does not decorate.
- **Native feel.** Desktop reads like a clean product; mobile reads like a native app.

## How to use this doc

- Each section leads with a **Trigger** — the condition under which it applies.
- Rules are imperative (`Do X`, `Never Y`).
- Examples cite real `file:line` references.
- The Anti-patterns table (§6) and Known debt appendix (§8) exist to prevent regressions and clean up drift.

## Triggers — when to consult which section

| You are about to... | Go to... |
|---|---|
| Add a color, background, border, or text shade | §1 Tokens & theming |
| Style the chat composer, tool output, metadata row, or mini chat dock | §2.1 Command surfaces |
| Style settings, admin, onboarding, dashboards, or prose | §2.2 Content surfaces |
| Pick a corner radius, spacing, or type size | §3 Scales |
| Style a button, badge, input, banner, toast, card, or active nav row | §4 Components |
| Ship any UI change | §5 Dark + light parity + §7 Accessibility floor |
| Fix UI debt you spotted | §8 Known debt |

---

## §1 — Tokens & theming

**Trigger:** any new color, background, border, or text shade.

### Rules

- **Use Tailwind classes that reference CSS variables.** All colors live in `ui/global.css` (lines 24–66) and are consumed by `ui/tailwind.config.cjs` (lines 12–47). Write `bg-surface`, `border-surface-border`, `text-text-muted`, `bg-accent/[0.08]`. Never write a hex literal in application code.
- **Never introduce a new color token inside a component.** If you need one, add it to `global.css` (both the `:root` light branch and the `.dark` branch) and to `tailwind.config.cjs`. In that order.
- **`useThemeTokens()` is debt.** Do not use it in new code. Existing callers are tolerated; do not expand them.
- **Dark mode flips via the `.dark` class on the root.** Components do not branch on mode — the tokens swap for free.

### Canonical token names

| Tailwind class | CSS variable | Purpose |
|---|---|---|
| `bg-surface` | `--color-surface` | Page background |
| `bg-surface-raised` | `--color-surface-raised` | Cards, panels, tiles |
| `bg-surface-overlay` | `--color-surface-overlay` | Hover state, active row fill, softly raised region |
| `border-surface-border` | `--color-surface-border` | Default border / divider |
| `text-text` | `--color-text` | Primary text |
| `text-text-muted` | `--color-text-muted` | Secondary text, labels |
| `text-text-dim` | `--color-text-dim` | Tertiary text, metadata, timestamps |
| `bg-accent` / `text-accent` | `--color-accent` | Primary interactive — buttons, active state, focus rings |
| `bg-accent/[0.08]` / `bg-accent/[0.12]` | — | Low-opacity accent for active rows and selected state |
| `bg-input` / `border-input-border` | `--color-input-bg` / `--color-input-border` | Form inputs |
| `text-success` / `bg-success` | `--color-success` | Success state only |
| `text-warning` / `text-warning-muted` | `--color-warning` / `--color-warning-muted` | Caution state only |
| `text-danger` / `text-danger-muted` | `--color-danger` / `--color-danger-muted` | Destructive / error only |
| `text-purple` | `--color-purple` | Skills / learning-center chrome (reserved) |
| `bg-skeleton` | `--color-skeleton` | Skeleton loading blocks (flips light ↔ dark) |

### Anti-pattern — inline hex in React

```tsx
// ❌ bypasses theming, breaks dark mode
<div style={{ color: "#8b5cf6" }}>Scheduled</div>

// ✅ token + Tailwind, dark mode free
<div className="text-purple">Scheduled</div>
```

---

## §2 — Two surface archetypes

Every screen in Spindrel is one of two archetypes. The rules differ. The tokens do not.

### §2.1 — Command surfaces

**Trigger:** chat composer, tool call / tool result rendering, metadata bars, IDs and hashes, model names, mini chat dock (`ChatSessionDock.tsx`), terminal-mode chat feed, Dev Panel.

#### Rules

- **Font stack**: monospace only. Use `TERMINAL_FONT_STACK` from `ui/src/components/chat/MessageInput.tsx`. Do not mix in sans fallback.
- **Corners**: square (`rounded-none`) OR minimal (`rounded-sm` = 2px) for chrome. Message containers stay at 4px (`rounded`) for a soft reading rhythm; surrounding chrome is square.
- **Chrome**: none. No drop shadows. No heavy borders. Separate regions with a tonal shift from `bg-surface-raised` to `bg-surface-overlay`.
- **Affordances**: inline and ghost. `+` is a character glyph, not an outlined pill. The send arrow is monochrome.
- **Metadata row**: below the composer, model name + mode + token chips in `text-text-dim`. Uppercase labels use `text-[10px] tracking-[0.08em]`.
- **Composer placement**: `transcript-flow` — the composer is part of the transcript and scrolls off. See `chatModes.ts:22-27`.
- **Density**: no bubble chrome around messages. `assistant:<name>` prefix is lowercase. Thinking collapses into a top-of-turn block.

#### Canonical references

- `ui/src/components/chat/chatModes.ts:22-27` — terminal = `composerPlacement: "transcript-flow"`.
- `ui/src/components/chat/MessageInput.tsx` — `TERMINAL_FONT_STACK`; terminal composer uses a slightly brighter surface fill, no border, no footer chrome (see `Track - UI Polish`).
- `ui/src/components/chat/MessageBubble.tsx` — 4px message corner in both modes; terminal branch drops bubble chrome.
- `ui/src/components/chat/ChatSessionDock.tsx` — mini chat dock; terminal variant drops the outer rounded-card border, uses a subtle header tint instead of a divider.
- `ui/src/components/chat/StreamingIndicator.tsx` — terminal `(thinking...)` status line with animated dots (`.terminal-thinking-dot`, `global.css:263-272`).

### §2.2 — Content surfaces

**Trigger:** settings pages, admin pages, onboarding, widget dashboards and tiles, prose pages, knowledge base views, detail panels, top navigation, sidebar.

#### Rules

- **Font stack**: system sans-serif. Already applied globally via `body` in `global.css:118-123`. Do not override.
- **Corners**: `rounded-md` (6px) by default. `rounded-lg` (10px) only for large hero cards and widget tiles. `rounded-full` only for avatars, status pills, and the active-row pill indicator (§4).
- **Chrome**: one border only. Never stack `border + drop-shadow + raised-bg`. Default: `bg-surface-raised` on `bg-surface`, no border.
- **Spacing, not dividers**: separate regions with `gap-*` and `bg-surface-raised` steps. Never a `border-b` or `border-l` between stacked bars.
- **Typography**: headings and body in `text-text`; labels and metadata in `text-text-muted` / `text-text-dim`. Section labels uppercase `text-[10px] tracking-[0.08em] text-text-dim/70`.
- **Status**: pill shape (`rounded-full`), `bg-surface-overlay`, no outline. Color only when it carries state.

#### Canonical references

- `ui/src/components/layout/Sidebar.tsx`, `sidebar/SidebarRail.tsx`, `sidebar/ChannelList.tsx` — the exemplars for content-surface chrome.
- `ui/global.css:8-20` — canonical `.sidebar-item`, `.sidebar-item-active`, `.sidebar-section-label`, `.sidebar-rail-btn` component classes.
- `ui/src/components/layout/DetailPanel.tsx` — single-border detail panel, flat typography.
- `ui/app/(app)/channels/[channelId]/ChannelHeader.tsx` — unified glass header; no stacked borders.

### §2.3 — Shared baseline (both archetypes)

- Same token system (§1).
- Same accent color for interactive state.
- Same active-row pill indicator (§4).
- Same restraint — no drop shadows, no bright borders, no colored decoration.
- Same accessibility floor (§7).

**Archetype is a font-and-density choice, not a theme choice.** Dark/light applies identically across both.

---

## §3 — Scales

**Trigger:** you need to pick a radius, spacing, or type size.

### Radius

| Class | Size | Use |
|---|---|---|
| `rounded-none` | 0 | Command-surface chrome (terminal composer, code blocks in terminal) |
| `rounded-sm` | 2px | Inline code in default mode, minimal chrome in command surfaces |
| `rounded` | 4px | Message bubbles (both modes), small chips |
| `rounded-md` | 6px | **Default for content surfaces** — nav items, buttons, inputs, cards |
| `rounded-lg` | 10px | Large hero cards, widget tiles |
| `rounded-full` | — | Avatars, status pills, active-row pill indicator |

Do not use `rounded-xl` or larger. Do not use a radius not on this scale.

### Spacing rhythm

4 / 8 / 12 / 16 / 24 (Tailwind: `gap-1` / `gap-2` / `gap-3` / `gap-4` / `gap-6`).

- `gap-3` (12px) — nav items, sidebar lists.
- `gap-4` (16px) — card content, form sections.
- `gap-2` (8px) — inline chips, button clusters.

### Typography

| Class | Use |
|---|---|
| `text-[10px] uppercase tracking-[0.08em] text-text-dim/70` | Section labels |
| `text-xs text-text-muted` | Secondary metadata, inline meta, timestamps |
| `text-sm` | Body, labels, most UI text |
| `text-base` | Message content, prose |
| `text-lg font-medium` | Card titles, modal headings |

**Font families:**
- Sans: inherited from `body` (system stack, `global.css:118-123`).
- Mono: `TERMINAL_FONT_STACK` from `MessageInput.tsx`. Apply via inline style on the element that needs it — Tailwind does not own this stack.

### Motion

- Interactive transitions: 100ms (`transition-colors duration-100`).
- Fade-in / skeleton-swap: 150ms.
- Entrance animations: 200–260ms (`chat-dock-expand-in`, `animate-toast-in`).
- Honor `prefers-reduced-motion`. Motion is never the only feedback channel.

### Shadow

Almost never. Signal elevation with `bg-surface-raised` + optional `border-surface-border`. Do not introduce `shadow-lg` / `shadow-xl` in new code.

---

## §4 — Components

**Trigger:** styling any of the listed elements.

### Buttons

- **Primary**: `bg-accent text-white rounded-md px-3 py-2 hover:bg-accent-hover`. Never `bg-blue-500` literal.
- **Secondary / ghost**: transparent background, `text-text`, `hover:bg-surface-overlay/60`. See `.input-action-btn` and `.header-icon-btn` (`global.css:316-344`).
- **Destructive**: `text-danger hover:bg-danger/10`. Reserved for confirm dialogs and danger-zone rows.
- Never combine `border + bg-color + shadow` on one button. Pick one.
- Gradient buttons (accent → purple) are reserved for the send button in the default-mode composer; do not generalize them.

### Badges / chips

- Base: `inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs bg-surface-overlay text-text-muted`.
- Metadata / state labels: add `uppercase tracking-[0.08em] text-[10px]`.
- Semantic — use only when carrying state: `bg-success/10 text-success`, `bg-warning/10 text-warning-muted`, `bg-danger/10 text-danger-muted`, `bg-accent/10 text-accent`.
- **Never** `bg-blue-500/[0.12] text-blue-600` for running/active. Use `bg-accent/10 text-accent`.

### Inputs

- `bg-input border border-input-border rounded-md px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40`.
- Placeholder color comes from the global rule (`global.css:162-166`) using `text-text-dim`.
- 16px minimum font-size — already enforced globally (`global.css:113-115`).
- Never an inset shadow to suggest depth; use `bg-input` against `bg-surface-raised`.

### Active-row indicator — the canonical pattern

**The one canonical active-state signal** for nav items, sidebar rail buttons, and list rows. Copy it; do not invent alternatives.

```css
/* from ui/global.css:11-13 */
.sidebar-item-active {
  @apply bg-accent/[0.08] relative
         before:content-[''] before:absolute before:left-0
         before:top-1/2 before:-translate-y-1/2
         before:w-[3px] before:h-4 before:rounded-full before:bg-accent;
}
```

- 3px × 16px accent bar, rounded-full, pinned left-center.
- `bg-accent/[0.08]` low-opacity fill on the row.
- Hover (inactive): `hover:bg-surface-overlay/60`.

**This is not the colored-left-stripe anti-pattern.** The anti-pattern is a 2–4px full-height colored border on dropdown / menu / autocomplete rows used to mark hover. The pattern above is narrow, restrained, and reserved for persistent navigation selection.

### Banners / toasts

- `bg-surface-raised border-l-2 border-warning text-text-muted p-3 rounded-md` for caution (left border uses a semantic token, not a decorative stripe).
- Icon color uses a `text-*` token (`text-warning-muted`, `text-danger-muted`) — never an inline hex.
- No `animate-pulse` on whole-row states. Use `.thinking-pulse` (`global.css:275-279`) or `.terminal-thinking-dot` (`global.css:263-272`) for a single dot.

### Cards / dashboards

- `rounded-md bg-surface-raised border border-surface-border p-4` — single border, single surface step.
- Widget tiles: `rounded-lg` for hero tiles; `rounded-md` for grid items.
- Hover: `hover:bg-surface-overlay/60`. Selected: the accent-pill pattern above.
- Never stack `border + shadow`. Almost never a shadow at all.

### Message bubbles

- `rounded` (4px) in both modes.
- User-message tint in default mode: `bg-surface-overlay/40`. No border. No `bg-purple-*` accent.
- Terminal mode: no chrome around messages; `assistant:<name>` header in lowercase mono.
- Hover reveals `.msg-actions` (copy / trace) via the pattern in `global.css:227-246`.

### Scrollbars

- Default: 6px thumb using `--color-surface-border` (`global.css:127-149`).
- Secondary surfaces (sidebar panel, popovers, dropdowns): use `.scroll-subtle` (`global.css:394-417`) — the thumb only materializes on hover or focus.
- Touch devices hide the chat scrollbar entirely (`global.css:208-211`).

---

## §5 — Dark + light parity

**Trigger:** about to ship any UI change.

### Rules

- Both modes are co-equal. Neither is an afterthought.
- **Do not branch on mode in JSX.** Tokens swap via `.dark`; your component renders once.
- **Do not hardcode a mode-assuming color.** Not `text-white` where `text-text` works. Not `bg-gray-900` where `bg-surface-raised` works.
- **Verify both modes before claiming done.** Toggle via the moon/sun button in `SidebarRail`. Check: contrast, active-row visibility, focus rings, hover states, disabled states, border visibility, skeleton pulse visibility.

### Reference values

- Light (`global.css:24-44`): surfaces are light neutrals (`248 249 252` → `229 231 235` border). Text near-black.
- Dark (`global.css:46-66`): surfaces are navy-tinged (`15 17 23` → `46 48 59` border). Text near-white.

---

## §6 — Anti-patterns (replace-with)

**Trigger:** reviewing a PR or writing new UI.

| Instead of... | Do this... | Why |
|---|---|---|
| `bg-blue-500/[0.12] text-blue-600` Bootstrap-style running state | `bg-accent/10 text-accent` | Accent token carries dark mode; blue-500 literal is frozen to light |
| `style={{ color: "#8b5cf6" }}` inline hex | `className="text-purple"` | Inline hex skips dark mode entirely |
| 2–4px `border-l-blue-500` stripe on dropdown rows | `bg-surface-overlay/60` hover tint alone | Colored hover stripes on list rows read as AI slop |
| `border-b border-surface-border` between every stacked bar | Spacing + `bg-surface-raised` step | Bar-between-bar borders produce admin-chrome noise |
| `animate-pulse` on a running task row | Inline `.thinking-pulse` dot + muted label | Pulsing whole rows pull the eye; a single dot carries it |
| `shadow-lg` on a card | `bg-surface-raised border border-surface-border` | Shadows read as old admin UI; tonal lift is calmer |
| Hand-rolled badge with `rgba(...)` bg | Token-based chip from §4 Badges | Consistent across surfaces, free dark mode |
| Mixing `style={{ t.surfaceBorder }}` and Tailwind classes | Tailwind classes only | `useThemeTokens()` is debt; new code avoids it |
| Multiple radii in one view (4 / 8 / 12 / 16 mixed) | Pick one from §3 Radius | Scale discipline is the difference between polished and generic |
| Adding a new hex color to a component | Add a token to `global.css` + `tailwind.config.cjs` first | Components never own color |

---

## §7 — Accessibility floor

**Trigger:** about to ship any UI change.

### Required

- **Contrast**: 4.5:1 for body text, 3:1 for large text and icons. Both modes.
- **Focus rings**: visible and token-driven. Default: `focus:outline-none focus:ring-2 focus:ring-accent`.
- **Keyboard**: every interactive element is reachable by Tab; `Enter` and `Space` activate.
- **Touch targets**: ≥ 44×44 px on mobile. ≥ 8px spacing between neighbors.
- **Heading hierarchy**: don't skip levels; one `<h1>` per route.
- **Color is not the only signal**: pair with a glyph, label, or position.
- **Labels**: every input has a programmatic label (`<label htmlFor>` or `aria-label`).
- **Reduced motion**: honor `prefers-reduced-motion`. Motion is never the sole feedback channel.
- **Alt text**: every meaningful image has alt; decorative images have `alt=""`.
- **ARIA**: semantic HTML first; `role="button"` only when `<button>` won't work.

### Mobile-native baseline (already applied globally — don't undo)

- `-webkit-tap-highlight-color: transparent` on `*` (`global.css:71-73`) — kills the blue tap flash.
- 16px minimum input font-size (`global.css:113-115`) — prevents iOS auto-zoom on focus.
- `overscroll-behavior: none` on `body` (`global.css:97-102`) — no pull-to-refresh on chat pages.

---

## §8 — Known debt (cleanup backlog)

These violate the rules above. They predate the rules. When you touch any file below, migrate it in the same commit.

### Inline hex that bypasses theming

- `ui/src/components/chat/MarkdownContent.tsx:54-58` — `MENTION_COLORS` hard-coded (`#1e1b4b`, `#a5b4fc`, `#14532d`, `#7dd3fc`). Replace with paired light/dark tokens.
- `ui/src/components/shared/task/StepsJsonEditor.tsx` — JSON syntax colors (`#e06c75`, `#98c379`, `#c678dd`, …). Needs a paired light/dark token set.
- `ui/src/components/layout/SystemPauseBanner.tsx` — `color: "#f59e0b"` → `text-warning-muted`.
- `ui/src/components/layout/ApprovalToast.tsx:8` — `color: "#ef4444"` → `text-danger-muted`.
- `ui/src/components/settings/MemoryHygieneGroupBanner.tsx` — `color: "#8b5cf6"` → `text-purple`.
- `ui/src/components/chat/DelegationCard.tsx` — `color: "#8b5cf6"` → `text-purple`.
- `ui/src/components/workspace/IndexStatusBadge.tsx:36` — `color: "#14b8a6"` — add a `teal` token or reuse `text-success`.
- `ui/src/components/chat/ToolsInContextPanel.tsx:38-40` — `rgba(168,85,247,0.15)` / `rgba(16,185,129,0.15)` / `rgba(59,130,246,0.15)` status backgrounds. Replace with `bg-purple/10` / `bg-success/10` / `bg-accent/10`.

### Bootstrap-blue running / selected states

- `ui/src/components/shared/TaskConstants.tsx:1-4` — `bg-blue-500/[0.12] text-blue-600` task status. Replace with `bg-accent/10 text-accent`.
- `ui/src/components/shared/TaskStepEditor.tsx` — `bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse` running step. Replace with token pair; drop `animate-pulse`; use a single dot.

### `useThemeTokens()` callers to migrate opportunistically

Not a forced migration — migrate when you are already touching the file for another reason.

Examples:
- `ui/src/components/shared/FormControls.tsx`
- `ui/src/components/layout/DetailPanel.tsx`
- `ui/src/components/chat/ChatMessageArea.tsx` (skeleton)

---

## §9 — See also

- `vault/Projects/agent-server/Track - UI Polish.md` — execution log: what's been shipped and when.
- `vault/Projects/agent-server/Track - UI Vision.md` — living companion to this doc; tracks adoption and outstanding debt.
- `vault/Projects/agent-server/Architecture Decisions.md` — load-bearing design decisions (e.g. chat-screen zones, unified glass header).
- Feedback memories that reference this doc:
  - `feedback_no_gratuitous_borders.md`
  - `feedback_no_left_colored_borders.md`
  - `feedback_tailwind_not_inline.md`
  - `feedback_widgets_use_app_theme.md`
