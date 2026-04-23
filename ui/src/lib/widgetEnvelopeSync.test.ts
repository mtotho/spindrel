import test from "node:test";
import assert from "node:assert/strict";

import {
  buildWidgetSyncSignature,
  decidePinnedSharedEnvelopeUpdate,
  type SharedEnvelopeUpdate,
} from "./widgetEnvelopeSync.ts";

const baseEnvelope = {
  content_type: "application/vnd.spindrel.components+json",
  body: "{\"components\":[]}",
  plain_body: "",
  display: "inline" as const,
  truncated: false,
  refreshable: true,
  record_id: "record-1",
  byte_size: 32,
};

function makeUpdate(
  overrides: Partial<SharedEnvelopeUpdate> = {},
): SharedEnvelopeUpdate {
  return {
    kind: "state_poll",
    sourceToolName: "homeassistant-ha_get_state",
    sourceSignature: buildWidgetSyncSignature("homeassistant-ha_get_state", {}),
    envelope: baseEnvelope,
    ...overrides,
  };
}

test("pinned widgets adopt same-signature state-poll updates without re-polling", () => {
  assert.equal(
    decidePinnedSharedEnvelopeUpdate({
      currentToolName: "homeassistant-ha_get_state",
      currentSignature: buildWidgetSyncSignature("homeassistant-ha_get_state", {}),
      currentEnvelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"Off\"}]}" },
      incoming: makeUpdate({
        envelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"On\"}]}" },
      }),
    }),
    "adopt",
  );
});

test("pinned widgets ignore same-tool state-poll updates from a different config signature", () => {
  assert.equal(
    decidePinnedSharedEnvelopeUpdate({
      currentToolName: "homeassistant-ha_get_state",
      currentSignature: buildWidgetSyncSignature("homeassistant-ha_get_state", { compact: true }),
      currentEnvelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"Off\"}]}" },
      incoming: makeUpdate({
        sourceSignature: buildWidgetSyncSignature("homeassistant-ha_get_state", { compact: false }),
        envelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"On\"}]}" },
      }),
    }),
    "ignore",
  );
});

test("pinned widgets locally refresh when a different tool variant updates the same entity", () => {
  assert.equal(
    decidePinnedSharedEnvelopeUpdate({
      currentToolName: "homeassistant-ha_get_state",
      currentSignature: buildWidgetSyncSignature("homeassistant-ha_get_state", {}),
      currentEnvelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"Off\"}]}" },
      incoming: makeUpdate({
        kind: "tool_result",
        sourceToolName: "homeassistant-HassTurnOn",
        sourceSignature: buildWidgetSyncSignature("homeassistant-HassTurnOn", {}),
        envelope: { ...baseEnvelope, body: "{\"components\":[{\"type\":\"status\",\"text\":\"Turning on\"}]}" },
      }),
    }),
    "refresh",
  );
});
