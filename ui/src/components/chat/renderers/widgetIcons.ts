/**
 * Inline SVG icon sprite for widgets.
 *
 * Curated subset of Lucide (https://lucide.dev, MIT) traced by hand as a
 * single `<svg>` containing `<symbol>` per icon. Injected once per widget
 * iframe at the top of `<body>` so widgets can reference icons via
 *
 *   <svg class="sd-icon"><use href="#sd-icon-check"/></svg>
 *
 * or programmatically:
 *
 *   element.innerHTML = window.spindrel.ui.icon("check");
 *
 * All symbols share the same attributes (24×24 viewBox, currentColor
 * stroke, width 2, round caps/joins, no fill) so the wrapper `<svg class="sd-icon">`
 * sets rendering style once via CSS.
 *
 * Adding an icon: drop a `<symbol id="sd-icon-<name>">` block below with
 * the raw path data from lucide.dev. Keep the list trimmed — every icon
 * ships in every iframe.
 */

export const WIDGET_ICON_NAMES = [
  "check",
  "x",
  "plus",
  "minus",
  "trash",
  "pencil",
  "search",
  "filter",
  "chevron-up",
  "chevron-down",
  "chevron-left",
  "chevron-right",
  "arrow-up",
  "arrow-down",
  "arrow-left",
  "arrow-right",
  "more-horizontal",
  "more-vertical",
  "calendar",
  "clock",
  "bell",
  "user",
  "users",
  "mail",
  "file",
  "folder",
  "link",
  "external-link",
  "settings",
  "eye",
  "eye-off",
  "refresh",
  "play",
  "pause",
  "star",
  "heart",
  "tag",
  "pin",
  "check-circle",
  "alert-circle",
  "info",
  "alert-triangle",
  "loader",
  "list",
  "grid",
  "home",
  "inbox",
  "send",
  "download",
  "upload",
  "sun",
  "moon",
  "copy",
  "save",
  "bookmark",
  "flag",
  "lock",
  "unlock",
  "zap",
  "chart-bar",
] as const;

export type WidgetIconName = (typeof WIDGET_ICON_NAMES)[number];

/**
 * The sprite body. Emitted inside a `<svg style="display:none">` wrapper
 * so browsers parse every `<symbol>` as referenceable without painting them.
 * Wrapper attributes (stroke, fill, width) propagate to each `<symbol>` via
 * the shared SVG attribute inheritance model — individual symbols only need
 * path data.
 */
const SPRITE_SYMBOLS: Record<WidgetIconName, string> = {
  "check": `<path d="M20 6 9 17l-5-5"/>`,
  "x": `<path d="M18 6 6 18"/><path d="m6 6 12 12"/>`,
  "plus": `<path d="M12 5v14"/><path d="M5 12h14"/>`,
  "minus": `<path d="M5 12h14"/>`,
  "trash": `<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6"/><path d="M14 11v6"/>`,
  "pencil": `<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>`,
  "search": `<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>`,
  "filter": `<path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3Z"/>`,
  "chevron-up": `<path d="m18 15-6-6-6 6"/>`,
  "chevron-down": `<path d="m6 9 6 6 6-6"/>`,
  "chevron-left": `<path d="m15 18-6-6 6-6"/>`,
  "chevron-right": `<path d="m9 18 6-6-6-6"/>`,
  "arrow-up": `<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>`,
  "arrow-down": `<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>`,
  "arrow-left": `<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>`,
  "arrow-right": `<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>`,
  "more-horizontal": `<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>`,
  "more-vertical": `<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>`,
  "calendar": `<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>`,
  "clock": `<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>`,
  "bell": `<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>`,
  "user": `<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>`,
  "users": `<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>`,
  "mail": `<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/>`,
  "file": `<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5Z"/><path d="M14 2v6h6"/>`,
  "folder": `<path d="M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3a2 2 0 0 1 1.7.9l.8 1.2a2 2 0 0 0 1.7.9H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2Z"/>`,
  "link": `<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>`,
  "external-link": `<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>`,
  "settings": `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>`,
  "eye": `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/>`,
  "eye-off": `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/>`,
  "refresh": `<path d="M21 12a9 9 0 0 0-15-6.7L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 15 6.7l3-2.7"/><path d="M21 21v-5h-5"/>`,
  "play": `<polygon points="5 3 19 12 5 21 5 3"/>`,
  "pause": `<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>`,
  "star": `<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"/>`,
  "heart": `<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78Z"/>`,
  "tag": `<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82Z"/><circle cx="7" cy="7" r="1"/>`,
  "pin": `<path d="M12 17v5"/><path d="M9 10.76A2 2 0 0 1 10 9V4h4v5a2 2 0 0 1 1 1.76l.59.85A2 2 0 0 1 16 13v1H8v-1a2 2 0 0 1 .41-1.39Z"/>`,
  "check-circle": `<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>`,
  "alert-circle": `<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>`,
  "info": `<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>`,
  "alert-triangle": `<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>`,
  "loader": `<path d="M12 2v4"/><path d="M12 18v4"/><path d="m4.93 4.93 2.83 2.83"/><path d="m16.24 16.24 2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/><path d="m4.93 19.07 2.83-2.83"/><path d="m16.24 7.76 2.83-2.83"/>`,
  "list": `<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>`,
  "grid": `<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>`,
  "home": `<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2h-4v-9H10v9H5a2 2 0 0 1-2-2Z"/>`,
  "inbox": `<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>`,
  "send": `<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>`,
  "download": `<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>`,
  "upload": `<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>`,
  "sun": `<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m4.93 19.07 1.41-1.41"/><path d="m17.66 6.34 1.41-1.41"/>`,
  "moon": `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/>`,
  "copy": `<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>`,
  "save": `<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>`,
  "bookmark": `<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z"/>`,
  "flag": `<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1Z"/><path d="M4 22V15"/>`,
  "lock": `<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>`,
  "unlock": `<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>`,
  "zap": `<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>`,
  "chart-bar": `<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>`,
};

function buildSprite(): string {
  const symbols = WIDGET_ICON_NAMES.map((name) => {
    const body = SPRITE_SYMBOLS[name];
    return `<symbol id="sd-icon-${name}" viewBox="0 0 24 24">${body}</symbol>`;
  }).join("");
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" style="display:none" ` +
    `aria-hidden="true" focusable="false" ` +
    `fill="none" stroke="currentColor" stroke-width="2" ` +
    `stroke-linecap="round" stroke-linejoin="round">` +
    symbols +
    `</svg>`
  );
}

/**
 * The full sprite markup to embed in the widget iframe `<body>`.
 * Safe to inline multiple times (IDs are scoped to the iframe document).
 */
export const WIDGET_ICON_SPRITE: string = buildSprite();
