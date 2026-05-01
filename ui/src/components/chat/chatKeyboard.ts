type KeyboardTargetLike = {
  tagName?: string;
  isContentEditable?: boolean;
  closest?: (selector: string) => unknown;
};

export type ChatShortcutId =
  | "switchSessions"
  | "commandPalette"
  | "openSlashCommands"
  | "focusLayout"
  | "browseFiles"
  | "toggleWorkbench"
  | "closeActiveTab"
  | "showKeyboardHelp";

type KeyboardShortcutLike = {
  key?: string;
  code?: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  repeat?: boolean;
};

export const CHAT_SHORTCUTS: Record<ChatShortcutId, { mac: string; win: string; label: string }> = {
  switchSessions: {
    mac: "⌘⌥S",
    win: "Ctrl+Alt+S",
    label: "Switch sessions",
  },
  commandPalette: {
    mac: "⌘K",
    win: "Ctrl+K",
    label: "Command palette",
  },
  openSlashCommands: {
    mac: "/",
    win: "/",
    label: "Slash commands",
  },
  focusLayout: {
    mac: "⌘⌥B",
    win: "Ctrl+Alt+B",
    label: "Focus chat panes",
  },
  browseFiles: {
    mac: "⌘⇧B",
    win: "Ctrl+Shift+B",
    label: "Browse files",
  },
  toggleWorkbench: {
    mac: "⌘B",
    win: "Ctrl+B",
    label: "Toggle workbench",
  },
  closeActiveTab: {
    mac: "⌘W",
    win: "Ctrl+W",
    label: "Close active tab",
  },
  showKeyboardHelp: {
    mac: "?",
    win: "?",
    label: "Keyboard shortcuts",
  },
};

export function isEditableKeyboardTarget(target: EventTarget | KeyboardTargetLike | null | undefined): boolean {
  const el = target as KeyboardTargetLike | null | undefined;
  const tag = typeof el?.tagName === "string" ? el.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el?.isContentEditable) return true;
  return !!el?.closest?.('[contenteditable="true"], [role="textbox"]');
}

export function isApplePlatform(userAgent?: string): boolean {
  const source = userAgent ?? (typeof navigator !== "undefined" ? navigator.userAgent : "");
  return /Mac|iPhone|iPad/.test(source);
}

export function getChatShortcutLabel(id: ChatShortcutId, userAgent?: string): string {
  const shortcut = CHAT_SHORTCUTS[id];
  return isApplePlatform(userAgent) ? shortcut.mac : shortcut.win;
}

export function isSwitchSessionsShortcut(event: KeyboardShortcutLike): boolean {
  if (event.repeat) return false;
  const key = typeof event.key === "string" ? event.key.toLowerCase() : "";
  return (event.metaKey || event.ctrlKey) === true
    && event.altKey === true
    && event.shiftKey !== true
    && key === "s";
}

export function isKeyboardHelpShortcut(event: KeyboardShortcutLike): boolean {
  if (event.repeat) return false;
  return event.key === "?"
    && event.metaKey !== true
    && event.ctrlKey !== true
    && event.altKey !== true;
}

export function isCloseActiveChatTabShortcut(event: KeyboardShortcutLike): boolean {
  if (event.repeat) return false;
  const key = typeof event.key === "string" ? event.key.toLowerCase() : "";
  return (event.metaKey || event.ctrlKey) === true
    && event.altKey !== true
    && event.shiftKey !== true
    && key === "w";
}
