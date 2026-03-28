/**
 * Resolved hex color tokens for inline styles on raw HTML elements.
 * Components using Tailwind classes (via NativeWind) get theme-awareness
 * automatically from CSS variables. This hook is for `<div style={{...}}>`,
 * `<input>`, `<textarea>`, `<button>`, etc.
 */
import { useThemeStore } from "../stores/theme";

export interface ThemeTokens {
  // Surfaces
  surface: string;
  surfaceRaised: string;
  surfaceOverlay: string;
  surfaceBorder: string;
  // Text
  text: string;
  textMuted: string;
  textDim: string;
  // Accent
  accent: string;
  accentHover: string;
  accentMuted: string;
  // Semantic
  inputBg: string;
  inputBorder: string;
  inputText: string;
  inputBorderFocus: string;
  codeBg: string;
  codeBorder: string;
  codeText: string;
  linkColor: string;
  contentText: string;
  // Overlays (rgba)
  overlayLight: string;
  overlayBorder: string;
  skeletonBg: string;
}

const DARK: ThemeTokens = {
  surface: "#111111",
  surfaceRaised: "#1a1a1a",
  surfaceOverlay: "#222222",
  surfaceBorder: "#333333",
  text: "#e5e5e5",
  textMuted: "#999999",
  textDim: "#666666",
  accent: "#3b82f6",
  accentHover: "#2563eb",
  accentMuted: "#1e3a5f",
  inputBg: "#111111",
  inputBorder: "#333333",
  inputText: "#e5e5e5",
  inputBorderFocus: "#3b82f6",
  codeBg: "#1a1a1e",
  codeBorder: "rgba(255,255,255,0.06)",
  codeText: "#e06c75",
  linkColor: "#5b9bd5",
  contentText: "#d1d5db",
  overlayLight: "rgba(255,255,255,0.06)",
  overlayBorder: "rgba(255,255,255,0.08)",
  skeletonBg: "rgba(255,255,255,0.04)",
};

const LIGHT: ThemeTokens = {
  surface: "#fafafa",
  surfaceRaised: "#ffffff",
  surfaceOverlay: "#f3f4f6",
  surfaceBorder: "#e5e7eb",
  text: "#171717",
  textMuted: "#737373",
  textDim: "#a3a3a3",
  accent: "#3b82f6",
  accentHover: "#2563eb",
  accentMuted: "#dbeafe",
  inputBg: "#ffffff",
  inputBorder: "#d1d5db",
  inputText: "#171717",
  inputBorderFocus: "#3b82f6",
  codeBg: "#f3f4f6",
  codeBorder: "rgba(0,0,0,0.08)",
  codeText: "#c7254e",
  linkColor: "#2563eb",
  contentText: "#374151",
  overlayLight: "rgba(0,0,0,0.04)",
  overlayBorder: "rgba(0,0,0,0.08)",
  skeletonBg: "rgba(0,0,0,0.04)",
};

export function useThemeTokens(): ThemeTokens {
  const mode = useThemeStore((s) => s.mode);
  return mode === "dark" ? DARK : LIGHT;
}
