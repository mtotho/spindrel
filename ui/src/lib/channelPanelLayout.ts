export type ChannelPanelMode = "closed" | "push" | "overlay";

export type ChannelLayoutMode =
  | "full"
  | "rail-header-chat"
  | "rail-chat"
  | "dashboard-only";

export const CHANNEL_PANEL_DEFAULT_WIDTH = 320;
export const CHANNEL_PANEL_MIN_WIDTH = 240;
export const CHANNEL_PANEL_MAX_WIDTH = 720;
export const CHANNEL_CHAT_MIN_WIDTH = 760;

export interface ChannelPanelLayoutInput {
  availableWidth: number;
  isMobile: boolean;
  layoutMode: ChannelLayoutMode;
  hasLeftPanel: boolean;
  hasRightPanel: boolean;
  leftOpen: boolean;
  rightOpen: boolean;
  leftPinned: boolean;
  rightPinned: boolean;
  leftWidth: number;
  rightWidth: number;
  chatMinWidth?: number;
}

export interface ChannelPanelLayout {
  left: { mode: ChannelPanelMode; width: number };
  right: { mode: ChannelPanelMode; width: number };
  chatWidth: number;
}

export function clampChannelPanelWidth(
  width: number,
  maxWidth: number = CHANNEL_PANEL_MAX_WIDTH,
): number {
  if (!Number.isFinite(width)) return CHANNEL_PANEL_DEFAULT_WIDTH;
  return Math.max(
    CHANNEL_PANEL_MIN_WIDTH,
    Math.min(maxWidth, Math.round(width)),
  );
}

function fitsPush(
  availableWidth: number,
  chatMinWidth: number,
  leftMode: ChannelPanelMode,
  leftWidth: number,
  rightMode: ChannelPanelMode,
  rightWidth: number,
): boolean {
  const used =
    (leftMode === "push" ? leftWidth : 0)
    + (rightMode === "push" ? rightWidth : 0);
  return availableWidth - used >= chatMinWidth;
}

export function resolveChannelPanelLayout(input: ChannelPanelLayoutInput): ChannelPanelLayout {
  const chatMinWidth = input.chatMinWidth ?? CHANNEL_CHAT_MIN_WIDTH;
  const leftWidth = clampChannelPanelWidth(input.leftWidth);
  const rightWidth = clampChannelPanelWidth(input.rightWidth);

  if (input.isMobile || input.layoutMode === "dashboard-only") {
    return {
      left: { mode: "closed", width: leftWidth },
      right: { mode: "closed", width: rightWidth },
      chatWidth: input.availableWidth,
    };
  }

  const leftAllowed = input.hasLeftPanel;
  const rightAllowed = input.hasRightPanel && input.layoutMode === "full";
  let leftMode: ChannelPanelMode = leftAllowed && input.leftOpen ? "push" : "closed";
  let rightMode: ChannelPanelMode = rightAllowed && input.rightOpen ? "push" : "closed";

  if (!fitsPush(input.availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth)) {
    if (rightMode === "push") {
      rightMode = input.rightPinned || leftMode === "closed" ? "overlay" : "closed";
    }
  }

  if (!fitsPush(input.availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth)) {
    if (leftMode === "push") {
      leftMode = input.leftPinned || rightMode === "closed" ? "overlay" : "closed";
    }
  }

  if (!fitsPush(input.availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth)) {
    if (rightMode === "push") rightMode = "overlay";
    if (!fitsPush(input.availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth) && leftMode === "push") {
      leftMode = "overlay";
    }
  }

  const pushedWidth =
    (leftMode === "push" ? leftWidth : 0)
    + (rightMode === "push" ? rightWidth : 0);

  return {
    left: { mode: leftMode, width: leftWidth },
    right: { mode: rightMode, width: rightWidth },
    chatWidth: Math.max(0, input.availableWidth - pushedWidth),
  };
}
