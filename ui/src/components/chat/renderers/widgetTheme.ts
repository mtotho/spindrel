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

export interface WidgetThemeDefinition {
  ref?: string | null;
  name?: string | null;
  is_builtin?: boolean;
  light_tokens?: Partial<ThemeTokens> | null;
  dark_tokens?: Partial<ThemeTokens> | null;
  custom_css?: string | null;
}

export interface WidgetThemeInput {
  tokens: ThemeTokens;
  isDark: boolean;
  theme?: WidgetThemeDefinition | null;
}

export function resolveWidgetThemeTokens(
  theme: WidgetThemeDefinition | null | undefined,
  fallback: ThemeTokens,
  isDark: boolean,
): ThemeTokens {
  const overrides = (isDark ? theme?.dark_tokens : theme?.light_tokens) || {};
  return {
    ...fallback,
    ...overrides,
  };
}

/**
 * Build the full widget stylesheet string. Output goes into a `<style>`
 * block inside the iframe's `<head>`.
 */
export function buildWidgetThemeCss({ tokens: t, isDark, theme }: WidgetThemeInput): string {
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

    --sd-shadow-focus: 0 0 0 3px var(--sd-accent-subtle);

    --sd-radius-sm: 4px;
    --sd-radius-md: 6px;
    --sd-radius-lg: 8px;
    --sd-radius-xl: 10px;
    --sd-gap-xs: 4px;
    --sd-gap-sm: 8px;
    --sd-gap-md: 10px;
    --sd-gap-lg: 16px;
    --sd-gap-xl: 24px;
    --sd-pad-sm: 8px;
    --sd-pad-md: 12px;
    --sd-pad-lg: 14px;
    --sd-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --sd-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    --sd-font-size: 13px;
    --sd-font-size-sm: 12px;
    --sd-font-size-xs: 11px;
    --sd-line: 1.45;
    --sd-shell-pad-x: 0px;
    --sd-shell-pad-y: 0px;
    --sd-card-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-raised) 84%, transparent 16%)' : 'color-mix(in srgb, var(--sd-surface-raised) 92%, transparent 8%)'};
    --sd-card-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 54%, transparent 46%)' : 'color-mix(in srgb, var(--sd-surface-border) 56%, white 44%)'};
    --sd-card-shadow: none;
    --sd-subpanel-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-overlay) 68%, transparent 32%)' : 'color-mix(in srgb, var(--sd-surface-overlay) 76%, white 24%)'};
    --sd-subpanel-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 46%, transparent 54%)' : 'color-mix(in srgb, var(--sd-surface-border) 48%, white 52%)'};
    --sd-section-gap: 12px;
  }

  html[data-sd-host="inline"] {
    --sd-shell-pad-x: 0px;
    --sd-shell-pad-y: 0px;
  }
  html[data-sd-host="pinned"] {
    --sd-card-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-raised) 72%, transparent 28%)' : 'color-mix(in srgb, var(--sd-surface-raised) 82%, transparent 18%)'};
    --sd-card-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 40%, transparent 60%)' : 'color-mix(in srgb, var(--sd-surface-border) 42%, white 58%)'};
    --sd-subpanel-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-overlay) 60%, transparent 40%)' : 'color-mix(in srgb, var(--sd-surface-overlay) 68%, white 32%)'};
    --sd-subpanel-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 36%, transparent 64%)' : 'color-mix(in srgb, var(--sd-surface-border) 38%, white 62%)'};
  }
  html[data-sd-host-surface="surface"] {
    --sd-card-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-raised) 64%, transparent 36%)' : 'color-mix(in srgb, var(--sd-surface-raised) 76%, transparent 24%)'};
    --sd-card-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 32%, transparent 68%)' : 'color-mix(in srgb, var(--sd-surface-border) 36%, white 64%)'};
    --sd-card-shadow: none;
    --sd-subpanel-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-overlay) 54%, transparent 46%)' : 'color-mix(in srgb, var(--sd-surface-overlay) 62%, white 38%)'};
    --sd-subpanel-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 30%, transparent 70%)' : 'color-mix(in srgb, var(--sd-surface-border) 34%, white 66%)'};
  }
  html[data-sd-host-surface="translucent"] {
    --sd-card-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-raised) 44%, transparent 56%)' : 'color-mix(in srgb, var(--sd-surface-raised) 52%, transparent 48%)'};
    --sd-card-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 24%, transparent 76%)' : 'color-mix(in srgb, var(--sd-surface-border) 28%, white 72%)'};
    --sd-card-shadow: none;
    --sd-subpanel-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-overlay) 42%, transparent 58%)' : 'color-mix(in srgb, var(--sd-surface-overlay) 50%, white 50%)'};
    --sd-subpanel-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 22%, transparent 78%)' : 'color-mix(in srgb, var(--sd-surface-border) 26%, white 74%)'};
  }
  html[data-sd-host-surface="plain"] {
    --sd-card-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-raised) 88%, transparent 12%)' : 'color-mix(in srgb, var(--sd-surface-raised) 96%, transparent 4%)'};
    --sd-card-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 58%, transparent 42%)' : 'color-mix(in srgb, var(--sd-surface-border) 60%, white 40%)'};
    --sd-subpanel-bg: ${isDark ? 'color-mix(in srgb, var(--sd-surface-overlay) 72%, transparent 28%)' : 'color-mix(in srgb, var(--sd-surface-overlay) 80%, white 20%)'};
    --sd-subpanel-border: ${isDark ? 'color-mix(in srgb, var(--sd-surface-border) 52%, transparent 48%)' : 'color-mix(in srgb, var(--sd-surface-border) 54%, white 46%)'};
  }
  html[data-sd-layout="grid"],
  html[data-sd-layout="rail"],
  html[data-sd-layout="dock"] {
    --sd-shell-pad-x: 0px;
    --sd-shell-pad-y: 0px;
  }
  html[data-sd-layout="chip"] {
    --sd-shell-pad-x: 0px;
    --sd-shell-pad-y: 0px;
    --sd-gap-md: 8px;
    --sd-gap-sm: 6px;
  }

  /* ── Reset + body ─────────────────────────────────────────── */
  html, body {
    margin: 0;
    padding: 0;
    font-family: var(--sd-font-sans);
    font-size: var(--sd-font-size);
    line-height: var(--sd-line);
    color: var(--sd-text);
    background: transparent;
  }
  /* The host owns the outer tile shell. Widgets render inside it and opt into
     an inner panel with .sd-card only when they need stronger grouping. */
  body {
    padding: var(--sd-shell-pad-y) var(--sd-shell-pad-x);
    overflow-y: auto;
  }
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
  html[data-hover-scrollbars="1"],
  html[data-hover-scrollbars="1"] body,
  html[data-hover-scrollbars="1"] * {
    scrollbar-width: none;
    scrollbar-color: transparent transparent;
    transition: scrollbar-color 200ms ease;
  }
  html[data-hover-scrollbars="1"]:hover,
  html[data-hover-scrollbars="1"]:focus-within,
  html[data-hover-scrollbars="1"]:hover body,
  html[data-hover-scrollbars="1"]:focus-within body,
  html[data-hover-scrollbars="1"]:hover *,
  html[data-hover-scrollbars="1"]:focus-within * {
    scrollbar-width: thin;
    scrollbar-color: var(--sd-surface-border) transparent;
  }
  html[data-hover-scrollbars="1"]::-webkit-scrollbar,
  html[data-hover-scrollbars="1"] body::-webkit-scrollbar,
  html[data-hover-scrollbars="1"] *::-webkit-scrollbar {
    display: none;
    width: 0;
    height: 0;
  }
  html[data-hover-scrollbars="1"]::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"] body::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"] *::-webkit-scrollbar-thumb {
    background: transparent;
    transition: background-color 200ms ease;
  }
  html[data-hover-scrollbars="1"]:hover::-webkit-scrollbar,
  html[data-hover-scrollbars="1"]:focus-within::-webkit-scrollbar,
  html[data-hover-scrollbars="1"]:hover body::-webkit-scrollbar,
  html[data-hover-scrollbars="1"]:focus-within body::-webkit-scrollbar,
  html[data-hover-scrollbars="1"]:hover *::-webkit-scrollbar,
  html[data-hover-scrollbars="1"]:focus-within *::-webkit-scrollbar {
    display: initial;
    width: 6px;
    height: 6px;
  }
  html[data-hover-scrollbars="1"]:hover::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"]:focus-within::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"]:hover body::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"]:focus-within body::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"]:hover *::-webkit-scrollbar-thumb,
  html[data-hover-scrollbars="1"]:focus-within *::-webkit-scrollbar-thumb {
    background: var(--sd-surface-border);
  }
  html[data-hover-scrollbars="1"]::-webkit-scrollbar-thumb:hover,
  html[data-hover-scrollbars="1"] body::-webkit-scrollbar-thumb:hover,
  html[data-hover-scrollbars="1"] *::-webkit-scrollbar-thumb:hover {
    background: var(--sd-text-dim);
  }

  /* ── Root wrapper (measured by host for iframe auto-sizing) ─ */
  #__sd_root {
    display: flex;
    flex-direction: column;
    gap: var(--sd-gap-md);
    min-height: 100%;
  }
  #__sd_root[data-sd-layout="chip"] { gap: var(--sd-gap-sm); }

  /* ── Layout ───────────────────────────────────────────────── */
  .sd-stack,
  .sd-stack-sm,
  .sd-stack-lg { display: flex; flex-direction: column; }
  .sd-stack { gap: var(--sd-gap-md); }
  .sd-stack-sm { gap: var(--sd-gap-sm); }
  .sd-stack-lg { gap: var(--sd-gap-lg); }
  .sd-hstack,
  .sd-hstack-sm,
  .sd-hstack-lg { display: flex; flex-direction: row; align-items: center; flex-wrap: wrap; }
  .sd-hstack { gap: var(--sd-gap-md); }
  .sd-hstack-sm { gap: var(--sd-gap-sm); }
  .sd-hstack-lg { gap: var(--sd-gap-lg); }
  .sd-hstack-between { justify-content: space-between; }
  .sd-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--sd-gap-md); }
  .sd-grid-2 { grid-template-columns: repeat(2, 1fr); }
  .sd-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: var(--sd-gap-sm); }
  .sd-spacer { flex: 1; }

  /* ── Typography ───────────────────────────────────────────── */
  .sd-title { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: -0.01em; color: var(--sd-text); line-height: 1.2; }
  .sd-subtitle { margin: 0; font-size: var(--sd-font-size-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--sd-text-muted); }
  .sd-meta { font-size: var(--sd-font-size-sm); color: var(--sd-text-muted); line-height: 1.45; }
  .sd-label { margin: 0; font-size: var(--sd-font-size-xs); font-weight: 650; text-transform: uppercase; letter-spacing: 0.08em; color: var(--sd-text-muted); }
  .sd-muted { color: var(--sd-text-muted); }
  .sd-dim { color: var(--sd-text-dim); }
  .sd-mono { font-family: var(--sd-font-mono); font-size: 12px; }

  /* ── Surfaces ─────────────────────────────────────────────── */
  .sd-card {
    background: var(--sd-card-bg);
    border: 1px solid var(--sd-card-border);
    box-shadow: var(--sd-card-shadow);
    border-radius: var(--sd-radius-xl);
    padding: var(--sd-pad-md);
    display: flex;
    flex-direction: column;
    gap: var(--sd-section-gap);
  }
  .sd-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sd-gap-sm); }
  .sd-card-body { display: flex; flex-direction: column; gap: var(--sd-section-gap); }
  .sd-card-actions { display: flex; flex-direction: row; gap: var(--sd-gap-sm); flex-wrap: wrap; }
  .sd-card.sd-card-flat,
  .sd-card--flat {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
    padding: 0;
    border-radius: 0;
  }
  .sd-tile,
  .sd-subcard {
    background: var(--sd-subpanel-bg);
    border: 1px solid var(--sd-subpanel-border);
    border-radius: var(--sd-radius-md);
    padding: var(--sd-pad-sm);
    display: flex;
    flex-direction: column;
    gap: var(--sd-gap-xs);
  }
  /* Sensible default for stacked inset panels in the most common authoring
     shape: multiple sub-panels placed directly inside a card body. This avoids
     visually merged tiles without changing grid/row layouts or nested stacks. */
  .sd-card-body > .sd-tile + .sd-tile,
  .sd-card-body > .sd-subcard + .sd-subcard {
    margin-top: var(--sd-gap-sm);
  }
  .sd-frame { position: relative; border-radius: var(--sd-radius-md); overflow: hidden; background: var(--sd-surface-overlay); }
  .sd-frame-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--sd-text-muted); font-size: var(--sd-font-size-sm); }

  /* ── Controls ─────────────────────────────────────────────────
     Button contract (matches docs/guides/ui-design.md §4):
     - .sd-btn        — default ghost control. Transparent, muted text, tonal hover.
                        Use for routine row actions (refresh, edit, close, cancel).
     - .sd-btn-accent — ghost tinted primary. Use for the primary action of a row
                        or card ("Connect", "Retry", "Open"). Accent text on accent/10 hover.
     - .sd-btn-primary — filled accent. RESERVED for the one final-commit moment per
                         screen (confirm dialog OK, save-and-close). Do not use for
                         routine row actions — that's the Bootstrap-button anti-pattern.
     - .sd-btn-subtle — explicit secondary ghost alias (same as .sd-btn today). Kept
                        for readability when multiple ghost buttons sit side-by-side.
     - .sd-btn-danger — ghost destructive. Danger text, danger/10 hover.
     Never combine border + bg-color + shadow on one button.
     ────────────────────────────────────────────────────────────── */
  .sd-btn {
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--sd-gap-xs);
    min-height: 30px;
    padding: 6px 10px;
    border: 1px solid transparent;
    background: transparent;
    color: var(--sd-text-muted);
    border-radius: var(--sd-radius-md);
    font-size: var(--sd-font-size-sm);
    font-weight: 500;
    letter-spacing: 0.01em;
    font-family: inherit;
    cursor: pointer;
    transition: background 140ms ease, color 140ms ease, opacity 140ms ease;
  }
  .sd-btn:hover {
    background: color-mix(in srgb, var(--sd-surface-overlay) 60%, transparent 40%);
    color: var(--sd-text);
  }
  .sd-btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .sd-btn[aria-pressed="true"] {
    background: var(--sd-accent-subtle);
    color: var(--sd-accent);
  }
  .sd-btn[aria-pressed="true"]:hover {
    background: color-mix(in srgb, var(--sd-accent) 14%, transparent 86%);
    color: var(--sd-accent);
  }
  .sd-btn-accent {
    background: transparent;
    border-color: transparent;
    color: var(--sd-accent);
  }
  .sd-btn-accent:hover {
    background: color-mix(in srgb, var(--sd-accent) 10%, transparent 90%);
    color: var(--sd-accent-hover);
  }
  .sd-btn-primary {
    background: var(--sd-accent);
    border-color: var(--sd-accent);
    color: white;
    font-weight: 600;
  }
  .sd-btn-primary:hover { background: var(--sd-accent-hover); border-color: var(--sd-accent-hover); color: white; }
  .sd-btn-subtle {
    background: transparent;
    border-color: transparent;
    color: var(--sd-text-muted);
  }
  .sd-btn-subtle:hover {
    background: color-mix(in srgb, var(--sd-surface-overlay) 60%, transparent 40%);
    color: var(--sd-text);
  }
  .sd-btn-danger {
    background: transparent;
    border-color: transparent;
    color: var(--sd-danger);
  }
  .sd-btn-danger:hover {
    background: color-mix(in srgb, var(--sd-danger) 12%, transparent 88%);
    color: var(--sd-danger);
  }

  .sd-input, .sd-select, .sd-textarea {
    appearance: none;
    width: 100%;
    padding: 8px 10px;
    border: 1px solid color-mix(in srgb, var(--sd-input-border) 72%, transparent 28%);
    background: color-mix(in srgb, var(--sd-input-bg) 90%, transparent 10%);
    color: var(--sd-text);
    border-radius: var(--sd-radius-md);
    font-size: var(--sd-font-size-sm);
    font-family: inherit;
    outline: none;
    transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
  }
  .sd-input::placeholder, .sd-textarea::placeholder { color: color-mix(in srgb, var(--sd-text-dim) 84%, transparent 16%); }
  .sd-input:hover, .sd-select:hover, .sd-textarea:hover { border-color: var(--sd-surface-border); }
  .sd-input:focus, .sd-select:focus, .sd-textarea:focus {
    border-color: var(--sd-accent);
    box-shadow: var(--sd-shadow-focus);
    background: var(--sd-input-bg);
  }

  /* ── Status chips ─────────────────────────────────────────── */
  .sd-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: var(--sd-font-size-xs);
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
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
  .sd-empty {
    color: var(--sd-text-muted);
    font-size: var(--sd-font-size-sm);
    padding: var(--sd-pad-lg) var(--sd-pad-md);
    text-align: center;
    border: 1px dashed color-mix(in srgb, var(--sd-surface-border) 60%, transparent 40%);
    border-radius: var(--sd-radius-md);
    background: color-mix(in srgb, var(--sd-overlay-light) 48%, transparent 52%);
  }
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
    outline-offset: 2px;
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
    border: 1.5px solid color-mix(in srgb, var(--sd-surface-border) 80%, transparent 20%);
    background: var(--sd-input-bg);
    border-radius: var(--sd-radius-sm);
    transition: background 120ms, border-color 120ms, box-shadow 120ms;
    flex: 0 0 auto;
  }
  .sd-check:hover .sd-check__box { box-shadow: 0 0 0 2px var(--sd-accent-subtle); }
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
    background: color-mix(in srgb, var(--sd-input-bg) 90%, transparent 10%);
    border: 1px solid color-mix(in srgb, var(--sd-input-border) 72%, transparent 28%);
    border-radius: var(--sd-radius-md);
    transition: border-color 120ms, box-shadow 120ms;
    min-height: 38px;
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
    padding: 8px 10px;
    font-size: var(--sd-font-size);
  }
  .sd-input-group__icon {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 0 2px 0 10px;
    color: var(--sd-text-muted);
    width: auto; height: auto;
  }
  .sd-input-group__action {
    margin: 3px; padding: 6px 10px;
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
  .sd-textarea {
    resize: vertical;
    min-height: 88px;
    padding: 9px 10px;
    line-height: 1.55;
    white-space: pre-wrap;
  }
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
    padding: 7px 8px;
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
  .sd-section__title { font-size: var(--sd-font-size-xs); font-weight: 650; text-transform: uppercase; letter-spacing: 0.1em; color: var(--sd-text-muted); }
  .sd-inline { display: inline-flex; align-items: center; gap: var(--sd-gap-xs); }

  /* ── Tags (removable chip extension) ──────────────────────── */
  .sd-tag {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 8px;
    border-radius: var(--sd-radius-sm);
    background: color-mix(in srgb, var(--sd-overlay-light) 72%, transparent 28%);
    color: var(--sd-text);
    font-size: var(--sd-font-size-sm);
    font-weight: 600;
    border: 1px solid transparent;
    line-height: 1.35;
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
    box-shadow: 0 4px 12px rgba(0,0,0,0.12);
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
    padding: 4px 7px;
    background: var(--sd-surface);
    border: 1px solid var(--sd-surface-border);
    color: var(--sd-text);
    font-size: var(--sd-font-size-xs);
    border-radius: var(--sd-radius-sm);
    box-shadow: 0 3px 10px rgba(0,0,0,0.1);
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
    border-radius: var(--sd-radius-xl);
    padding: var(--sd-pad-md);
    display: flex; flex-direction: column; gap: var(--sd-gap-md);
    box-shadow: 0 6px 20px rgba(0,0,0,0.18);
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
  /* Defense-in-depth: some widget bundles inject a later generic
     body padding rule. Use a more specific selector plus
     !important so the iframe body stays flush and widgets opt into spacing
     explicitly via sd-card / sd-stack / local CSS instead. */
  html[data-sd-host] body[data-sd-host][data-sd-layout] { padding: 0 !important; }
  ${theme?.custom_css?.trim() ? `\n  /* theme custom css */\n${theme.custom_css.trim()}\n` : ""}
  ${isDark ? "" : "/* light mode active */"}
  `;
}

/**
 * JS-side theme object exposed at `window.spindrel.theme`. Used by
 * SVG/canvas widgets that need programmatic access to resolved color
 * values (charts, pulse animations, dynamic fills).
 */
export function buildWidgetThemeObject({ tokens: t, isDark, theme }: WidgetThemeInput): Record<string, unknown> {
  return {
    isDark,
    themeRef: theme?.ref ?? "builtin/default",
    themeName: theme?.name ?? "Default",
    isBuiltin: theme?.is_builtin ?? true,
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
