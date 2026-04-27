import test from "node:test";
import assert from "node:assert/strict";
import { buildWidgetThemeCss } from "./widgetTheme.js";
const TOKENS = {
    surface: "#111111",
    surfaceRaised: "#171717",
    surfaceOverlay: "#1f1f1f",
    surfaceBorder: "#333333",
    text: "#eeeeee",
    textMuted: "#aaaaaa",
    textDim: "#777777",
    accent: "#3b82f6",
    accentHover: "#2563eb",
    accentMuted: "#1e3a5f",
    accentSubtle: "rgba(59,130,246,0.08)",
    accentBorder: "rgba(59,130,246,0.2)",
    danger: "#ef4444",
    dangerMuted: "#f87171",
    dangerSubtle: "rgba(239,68,68,0.08)",
    dangerBorder: "rgba(239,68,68,0.15)",
    success: "#22c55e",
    successSubtle: "rgba(34,197,94,0.08)",
    successBorder: "rgba(34,197,94,0.2)",
    warning: "#eab308",
    warningSubtle: "rgba(234,179,8,0.08)",
    warningMuted: "#d97706",
    warningBorder: "rgba(234,179,8,0.2)",
    purple: "#a855f7",
    purpleMuted: "#c084fc",
    purpleSubtle: "rgba(168,85,247,0.08)",
    purpleBorder: "rgba(168,85,247,0.15)",
    inputBg: "#101010",
    inputBorder: "#3a3a3a",
    inputText: "#eeeeee",
    inputBorderFocus: "#3b82f6",
    codeBg: "#181818",
    codeBorder: "rgba(255,255,255,0.06)",
    codeText: "#e06c75",
    linkColor: "#5b9bd5",
    contentText: "#d1d5db",
    botMessageBg: "rgba(168,85,247,0.04)",
    overlayLight: "rgba(255,255,255,0.06)",
    overlayBorder: "rgba(255,255,255,0.08)",
    skeletonBg: "rgba(255,255,255,0.04)",
};
function renderCss() {
    return buildWidgetThemeCss({
        tokens: TOKENS,
        isDark: true,
        theme: null,
    });
}
test("widget theme emits the tighter low-chrome radius scale", () => {
    const css = renderCss();
    assert.match(css, /--sd-radius-sm: 4px;/);
    assert.match(css, /--sd-radius-md: 6px;/);
    assert.match(css, /--sd-radius-lg: 8px;/);
    assert.match(css, /--sd-radius-xl: 10px;/);
});
test("widget theme keeps buttons and inputs on the shared compact radius", () => {
    const css = renderCss();
    assert.match(css, /\.sd-btn \{[\s\S]*?border-radius: var\(--sd-radius-md\);/);
    assert.match(css, /\.sd-input, \.sd-select, \.sd-textarea \{[\s\S]*?border-radius: var\(--sd-radius-md\);/);
    assert.match(css, /\.sd-input-group \{[\s\S]*?border-radius: var\(--sd-radius-md\);/);
});
test("widget theme uses rectangular chips and tags instead of pill defaults", () => {
    const css = renderCss();
    assert.match(css, /\.sd-chip \{[\s\S]*?border-radius: var\(--sd-radius-sm\);/);
    assert.match(css, /\.sd-tag \{[\s\S]*?border-radius: var\(--sd-radius-sm\);/);
});
test("widget theme quiets inner panels when the host already owns the surface", () => {
    const css = renderCss();
    assert.match(css, /html\[data-sd-host-surface="surface"\] \{[\s\S]*?--sd-card-shadow: none;/);
    assert.match(css, /html\[data-sd-host-surface="surface"\] \{[\s\S]*?--sd-subpanel-border:/);
    assert.match(css, /html\[data-sd-host-surface="plain"\] \{/);
});
