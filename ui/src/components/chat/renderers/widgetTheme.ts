/**
 * Widget theme layer — injected into every interactive HTML widget's iframe
 * so widgets inherit the app's design language (colors, spacing, typography,
 * component vocabulary) without hand-rolling inline styles.
 *
 * Widget authors style with:
 *   - CSS variables: `var(--sd-accent)`, `var(--sd-surface-raised)`, …
 *   - Utility/component classes: `sd-card`, `sd-btn`, `sd-chip-success`, …
 *   - JS: `window.spindrel.theme.accent`, `window.spindrel.theme.isDark`
 *
 * Values are populated from the active `ThemeTokens` at srcDoc-generation
 * time. A theme toggle rebuilds srcDoc — acceptable because theme toggles
 * are rare and the alternative (postMessage-based hot-swap) would need
 * the iframe to recompute every element's resolved color.
 *
 * Deliberately NOT a Tailwind subset — the iframe is a separate document
 * from the host's Tailwind build, and shipping a compiled atomic CSS sheet
 * into every widget is overkill. The `sd-*` vocabulary is the minimum set
 * that covers observed widget needs (cards, buttons, chips, stacks, grids,
 * status bars, progress bars, skeletons, form controls).
 */
import type { ThemeTokens } from "../../../theme/tokens";

export interface WidgetThemeInput {
  tokens: ThemeTokens;
  isDark: boolean;
}

/**
 * Build the full widget stylesheet string. Output goes into a `<style>`
 * block inside the iframe's `<head>`.
 */
