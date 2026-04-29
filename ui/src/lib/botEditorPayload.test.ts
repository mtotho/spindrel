import { strict as assert } from "node:assert";
import { buildBotSavePayload } from "./botEditorPayload.js";
import type { BotConfig } from "../types/api";

const original = {
  id: "qa-bot",
  name: "QA Bot",
  model: "openai/gpt-4o",
  system_prompt: "Answer carefully.",
  model_provider_id: "openai",
  shared_workspace_id: "workspace-1",
  shared_workspace_role: "member",
  harness_session_state: { opaque: true },
  api_permissions: ["legacy:scope"],
  memory: {
    enabled: false,
    cross_channel: false,
    cross_client: false,
    cross_bot: false,
    similarity_threshold: 0.45,
  },
  created_at: "2026-04-23T00:00:00Z",
  updated_at: "2026-04-23T00:00:00Z",
} satisfies Partial<BotConfig>;

{
  const payload = buildBotSavePayload({
    original,
    draft: { ...original, model: "openai/gpt-5.4" },
    isNew: false,
  });

  assert.deepEqual(payload, { model: "openai/gpt-5.4" });
}

{
  const payload = buildBotSavePayload({
    original,
    draft: { ...original, model_provider_id: null },
    isNew: false,
  });

  assert.deepEqual(payload, { model_provider_id: null });
}

{
  const nextMemory = {
    ...(original.memory!),
    similarity_threshold: 0.5,
  };
  const payload = buildBotSavePayload({
    original,
    draft: { ...original, memory: nextMemory },
    isNew: false,
  });

  assert.deepEqual(payload, { memory_config: nextMemory });
}

{
  const payload = buildBotSavePayload({
    original,
    draft: { ...original, api_permissions: ["attachments:read"] },
    isNew: false,
  });

  assert.deepEqual(payload, { api_permissions: ["attachments:read"] });
}

{
  const payload = buildBotSavePayload({
    original,
    draft: {
      ...original,
      shared_workspace_id: "workspace-2",
      shared_workspace_role: "orchestrator",
      harness_session_state: { changed: true },
    },
    isNew: false,
  });

  assert.deepEqual(payload, {});
}

{
  const payload = buildBotSavePayload({
    draft: {
      id: "new-bot",
      name: "New Bot",
      model: "openai/gpt-5.4",
      memory: original.memory,
      shared_workspace_id: "workspace-1",
      shared_workspace_role: "member",
      created_at: "ignored",
    },
    isNew: true,
  });

  assert.deepEqual(payload, {
    id: "new-bot",
    name: "New Bot",
    model: "openai/gpt-5.4",
    memory_config: original.memory,
  });
}
