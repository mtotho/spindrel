import { strict as assert } from "node:assert";
import { getHistoryModeMeta, historyModeOptionLabel } from "./historyModeMeta";

const fileMode = getHistoryModeMeta("file");
assert.equal(fileMode.recommended, true);
assert.equal(fileMode.showFileArtifacts, true);
assert.equal(historyModeOptionLabel(fileMode), "File (active default)");

const summaryMode = getHistoryModeMeta("summary");
assert.equal(summaryMode.legacy, true);
assert.equal(historyModeOptionLabel(summaryMode), "Summary (legacy)");

const structuredMode = getHistoryModeMeta("structured");
assert.equal(structuredMode.legacy, true);
assert.equal(structuredMode.showFileArtifacts, undefined);
assert.match(structuredMode.detail, /Supported for compatibility/);
assert.ok(!structuredMode.detail.includes("active/default path for channels"));
