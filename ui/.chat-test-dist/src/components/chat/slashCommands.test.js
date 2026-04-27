import assert from "node:assert/strict";
import { buildCompletedSlashCommandText } from "./slashCommands.js";
assert.equal(buildCompletedSlashCommandText("sessions"), "/sessions ");
assert.equal(buildCompletedSlashCommandText("/split"), "/split ");
assert.equal(buildCompletedSlashCommandText("model", "gpt-5.5"), "/model gpt-5.5 ");
assert.equal(buildCompletedSlashCommandText("  "), "/");
