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
