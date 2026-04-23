export const CHANNEL_PANEL_DEFAULT_WIDTH = 320;
export const CHANNEL_PANEL_MIN_WIDTH = 240;
export const CHANNEL_PANEL_MAX_WIDTH = 720;
export const CHANNEL_CHAT_MIN_WIDTH = 760;
export function clampChannelPanelWidth(width, maxWidth = CHANNEL_PANEL_MAX_WIDTH) {
    if (!Number.isFinite(width))
        return CHANNEL_PANEL_DEFAULT_WIDTH;
    return Math.max(CHANNEL_PANEL_MIN_WIDTH, Math.min(maxWidth, Math.round(width)));
}
function fitsPush(availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth) {
    const used = (leftMode === "push" ? leftWidth : 0)
        + (rightMode === "push" ? rightWidth : 0);
    return availableWidth - used >= chatMinWidth;
}
export function resolveChannelPanelLayout(input) {
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
    let leftMode = leftAllowed && input.leftOpen ? "push" : "closed";
    let rightMode = rightAllowed && input.rightOpen ? "push" : "closed";
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
        if (rightMode === "push")
            rightMode = "overlay";
        if (!fitsPush(input.availableWidth, chatMinWidth, leftMode, leftWidth, rightMode, rightWidth) && leftMode === "push") {
            leftMode = "overlay";
        }
    }
    const pushedWidth = (leftMode === "push" ? leftWidth : 0)
        + (rightMode === "push" ? rightWidth : 0);
    return {
        left: { mode: leftMode, width: leftWidth },
        right: { mode: rightMode, width: rightWidth },
        chatWidth: Math.max(0, input.availableWidth - pushedWidth),
    };
}
