import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { SlashCommandSpec } from "@/src/types/api";
import { resolveAvailableSlashCommandIds } from "./slashCommandSurfaces.js";

const catalog: SlashCommandSpec[] = [
  { id: "help", label: "/help", description: "", surfaces: ["channel", "session"], local_only: false, args: [] },
  { id: "context", label: "/context", description: "", surfaces: ["channel", "session"], local_only: false, args: [] },
  { id: "find", label: "/find", description: "", surfaces: ["channel"], local_only: false, args: [] },
  { id: "effort", label: "/effort", description: "", surfaces: ["channel"], local_only: false, args: [] },
  { id: "clear", label: "/clear", description: "", surfaces: ["channel"], local_only: true, args: [] },
  { id: "scratch", label: "/scratch", description: "", surfaces: ["channel"], local_only: true, args: [] },
  { id: "model", label: "/model", description: "", surfaces: ["channel", "session"], local_only: true, args: [] },
  { id: "theme", label: "/theme", description: "", surfaces: ["channel", "session"], local_only: true, args: [] },
  { id: "sessions", label: "/sessions", description: "", surfaces: ["channel", "session"], local_only: true, args: [] },
];

describe("resolveAvailableSlashCommandIds", () => {
  it("derives channel commands from catalog plus enabled local capabilities", () => {
    assert.deepEqual(
      resolveAvailableSlashCommandIds({
        catalog,
        surface: "channel",
        enabled: true,
        capabilities: ["clear", "scratch", "model", "theme", "sessions"],
      }),
      ["help", "context", "find", "effort", "clear", "scratch", "model", "theme", "sessions"],
    );
  });

  it("keeps session surfaces off channel-only commands", () => {
    assert.deepEqual(
      resolveAvailableSlashCommandIds({
        catalog,
        surface: "session",
        enabled: true,
        capabilities: ["model", "theme", "sessions"],
      }),
      ["help", "context", "model", "theme", "sessions"],
    );
  });

  it("omits local commands when the caller does not provide the capability", () => {
    assert.deepEqual(
      resolveAvailableSlashCommandIds({
        catalog,
        surface: "session",
        enabled: true,
        capabilities: ["model", "theme"],
      }),
      ["help", "context", "model", "theme"],
    );
  });

  it("returns no commands for disabled surfaces", () => {
    assert.deepEqual(
      resolveAvailableSlashCommandIds({
        catalog,
        surface: "channel",
        enabled: false,
        capabilities: ["clear", "scratch", "model", "theme", "sessions"],
      }),
      [],
    );
  });
});
