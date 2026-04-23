import assert from "node:assert/strict";
import {
  CHANNEL_PANEL_DEFAULT_WIDTH,
  resolveChannelPanelLayout,
  type ChannelPanelLayoutInput,
} from "./channelPanelLayout.js";

const base: ChannelPanelLayoutInput = {
  availableWidth: 1600,
  isMobile: false,
  layoutMode: "full",
  hasLeftPanel: true,
  hasRightPanel: true,
  leftOpen: true,
  rightOpen: true,
  leftPinned: false,
  rightPinned: false,
  leftWidth: CHANNEL_PANEL_DEFAULT_WIDTH,
  rightWidth: CHANNEL_PANEL_DEFAULT_WIDTH,
};

assert.deepEqual(resolveChannelPanelLayout(base).left.mode, "push");
assert.deepEqual(resolveChannelPanelLayout(base).right.mode, "push");

{
  const resolved = resolveChannelPanelLayout({ ...base, availableWidth: 1300 });
  assert.equal(resolved.left.mode, "push");
  assert.equal(resolved.right.mode, "closed");
}

{
  const resolved = resolveChannelPanelLayout({ ...base, availableWidth: 1000, leftPinned: true });
  assert.equal(resolved.left.mode, "overlay");
  assert.equal(resolved.right.mode, "closed");
}

{
  const resolved = resolveChannelPanelLayout({ ...base, availableWidth: 1000, rightPinned: true });
  assert.equal(resolved.left.mode, "closed");
  assert.equal(resolved.right.mode, "overlay");
}

{
  const resolved = resolveChannelPanelLayout({ ...base, layoutMode: "rail-chat" });
  assert.equal(resolved.left.mode, "push");
  assert.equal(resolved.right.mode, "closed");
}

{
  const resolved = resolveChannelPanelLayout({
    ...base,
    leftWidth: 700,
    rightOpen: false,
  });
  assert.equal(resolved.left.mode, "push");
  assert.equal(resolved.left.width, 700);
  assert.equal(resolved.right.mode, "closed");
  assert.equal(resolved.chatWidth, 900);
}

{
  const resolved = resolveChannelPanelLayout({
    ...base,
    availableWidth: 1200,
    leftWidth: 700,
    rightOpen: false,
  });
  assert.equal(resolved.left.mode, "overlay");
  assert.equal(resolved.right.mode, "closed");
  assert.equal(resolved.chatWidth, 1200);
}

{
  const resolved = resolveChannelPanelLayout({
    ...base,
    rightWidth: 700,
    leftOpen: false,
  });
  assert.equal(resolved.left.mode, "closed");
  assert.equal(resolved.right.mode, "push");
  assert.equal(resolved.right.width, 700);
  assert.equal(resolved.chatWidth, 900);
}

{
  const resolved = resolveChannelPanelLayout({ ...base, layoutMode: "dashboard-only" });
  assert.equal(resolved.left.mode, "closed");
  assert.equal(resolved.right.mode, "closed");
}

{
  const resolved = resolveChannelPanelLayout({ ...base, isMobile: true });
  assert.equal(resolved.left.mode, "closed");
  assert.equal(resolved.right.mode, "closed");
}