export function buildWidgetThemeCss({ tokens: t, isDark }: WidgetThemeInput): string {
  return `
  :root {
    --sd-surface: ${t.surface};
    --sd-surface-raised: ${t.surfaceRaised};
    --sd-surface-overlay: ${t.surfaceOverlay};
    --sd-surface-border: ${t.surfaceBorder};
    --sd-text: ${t.text};
    --sd-text-muted: ${t.textMuted};
    --sd-text-dim: ${t.textDim};
    --sd-accent: ${t.accent};
    --sd-accent-hover: ${t.accentHover};
    --sd-accent-muted: ${t.accentMuted};
    --sd-accent-subtle: ${t.accentSubtle};
    --sd-accent-border: ${t.accentBorder};
    --sd-success: ${t.success};
    --sd-success-subtle: ${t.successSubtle};
    --sd-success-border: ${t.successBorder};
    --sd-warning: ${t.warning};
    --sd-warning-subtle: ${t.warningSubtle};
    --sd-warning-border: ${t.warningBorder};
    --sd-danger: ${t.danger};
    --sd-danger-subtle: ${t.dangerSubtle};
    --sd-danger-border: ${t.dangerBorder};
    --sd-purple: ${t.purple};
    --sd-purple-subtle: ${t.purpleSubtle};
    --sd-purple-border: ${t.purpleBorder};
    --sd-input-bg: ${t.inputBg};
    --sd-input-border: ${t.inputBorder};
    --sd-overlay-light: ${t.overlayLight};
    --sd-overlay-border: ${t.overlayBorder};
    --sd-skeleton-bg: ${t.skeletonBg};
    --sd-code-bg: ${t.codeBg};

    --sd-radius-sm: 4px;
    --sd-radius-md: 6px;
    --sd-radius-lg: 8px;
    --sd-gap-xs: 4px;
    --sd-gap-sm: 6px;
    --sd-gap-md: 10px;
    --sd-gap-lg: 16px;
    --sd-pad-sm: 8px;
    --sd-pad-md: 12px;
    --sd-pad-lg: 16px;
    --sd-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --sd-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    --sd-font-size: 13px;
    --sd-font-size-sm: 11px;
    --sd-font-size-xs: 10px;
    --sd-line: 1.4;
  }

  /* ── Reset + body ─────────────────────────────────────────── */
  html, body {
    margin: 0;
    padding: 0;
    font-family: var(--sd-font-sans);
    font-size: var(--sd-font-size);
    line-height: var(--sd-line);
    color: var(--sd-text);
    background: var(--sd-surface-raised);
  }
  /* Host wraps the iframe in its own padded card (WidgetCard, PinnedToolWidget,
     ToolsSandbox). We intentionally sit flush inside that container — widgets
     that want inner chrome opt in via .sd-card; flatter layouts (image-heavy,
     chart-heavy) can fill the full tile by not using sd-card. */
  body { padding: 0; overflow-y: auto; }
  * { box-sizing: border-box; max-width: 100%; }
  img, video { max-width: 100%; height: auto; border-radius: var(--sd-radius-sm); }
  a { color: var(--sd-accent); text-decoration: none; }
  a:hover { color: var(--sd-accent-hover); text-decoration: underline; }
  code, pre { font-family: var(--sd-font-mono); background: var(--sd-code-bg); border-radius: var(--sd-radius-sm); }
  code { padding: 1px 4px; font-size: 12px; }
  pre { padding: 8px 10px; overflow-x: auto; font-size: 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { padding: 4px 8px; text-align: left; font-size: var(--sd-font-size-sm); }
  thead th { color: var(--sd-text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: var(--sd-font-size-xs); border-bottom: 1px solid var(--sd-surface-border); }
  tbody td { border-bottom: 1px solid var(--sd-surface-border); }
  tbody tr:last-child td { border-bottom: none; }

  /* ── Scrollbar (match host) ───────────────────────────────── */
  * { scrollbar-width: thin; scrollbar-color: var(--sd-surface-border) transparent; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--sd-surface-border); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--sd-text-dim); }
  ::-webkit-scrollbar-corner { background: transparent; }

  /* ── Root wrapper (measured by host for iframe auto-sizing) ─ */
  #__sd_root { display: block; }

  /* ── Layout ───────────────────────────────────────────────── */
  .sd-stack { display: flex; flex-direction: column; gap: var(--sd-gap-md); }
  .sd-stack-sm { gap: var(--sd-gap-sm); }
  .sd-stack-lg { gap: var(--sd-gap-lg); }
  .sd-hstack { display: flex; flex-direction: row; align-items: center; gap: var(--sd-gap-md); flex-wrap: wrap; }
  .sd-hstack-sm { gap: var(--sd-gap-sm); }
  .sd-hstack-lg { gap: var(--sd-gap-lg); }
  .sd-hstack-between { justify-content: space-between; }
  .sd-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--sd-gap-md); }
  .sd-grid-2 { grid-template-columns: repeat(2, 1fr); }
  .sd-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: var(--sd-gap-sm); }
  .sd-spacer { flex: 1; }

  /* ── Typography ───────────────────────────────────────────── */
  .sd-title { margin: 0; font-size: 14px; font-weight: 600; letter-spacing: 0.01em; color: var(--sd-text); }
  .sd-subtitle { margin: 0; font-size: var(--sd-font-size-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--sd-text-muted); }
  .sd-meta { font-size: var(--sd-font-size-sm); color: var(--sd-text-muted); }
  .sd-muted { color: var(--sd-text-muted); }
  .sd-dim { color: var(--sd-text-dim); }
  .sd-mono { font-family: var(--sd-font-mono); font-size: 12px; }

  /* ── Surfaces ─────────────────────────────────────────────── */
  .sd-card { background: var(--sd-surface-raised); border-radius: var(--sd-radius-lg); padding: var(--sd-pad-md); display: flex; flex-direction: column; gap: var(--sd-gap-md); }
  .sd-card-header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--sd-gap-sm); }
  .sd-card-body { display: flex; flex-direction: column; gap: var(--sd-gap-md); }
  .sd-card-actions { display: flex; flex-direction: row; gap: var(--sd-gap-sm); flex-wrap: wrap; }
  .sd-tile { background: var(--sd-surface-overlay); border: 1px solid var(--sd-surface-border); border-radius: var(--sd-radius-md); padding: var(--sd-pad-sm); display: flex; flex-direction: column; gap: var(--sd-gap-xs); }
  .sd-frame { position: relative; border-radius: var(--sd-radius-md); overflow: hidden; background: var(--sd-surface-overlay); }
  .sd-frame-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--sd-text-muted); font-size: var(--sd-font-size-sm); }

  /* ── Controls ─────────────────────────────────────────────── */
  .sd-btn {
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--sd-gap-xs);
    padding: 4px 10px;
    border: 1px solid var(--sd-surface-border);
    background: var(--sd-surface-overlay);
    color: var(--sd-text);
    border-radius: var(--sd-radius-sm);
    font-size: var(--sd-font-size-sm);
    font-family: inherit;
    cursor: pointer;
    transition: background 120ms, border-color 120ms, color 120ms;
  }
  .sd-btn:hover { background: var(--sd-overlay-light); }
  .sd-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .sd-btn[aria-pressed="true"] { background: var(--sd-accent); border-color: var(--sd-accent); color: white; }
  .sd-btn-primary { background: var(--sd-accent); border-color: var(--sd-accent); color: white; }
  .sd-btn-primary:hover { background: var(--sd-accent-hover); border-color: var(--sd-accent-hover); color: white; }
  .sd-btn-subtle { background: transparent; border-color: transparent; color: var(--sd-text-muted); }
  .sd-btn-subtle:hover { background: var(--sd-overlay-light); color: var(--sd-text); }
  .sd-btn-danger { background: var(--sd-danger-subtle); border-color: var(--sd-danger-border); color: var(--sd-danger); }
  .sd-btn-danger:hover { background: var(--sd-danger); border-color: var(--sd-danger); color: white; }

  .sd-input, .sd-select, .sd-textarea {
    appearance: none;
    padding: 4px 8px;
    border: 1px solid var(--sd-input-border);
    background: var(--sd-input-bg);
    color: var(--sd-text);
    border-radius: var(--sd-radius-sm);
    font-size: var(--sd-font-size-sm);
    font-family: inherit;
    outline: none;
  }
  .sd-input:focus, .sd-select:focus, .sd-textarea:focus { border-color: var(--sd-accent); }

  /* ── Status chips ─────────────────────────────────────────── */
  .sd-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border-radius: var(--sd-radius-sm);
    font-size: var(--sd-font-size-xs);
    font-weight: 500;
    background: var(--sd-overlay-light);
    color: var(--sd-text-muted);
    border: 1px solid transparent;
  }
  .sd-chip-accent { background: var(--sd-accent-subtle); color: var(--sd-accent); border-color: var(--sd-accent-border); }
  .sd-chip-success { background: var(--sd-success-subtle); color: var(--sd-success); border-color: var(--sd-success-border); }
  .sd-chip-warning { background: var(--sd-warning-subtle); color: var(--sd-warning); border-color: var(--sd-warning-border); }
  .sd-chip-danger { background: var(--sd-danger-subtle); color: var(--sd-danger); border-color: var(--sd-danger-border); }
  .sd-chip-purple { background: var(--sd-purple-subtle); color: var(--sd-purple); border-color: var(--sd-purple-border); }

  /* ── Progress bar ─────────────────────────────────────────── */
  /*   <div class="sd-progress" style="--p: 60"></div>   */
  .sd-progress {
    position: relative;
    width: 100%;
    height: 4px;
    border-radius: 2px;
    background: var(--sd-surface-overlay);
    overflow: hidden;
  }
  .sd-progress::after {
    content: "";
    position: absolute;
    inset: 0;
    width: calc(var(--p, 0) * 1%);
    background: var(--sd-accent);
    transition: width 240ms ease-out;
  }
  .sd-progress-success::after { background: var(--sd-success); }
  .sd-progress-warning::after { background: var(--sd-warning); }
  .sd-progress-danger::after { background: var(--sd-danger); }

  /* ── Feedback ─────────────────────────────────────────────── */
  .sd-error { color: var(--sd-danger); font-size: var(--sd-font-size-sm); }
  .sd-empty { color: var(--sd-text-muted); font-size: var(--sd-font-size-sm); padding: var(--sd-pad-md); text-align: center; }
  /* Structured empty-state: <div class="sd-empty"><svg class="sd-icon sd-empty__icon">…</svg>
     <div class="sd-empty__title">Nothing yet</div><div class="sd-empty__subtitle">…</div></div> */
  .sd-empty__icon { display: block; margin: 0 auto 6px; width: 28px; height: 28px; color: var(--sd-text-dim); }
  .sd-empty__title { font-size: var(--sd-font-size); font-weight: 600; color: var(--sd-text); margin-bottom: 2px; }
  .sd-empty__subtitle { font-size: var(--sd-font-size-sm); color: var(--sd-text-muted); }
  .sd-empty__cta { margin-top: 10px; display: inline-flex; }
  .sd-skeleton { background: var(--sd-skeleton-bg); border-radius: var(--sd-radius-sm); animation: sd-skeleton-pulse 1.5s ease-in-out infinite; }
  @keyframes sd-skeleton-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .sd-spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid var(--sd-surface-border);
    border-top-color: var(--sd-accent);
    border-radius: 50%;
    animation: sd-spinner-rotate 700ms linear infinite;
  }
  @keyframes sd-spinner-rotate { to { transform: rotate(360deg); } }

  /* ── Divider ──────────────────────────────────────────────── */
  .sd-divider { height: 1px; background: var(--sd-surface-border); border: none; margin: var(--sd-gap-xs) 0; }

  /* ──────────────────────────────────────────────────────────── */
  /* sd-* v2 — richer component vocabulary                        */
  /* ──────────────────────────────────────────────────────────── */

  /* ── Icons ────────────────────────────────────────────────── */
  /* <svg class="sd-icon"><use href="#sd-icon-check"/></svg>
     Presentation attributes MUST live on the referencing <svg>, not the
     sprite root — <use> doesn't cascade stroke/fill from the sprite. */
  .sd-icon {
    display: inline-block;
    width: 16px; height: 16px;
    flex: 0 0 auto;
    vertical-align: middle;
    color: currentColor;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .sd-icon--sm { width: 14px; height: 14px; }
  .sd-icon--lg { width: 20px; height: 20px; }
  .sd-icon--xl { width: 28px; height: 28px; }
  .sd-icon--muted { color: var(--sd-text-muted); }
  .sd-icon--dim { color: var(--sd-text-dim); }
  .sd-icon--accent { color: var(--sd-accent); }
  .sd-icon--success { color: var(--sd-success); }
  .sd-icon--danger { color: var(--sd-danger); }
  .sd-icon--warning { color: var(--sd-warning); }
  /* Some icons use polygons/rects (star, grid, pause) — those want fill
     rather than stroke. Opt-in modifier keeps the default stroke pattern. */
  .sd-icon--filled { fill: currentColor; stroke: none; }

  /* ── Focus ring (shared) ──────────────────────────────────── */
  .sd-btn:focus-visible,
  .sd-input:focus-visible,
  .sd-select:focus-visible,
  .sd-textarea:focus-visible,
  .sd-check__box:focus-within,
  .sd-radio__dot:focus-within,
  .sd-switch__track:focus-within,
  .sd-row:focus-visible,
  .sd-menu-item:focus-visible {
    outline: 2px solid var(--sd-accent);
    outline-offset: 1px;
  }

  /* ── Custom checkbox: .sd-check ───────────────────────────── */
  /* <label class="sd-check">
       <input type="checkbox" />
       <span class="sd-check__box"><svg class="sd-check__mark" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg></span>
       <span class="sd-check__label">Label</span>
     </label> */
  .sd-check { display: inline-flex; align-items: center; gap: var(--sd-gap-sm); cursor: pointer; user-select: none; }
  .sd-check > input[type="checkbox"] { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .sd-check__box {
    position: relative;
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px;
    border: 2px solid var(--sd-surface-border);
    background: var(--sd-input-bg);
    border-radius: var(--sd-radius-sm);
    transition: background 120ms, border-color 120ms, box-shadow 120ms;
    flex: 0 0 auto;
  }
  .sd-check:hover .sd-check__box { box-shadow: 0 0 0 3px var(--sd-accent-subtle); }
  .sd-check__mark {
    width: 14px; height: 14px;
    stroke: white; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; fill: none;
    stroke-dasharray: 24; stroke-dashoffset: 24;
    transition: stroke-dashoffset 180ms ease-out;
  }
  .sd-check:hover .sd-check__box { border-color: var(--sd-accent); }
  .sd-check > input[type="checkbox"]:checked ~ .sd-check__box,
  .sd-check[data-checked="true"] .sd-check__box {
    background: var(--sd-accent);
    border-color: var(--sd-accent);
  }
  .sd-check > input[type="checkbox"]:checked ~ .sd-check__box .sd-check__mark,
  .sd-check[data-checked="true"] .sd-check__box .sd-check__mark {
    stroke-dashoffset: 0;
  }
  .sd-check > input[type="checkbox"]:disabled ~ .sd-check__box,
  .sd-check[data-disabled="true"] .sd-check__box { opacity: 0.5; cursor: not-allowed; }
  .sd-check__label { font-size: var(--sd-font-size); color: var(--sd-text); }

  /* ── Custom radio: .sd-radio ──────────────────────────────── */
  .sd-radio { display: inline-flex; align-items: center; gap: var(--sd-gap-sm); cursor: pointer; user-select: none; }
  .sd-radio > input[type="radio"] { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .sd-radio__dot {
    position: relative;
    display: inline-flex; align-items: center; justify-content: center;
    width: 16px; height: 16px;
    border: 1.5px solid var(--sd-input-border);
    background: var(--sd-input-bg);
    border-radius: 50%;
    transition: border-color 120ms;
    flex: 0 0 auto;
  }
  .sd-radio__dot::after {
    content: "";
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--sd-accent);
    transform: scale(0);
    transition: transform 150ms ease-out;
  }
  .sd-radio:hover .sd-radio__dot { border-color: var(--sd-accent); }
  .sd-radio > input[type="radio"]:checked ~ .sd-radio__dot { border-color: var(--sd-accent); }
  .sd-radio > input[type="radio"]:checked ~ .sd-radio__dot::after { transform: scale(1); }

  /* ── Switch: .sd-switch ───────────────────────────────────── */
  /* <label class="sd-switch">
       <input type="checkbox" />
       <span class="sd-switch__track"><span class="sd-switch__thumb"></span></span>
       <span class="sd-switch__label">Enable</span>
     </label> */
  .sd-switch { display: inline-flex; align-items: center; gap: var(--sd-gap-sm); cursor: pointer; user-select: none; }
  .sd-switch > input[type="checkbox"] { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .sd-switch__track {
    position: relative;
    width: 28px; height: 16px;
    border-radius: 999px;
    background: var(--sd-surface-border);
    transition: background 150ms;
    flex: 0 0 auto;
  }
  .sd-switch__thumb {
    position: absolute;
    top: 2px; left: 2px;
    width: 12px; height: 12px;
    border-radius: 50%;
    background: var(--sd-surface-raised);
    box-shadow: 0 1px 2px rgba(0,0,0,0.25);
    transition: transform 150ms ease-out;
  }
  .sd-switch > input[type="checkbox"]:checked ~ .sd-switch__track { background: var(--sd-accent); }
  .sd-switch > input[type="checkbox"]:checked ~ .sd-switch__track .sd-switch__thumb { transform: translateX(12px); }
  .sd-switch > input[type="checkbox"]:disabled ~ .sd-switch__track { opacity: 0.5; cursor: not-allowed; }
  .sd-switch__label { font-size: var(--sd-font-size); color: var(--sd-text); }

  /* ── Input groups: leading icon + trailing button ─────────── */
  /* <div class="sd-input-group">
       <svg class="sd-icon sd-input-group__icon"><use href="#sd-icon-search"/></svg>
       <input class="sd-input" />
       <button class="sd-btn sd-btn-primary sd-input-group__action">Go</button>
     </div> */
  .sd-input-group {
    display: flex; align-items: stretch;
    background: var(--sd-input-bg);
    border: 1px solid var(--sd-input-border);
    border-radius: var(--sd-radius-md);
    transition: border-color 120ms, box-shadow 120ms;
    min-height: 36px;
  }
  .sd-input-group:hover { border-color: var(--sd-surface-border); }
  .sd-input-group:focus-within {
    border-color: var(--sd-accent);
    box-shadow: 0 0 0 3px var(--sd-accent-subtle);
  }
  .sd-input-group > .sd-input,
  .sd-input-group > .sd-select,
  .sd-input-group > .sd-textarea {
    flex: 1 1 auto; min-width: 0;
    background: transparent; border: none; outline: none;
    padding: 6px 10px;
    font-size: var(--sd-font-size);
  }
  .sd-input-group__icon {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 0 2px 0 10px;
    color: var(--sd-text-muted);
    width: auto; height: auto;
  }
  .sd-input-group__action {
    margin: 3px; padding: 4px 14px;
    border-radius: calc(var(--sd-radius-md) - 2px);
    flex: 0 0 auto;
    font-weight: 600;
  }
  .sd-input-group__addon {
    display: inline-flex; align-items: center; padding: 0 8px;
    color: var(--sd-text-muted); font-size: var(--sd-font-size-sm);
    border-left: 1px solid var(--sd-input-border);
  }

  /* ── Textarea auto-grow hook (sizing handled by spindrel.ui.autogrow) ── */
  .sd-textarea { resize: vertical; min-height: 64px; padding: 6px 8px; line-height: 1.45; }
  .sd-textarea[data-autogrow] { resize: none; overflow: hidden; min-height: 32px; }

  /* ── Rows + list container ────────────────────────────────── */
  /* <div class="sd-list sd-list--divided">
       <div class="sd-row">
         <svg class="sd-icon"><use href="#sd-icon-file"/></svg>
         <span class="sd-row__title">Title</span>
         <span class="sd-row__meta">12m</span>
         <span class="sd-row__actions">
           <button class="sd-btn sd-btn-subtle"><svg class="sd-icon sd-icon--sm"><use href="#sd-icon-trash"/></svg></button>
         </span>
       </div>
     </div> */
  .sd-list { display: flex; flex-direction: column; gap: 0; }
  .sd-list--divided > .sd-row + .sd-row { border-top: 1px solid var(--sd-surface-border); }
  .sd-list--gap { gap: var(--sd-gap-xs); }
  .sd-row {
    position: relative;
    display: flex; align-items: center; gap: var(--sd-gap-md);
    padding: 8px 8px;
    border-radius: var(--sd-radius-md);
    transition: background 120ms;
    min-height: 36px;
  }
  .sd-row:hover { background: var(--sd-overlay-light); }
  .sd-row--interactive { cursor: pointer; }
  .sd-row.sd-is-selected,
  .sd-row[aria-selected="true"] { background: var(--sd-accent-subtle); }
  .sd-row__title { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; color: var(--sd-text); }
  .sd-row__meta { flex: 0 0 auto; color: var(--sd-text-muted); font-size: var(--sd-font-size-sm); font-variant-numeric: tabular-nums; }
  .sd-row__actions {
    flex: 0 0 auto; display: inline-flex; gap: 2px;
    opacity: 0; transition: opacity 120ms ease;
  }
  .sd-row:hover .sd-row__actions,
  .sd-row:focus-within .sd-row__actions { opacity: 1; }
  .sd-row--done .sd-row__title { text-decoration: line-through; color: var(--sd-text-muted); }

  /* ── Section ──────────────────────────────────────────────── */
  .sd-section { display: flex; flex-direction: column; gap: var(--sd-gap-sm); }
  .sd-section__header {
    display: flex; align-items: center; justify-content: space-between;
    gap: var(--sd-gap-sm);
  }
  .sd-section__title { font-size: var(--sd-font-size-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--sd-text-muted); }
  .sd-inline { display: inline-flex; align-items: center; gap: var(--sd-gap-xs); }

  /* ── Tags (removable chip extension) ──────────────────────── */
  .sd-tag {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--sd-overlay-light);
    color: var(--sd-text);
    font-size: var(--sd-font-size-sm);
    border: 1px solid transparent;
    line-height: 1.4;
  }
  .sd-tag--accent { background: var(--sd-accent-subtle); color: var(--sd-accent); border-color: var(--sd-accent-border); }
  .sd-tag--success { background: var(--sd-success-subtle); color: var(--sd-success); border-color: var(--sd-success-border); }
  .sd-tag--warning { background: var(--sd-warning-subtle); color: var(--sd-warning); border-color: var(--sd-warning-border); }
  .sd-tag--danger { background: var(--sd-danger-subtle); color: var(--sd-danger); border-color: var(--sd-danger-border); }
  .sd-tag--purple { background: var(--sd-purple-subtle); color: var(--sd-purple); border-color: var(--sd-purple-border); }
  .sd-tag__remove {
    appearance: none;
    display: inline-flex; align-items: center; justify-content: center;
    width: 14px; height: 14px; margin-right: -4px;
    border: none; background: transparent; color: inherit;
    opacity: 0.6; cursor: pointer; border-radius: 50%;
    transition: opacity 120ms, background 120ms;
  }
  .sd-tag__remove:hover { opacity: 1; background: var(--sd-overlay-light); }

  /* ── Menu (popover) ───────────────────────────────────────── */
  .sd-menu {
    position: absolute; z-index: 1000;
    display: flex; flex-direction: column;
    min-width: 140px;
    padding: 4px;
    background: var(--sd-surface-raised);
    border: 1px solid var(--sd-surface-border);
    border-radius: var(--sd-radius-md);
    box-shadow: 0 6px 24px rgba(0,0,0,0.25);
  }
  .sd-menu-item {
    appearance: none;
    display: flex; align-items: center; gap: var(--sd-gap-sm);
    padding: 5px 8px;
    background: transparent;
    border: none;
    color: var(--sd-text);
    text-align: left;
    font-size: var(--sd-font-size-sm);
    font-family: inherit;
    border-radius: var(--sd-radius-sm);
    cursor: pointer;
    outline: none;
  }
  .sd-menu-item:hover,
  .sd-menu-item:focus-visible,
  .sd-menu-item[data-active="true"] { background: var(--sd-overlay-light); }
  .sd-menu-item--danger { color: var(--sd-danger); }
  .sd-menu-item--danger:hover { background: var(--sd-danger-subtle); }
  .sd-menu-divider { height: 1px; background: var(--sd-surface-border); margin: 4px 0; }

  /* ── Keyboard shortcut hint ───────────────────────────────── */
  .sd-kbd {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 16px; padding: 1px 5px;
    background: var(--sd-surface-overlay);
    border: 1px solid var(--sd-surface-border);
    border-bottom-width: 2px;
    border-radius: 3px;
    color: var(--sd-text-muted);
    font-family: var(--sd-font-mono);
    font-size: 10px;
    line-height: 1.2;
  }

  /* ── Tooltip (used by spindrel.ui.tooltip) ────────────────── */
  .sd-tooltip {
    position: absolute; z-index: 1001;
    padding: 4px 8px;
    background: var(--sd-surface);
    border: 1px solid var(--sd-surface-border);
    color: var(--sd-text);
    font-size: var(--sd-font-size-xs);
    border-radius: var(--sd-radius-sm);
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    pointer-events: none;
    max-width: 220px;
  }

  /* ── Modal (used by spindrel.ui.confirm) ──────────────────── */
  .sd-modal-backdrop {
    position: fixed; inset: 0; z-index: 999;
    background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center;
    padding: 16px;
  }
  .sd-modal {
    max-width: 360px; width: 100%;
    background: var(--sd-surface-raised);
    border: 1px solid var(--sd-surface-border);
    border-radius: var(--sd-radius-lg);
    padding: var(--sd-pad-md);
    display: flex; flex-direction: column; gap: var(--sd-gap-md);
    box-shadow: 0 12px 48px rgba(0,0,0,0.4);
  }
  .sd-modal__title { margin: 0; font-size: 14px; font-weight: 600; color: var(--sd-text); }
  .sd-modal__body { font-size: var(--sd-font-size-sm); color: var(--sd-text-muted); }
  .sd-modal__actions { display: flex; justify-content: flex-end; gap: var(--sd-gap-sm); }

  /* ── State modifiers ──────────────────────────────────────── */
  .sd-is-disabled,
  [aria-disabled="true"].sd-row,
  [aria-disabled="true"].sd-btn { opacity: 0.5; pointer-events: none; }
  .sd-is-loading { position: relative; pointer-events: none; color: transparent !important; }
  .sd-is-loading::after {
    content: "";
    position: absolute; top: 50%; left: 50%;
    width: 12px; height: 12px; margin: -6px 0 0 -6px;
    border: 2px solid var(--sd-text-muted);
    border-top-color: transparent;
    border-radius: 50%;
    animation: sd-spinner-rotate 700ms linear infinite;
  }

  /* ── Motion (respects reduced-motion) ─────────────────────── */
  @media (prefers-reduced-motion: no-preference) {
    @keyframes sd-fade-in {
      from { opacity: 0; transform: translateY(2px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes sd-pop {
      0%   { transform: scale(0.96); opacity: 0; }
      100% { transform: scale(1); opacity: 1; }
    }
    .sd-anim-fade-in { animation: sd-fade-in 180ms ease-out both; }
    .sd-anim-pop { animation: sd-pop 150ms ease-out both; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sd-check__mark, .sd-switch__thumb, .sd-radio__dot::after,
    .sd-anim-fade-in, .sd-anim-pop { transition: none !important; animation: none !important; }
  }
  ${isDark ? "" : "/* light mode active */"}
  `;
}

/**
 * JS-side theme object exposed at `window.spindrel.theme`. Used by
 * SVG/canvas widgets that need programmatic access to resolved color
 * values (charts, pulse animations, dynamic fills).
 */
export function buildWidgetThemeObject({ tokens: t, isDark }: WidgetThemeInput): Record<string, unknown> {
  return {
    isDark,
    surface: t.surface,
    surfaceRaised: t.surfaceRaised,
    surfaceOverlay: t.surfaceOverlay,
    surfaceBorder: t.surfaceBorder,
    text: t.text,
    textMuted: t.textMuted,
    textDim: t.textDim,
    accent: t.accent,
    accentHover: t.accentHover,
    accentMuted: t.accentMuted,
    success: t.success,
    warning: t.warning,
    danger: t.danger,
    purple: t.purple,
  };
}
