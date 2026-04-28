import test from "node:test";
import assert from "node:assert/strict";

import {
  CHANNEL_DATA_UPLOAD_MAX_BYTES,
  CHAT_INLINE_IMAGE_MAX_BYTES,
  decideAttachmentRoute,
  formatFileSize,
} from "./attachmentRouting.js";

function fileLike(type: string, size: number): Pick<File, "type" | "size"> {
  return { type, size };
}

test("small images route inline to the agent", () => {
  const decision = decideAttachmentRoute(fileLike("image/png", CHAT_INLINE_IMAGE_MAX_BYTES));
  assert.equal(decision.route, "inline_image");
});

test("large images route to channel data", () => {
  const decision = decideAttachmentRoute(fileLike("image/jpeg", CHAT_INLINE_IMAGE_MAX_BYTES + 1));
  assert.equal(decision.route, "channel_data");
});

test("non-image files route to channel data", () => {
  const decision = decideAttachmentRoute(fileLike("text/plain", 1024));
  assert.equal(decision.route, "channel_data");
});

test("files above the channel upload limit are rejected before upload", () => {
  const decision = decideAttachmentRoute(fileLike("application/octet-stream", CHANNEL_DATA_UPLOAD_MAX_BYTES + 1));
  assert.equal(decision.route, "rejected");
  assert.match(decision.reason, /larger than/);
});

test("file size labels are compact and human-readable", () => {
  assert.equal(formatFileSize(512), "512 B");
  assert.equal(formatFileSize(1536), "1.5 KB");
  assert.equal(formatFileSize(8 * 1024 * 1024), "8 MB");
});
