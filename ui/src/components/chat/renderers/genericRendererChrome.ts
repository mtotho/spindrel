import type { CSSProperties } from "react";
import type { ThemeTokens } from "../../../theme/tokens";

export type RichRendererVariant = "default-chat" | "terminal-chat" | "dashboard";
export type RichRendererChromeMode = "standalone" | "embedded";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

export function resolveCodeShell({
  t,
  rendererVariant = "default-chat",
  chromeMode = "standalone",
}: {
  t: ThemeTokens;
  rendererVariant?: RichRendererVariant;
  chromeMode?: RichRendererChromeMode;
}): CSSProperties {
  const isTerminal = rendererVariant === "terminal-chat";
  const isEmbedded = chromeMode === "embedded";
  return {
    margin: 0,
    padding: isEmbedded
      ? (isTerminal ? "0" : "0")
      : "8px 12px",
    borderRadius: isEmbedded ? 0 : 8,
    background: isEmbedded ? "transparent" : t.codeBg,
    border: isEmbedded ? "none" : `1px solid ${t.codeBorder ?? t.surfaceBorder}`,
    fontFamily: TERMINAL_FONT_STACK,
    fontSize: 12,
    lineHeight: isTerminal ? 1.5 : 1.5,
    color: t.contentText,
    maxHeight: 400,
    overflowY: isTerminal ? "hidden" : "auto",
  };
}

export function resolveSurfaceShell({
  t,
  rendererVariant = "default-chat",
  chromeMode = "standalone",
}: {
  t: ThemeTokens;
  rendererVariant?: RichRendererVariant;
  chromeMode?: RichRendererChromeMode;
}): CSSProperties {
  const isTerminal = rendererVariant === "terminal-chat";
  const isEmbedded = chromeMode === "embedded";
  return {
    border: isEmbedded ? "none" : `1px solid ${t.surfaceBorder}`,
    borderRadius: isEmbedded ? 0 : 8,
    background: isEmbedded ? "transparent" : t.codeBg,
    fontFamily: TERMINAL_FONT_STACK,
    fontSize: 12,
    lineHeight: isTerminal ? 1.5 : 1.5,
    color: t.contentText,
    maxHeight: 400,
    overflowY: isTerminal ? "hidden" : "auto",
  };
}
