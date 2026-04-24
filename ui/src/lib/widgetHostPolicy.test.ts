import test from "node:test";
import assert from "node:assert/strict";

import { resolveWidgetHostPolicy } from "./widgetHostPolicy.js";

const chrome = {
  borderless: false,
  hoverScrollbars: true,
  hideTitles: true,
} as const;

test("header zone stays titleless even when widget config requests a host title", () => {
  const resolved = resolveWidgetHostPolicy({
    layout: "header",
    chrome,
    widgetConfig: { show_title: "show" },
    widgetPresentation: {
      presentation_family: "card",
      panel_title: "Panel title",
      show_panel_title: true,
    },
    headerBackdropMode: "default",
  });

  assert.equal(resolved.titleMode, "hidden");
});

test("header backdrop mode selects the intended host surface", () => {
  const implicit = resolveWidgetHostPolicy({
    layout: "header",
    chrome,
    widgetConfig: null,
  });
  const glass = resolveWidgetHostPolicy({
    layout: "header",
    chrome,
    widgetConfig: null,
    headerBackdropMode: "glass",
  });
  const clear = resolveWidgetHostPolicy({
    layout: "header",
    chrome,
    widgetConfig: null,
    headerBackdropMode: "clear",
  });
  const fallback = resolveWidgetHostPolicy({
    layout: "header",
    chrome,
    widgetConfig: null,
    headerBackdropMode: "default",
  });

  assert.equal(implicit.wrapperSurface, "translucent");
  assert.equal(glass.wrapperSurface, "translucent");
  assert.equal(clear.wrapperSurface, "plain");
  assert.equal(fallback.wrapperSurface, "surface");
});
