import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(
  resolve(process.cwd(), "app/(app)/admin/bots/[botId]/WorkspaceSection.tsx"),
  "utf8",
);

assert.match(source, /pending shared/);
assert.match(source, /Default shared workspace/);
assert.match(source, /enrolls on save/);

for (const staleCopy of [
  "Enable workspace tools",
  "Docker container",
  "Docker sandbox",
  "Host execution",
  "standalone",
]) {
  assert.equal(source.includes(staleCopy), false, `${staleCopy} should not appear in the normal bot workspace settings`);
}
