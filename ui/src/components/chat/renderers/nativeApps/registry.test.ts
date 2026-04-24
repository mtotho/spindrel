import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

test("native widget registry includes machine control widget", () => {
  const registry = readFileSync(resolve(process.cwd(), "src/components/chat/renderers/nativeApps/registry.tsx"), "utf8");

  assert.match(registry, /"core\/machine_control_native": MachineControlWidget/);
});
