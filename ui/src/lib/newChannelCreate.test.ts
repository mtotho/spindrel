import { strict as assert } from "node:assert";
import {
  botIdFromName,
  buildChannelCreatePayload,
  buildNewBotCreatePayload,
  validateNewBotDraft,
} from "./newChannelCreate.js";

assert.equal(botIdFromName("  My Kitchen Bot!  "), "my-kitchen-bot");
assert.equal(botIdFromName("QA_Bot v2"), "qa_bot-v2");

assert.equal(
  validateNewBotDraft({
    id: "qa-bot",
    name: "QA Bot",
    model: "openai/gpt-5.4",
    existingBotIds: ["qa-bot"],
  }),
  "That bot id already exists.",
);

assert.equal(
  validateNewBotDraft({
    id: "qa bot",
    name: "QA Bot",
    model: "openai/gpt-5.4",
    existingBotIds: [],
  }),
  "Use lowercase letters, numbers, hyphens, or underscores for the bot id.",
);

assert.equal(
  validateNewBotDraft({
    id: "qa-bot",
    name: "QA Bot",
    model: "openai/gpt-5.4",
    existingBotIds: [],
  }),
  null,
);

assert.deepEqual(
  buildChannelCreatePayload({
    name: "  Kitchen  ",
    botId: "kitchen-bot",
    isPrivate: true,
    category: " Home ",
    ownerUserId: "user-1",
    isAdmin: true,
    enabledIntegrations: ["slack"],
  }),
  {
    name: "Kitchen",
    bot_id: "kitchen-bot",
    private: true,
    category: "Home",
    user_id: "user-1",
    activate_integrations: ["slack"],
  },
);

assert.deepEqual(
  buildNewBotCreatePayload({
    id: " kitchen-bot ",
    name: " Kitchen Bot ",
    model: " openai/gpt-5.4 ",
    modelProviderId: "openai",
    ownerUserId: "user-1",
    isAdmin: true,
  }),
  {
    id: "kitchen-bot",
    name: "Kitchen Bot",
    model: "openai/gpt-5.4",
    model_provider_id: "openai",
    user_id: "user-1",
  },
);
