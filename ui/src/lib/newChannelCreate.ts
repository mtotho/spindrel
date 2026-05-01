export type NewChannelBotMode = "existing" | "create";

export interface ChannelCreatePayload {
  name: string;
  bot_id: string;
  private?: boolean;
  category?: string;
  user_id?: string;
  activate_integrations?: string[];
}

export interface NewBotCreatePayload {
  id: string;
  name: string;
  model: string;
  model_provider_id?: string | null;
  user_id?: string;
}

export const BOT_ID_PATTERN = /^[a-z0-9_-]+$/;

export function botIdFromName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "")
    .slice(0, 48);
}

export function validateNewBotDraft({
  id,
  name,
  model,
  existingBotIds,
}: {
  id: string;
  name: string;
  model: string;
  existingBotIds: readonly string[];
}): string | null {
  const trimmedId = id.trim();
  if (!name.trim()) return "Name the bot.";
  if (!trimmedId) return "Set a bot id.";
  if (!BOT_ID_PATTERN.test(trimmedId)) return "Use lowercase letters, numbers, hyphens, or underscores for the bot id.";
  if (existingBotIds.includes(trimmedId)) return "That bot id already exists.";
  if (!model.trim()) return "Choose a model for the bot.";
  return null;
}

export function buildChannelCreatePayload({
  name,
  botId,
  isPrivate,
  category,
  ownerUserId,
  isAdmin,
  enabledIntegrations = [],
}: {
  name: string;
  botId: string;
  isPrivate: boolean;
  category?: string;
  ownerUserId?: string | null;
  isAdmin: boolean;
  enabledIntegrations?: readonly string[];
}): ChannelCreatePayload {
  const body: ChannelCreatePayload = {
    name: name.trim(),
    bot_id: botId,
    private: isPrivate,
  };
  const trimmedCategory = category?.trim();
  if (trimmedCategory) body.category = trimmedCategory;
  if (isAdmin && ownerUserId) body.user_id = ownerUserId;
  if (enabledIntegrations.length > 0) body.activate_integrations = [...enabledIntegrations];
  return body;
}

export function buildNewBotCreatePayload({
  id,
  name,
  model,
  modelProviderId,
  ownerUserId,
  isAdmin,
}: {
  id: string;
  name: string;
  model: string;
  modelProviderId?: string | null;
  ownerUserId?: string | null;
  isAdmin: boolean;
}): NewBotCreatePayload {
  const body: NewBotCreatePayload = {
    id: id.trim(),
    name: name.trim(),
    model: model.trim(),
  };
  if (modelProviderId !== undefined) body.model_provider_id = modelProviderId;
  if (isAdmin && ownerUserId) body.user_id = ownerUserId;
  return body;
}
