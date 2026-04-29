import test from "node:test";
import assert from "node:assert/strict";

import { buildChatAttachmentPayload } from "./chatAttachmentPayload.ts";

function pendingFile(overrides: Record<string, unknown>) {
  return {
    id: "pf-1",
    status: "ready",
    preview: undefined,
    reason: undefined,
    error: undefined,
    base64: undefined,
    upload: undefined,
    file: {
      name: "fixture.png",
      type: "image/png",
      size: 3,
    },
    ...overrides,
  } as never;
}

test("inline images become chat attachments and file metadata", () => {
  const payload = buildChatAttachmentPayload([
    pendingFile({ route: "inline_image", base64: "AAA" }),
  ]);

  assert.deepEqual(payload.attachments, [{
    type: "image",
    content: "AAA",
    mime_type: "image/png",
    name: "fixture.png",
  }]);
  assert.deepEqual(payload.file_metadata, [{
    filename: "fixture.png",
    mime_type: "image/png",
    size_bytes: 3,
    file_data: "AAA",
  }]);
  assert.equal(payload.workspace_uploads, undefined);
});

test("channel data uploads become workspace upload metadata", () => {
  const payload = buildChatAttachmentPayload([
    pendingFile({
      route: "channel_data",
      upload: { path: "data/uploads/fixture.png", size: 3 },
    }),
  ]);

  assert.deepEqual(payload.workspace_uploads, [{
    filename: "fixture.png",
    mime_type: "image/png",
    size_bytes: 3,
    path: "data/uploads/fixture.png",
  }]);
  assert.equal(payload.attachments, undefined);
  assert.equal(payload.file_metadata, undefined);
});
