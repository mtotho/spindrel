import test from "node:test";
import assert from "node:assert/strict";

import {
  buildHarnessApprovalPreview,
  unifiedDiffPreviewFromStrings,
} from "./harnessApprovalPreviewModel.js";

test("Claude Edit approval preview is modeled as a unified diff", () => {
  const preview = buildHarnessApprovalPreview("Edit", {
    file_path: "app.py",
    old_string: "print('old')\n",
    new_string: "print('new')\n",
  });

  assert.equal(preview.kind, "diff");
  if (preview.kind !== "diff") throw new Error("expected diff preview");
  assert.equal(preview.target, "app.py");
  assert.match(preview.body, /--- a\/app\.py/);
  assert.match(preview.body, /\+print\('new'\)/);
  assert.match(preview.body, /-print\('old'\)/);
});

test("Claude Write approval preview is modeled as code content, not plain text chrome", () => {
  const preview = buildHarnessApprovalPreview("Write", {
    file_path: "index.html",
    content: "<!DOCTYPE html>\n<html>\n<body>Hello</body>\n</html>",
  });

  assert.equal(preview.kind, "code");
  if (preview.kind !== "code") throw new Error("expected code preview");
  assert.equal(preview.target, "index.html");
  assert.match(preview.body, /<!DOCTYPE html>/);
});

test("Bash approval preview preserves command and description separately", () => {
  const preview = buildHarnessApprovalPreview("Bash", {
    command: "npm test",
    description: "run tests",
  });

  assert.deepEqual(preview, {
    kind: "bash",
    toolName: "Bash",
    command: "npm test",
    description: "run tests",
  });
});

test("unified diff preview includes source and target headers", () => {
  assert.equal(
    unifiedDiffPreviewFromStrings({
      path: "notes.md",
      oldString: "old\n",
      newString: "new\n",
    }),
    "--- a/notes.md\n+++ b/notes.md\n@@ -1,1 +1,1 @@\n-old\n+new",
  );
});
