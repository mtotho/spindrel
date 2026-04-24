import type { BotConfig, MemoryConfig } from "../types/api";

type BotSavePayload = Record<string, unknown>;

const READ_ONLY_FIELDS = new Set([
  "created_at",
  "updated_at",
]);

function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, inner) => {
    if (!inner || typeof inner !== "object" || Array.isArray(inner)) return inner;
    return Object.keys(inner as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        const child = (inner as Record<string, unknown>)[key];
        if (child !== undefined) acc[key] = child;
        return acc;
      }, {});
  });
}

function normalizeBotForSave(bot: Partial<BotConfig>, isNew: boolean): BotSavePayload {
  const payload: BotSavePayload = { ...bot };
  const memory = payload.memory as MemoryConfig | undefined;

  if (memory) {
    payload.memory_config = memory;
    delete payload.memory;
  }

  if (!isNew) {
    delete payload.id;
  }

  for (const key of Object.keys(payload)) {
    if (payload[key] === undefined || READ_ONLY_FIELDS.has(key)) {
      delete payload[key];
    }
  }

  return payload;
}

export function buildBotSavePayload({
  draft,
  original,
  isNew,
}: {
  draft: Partial<BotConfig>;
  original?: Partial<BotConfig> | null;
  isNew: boolean;
}): BotSavePayload {
  const draftPayload = normalizeBotForSave(draft, isNew);

  if (isNew || !original) return draftPayload;

  const originalPayload = normalizeBotForSave(original, false);
  const changed: BotSavePayload = {};

  for (const key of Object.keys(draftPayload)) {
    if (stableStringify(draftPayload[key]) !== stableStringify(originalPayload[key])) {
      changed[key] = draftPayload[key];
    }
  }

  return changed;
}
