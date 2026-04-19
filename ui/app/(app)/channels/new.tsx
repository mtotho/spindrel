import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useCreateChannel,
  useGlobalActivatableIntegrations,
  useChannelCategories,
} from "@/src/api/hooks/useChannels";
import { Section, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { UserSelect } from "@/src/components/shared/UserSelect";
import { IntegrationActivationList } from "@/src/components/channels/IntegrationActivationList";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";

type WizardStep = "basics" | "integrations";

export default function NewChannelScreen() {
  const navigate = useNavigate();
  const goBack = useGoBack("/");
  const theme = useThemeTokens();
  const { data: bots } = useBots();
  const { data: activatableIntegrations } = useGlobalActivatableIntegrations();
  const { data: existingCategories } = useChannelCategories();
  const createChannel = useCreateChannel();

  const isAdmin = useIsAdmin();
  const currentUserId = useAuthStore((s) => s.user?.id);

  // Form state
  const [step, setStep] = useState<WizardStep>("basics");
  const [name, setName] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [useBotMode, setUseBotMode] = useState(false);
  const [botId, setBotId] = useState("default");
  const [category, setCategory] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [enabledIntegrations, setEnabledIntegrations] = useState<string[]>([]);
  const [memberBotIds, setMemberBotIds] = useState<string[]>([]);
  // Admin can reassign owner at create time. Non-admins always own what they
  // create (backend auto-populates user_id from the auth user when omitted).
  const [ownerUserId, setOwnerUserId] = useState<string | null>(currentUserId ?? null);

  const botOptions = useMemo(
    () => (bots ?? []).map((b) => ({ label: b.name, value: b.id })),
    [bots],
  );

  // Category autocomplete suggestions
  const categorySuggestions = useMemo(() => {
    if (!existingCategories || !category) return [];
    return existingCategories.filter(
      (c) => c.toLowerCase().includes(category.toLowerCase()) && c !== category,
    );
  }, [existingCategories, category]);

  const hasActivatable = (activatableIntegrations?.length ?? 0) > 0;

  const handleToggleIntegration = (intType: string) => {
    setEnabledIntegrations((prev) =>
      prev.includes(intType)
        ? prev.filter((x) => x !== intType)
        : [...prev, intType],
    );
  };

  /** Build shared request body from common fields */
  const buildBody = () => {
    const body: Parameters<typeof createChannel.mutateAsync>[0] = {
      name: name.trim(),
      bot_id: useBotMode ? botId : "default",
      private: isPrivate,
    };
    if (!useBotMode && selectedModel) {
      body.model_override = selectedModel;
    }
    if (category.trim()) {
      body.category = category.trim();
    }
    if (memberBotIds.length > 0) {
      body.member_bot_ids = memberBotIds;
    }
    if (isAdmin && ownerUserId) {
      body.user_id = ownerUserId;
    }
    return body;
  };

  const handleQuickCreate = async () => {
    if (!name.trim() || createChannel.isPending) return;
    try {
      const channel = await createChannel.mutateAsync(buildBody());
      navigate(`/channels/${channel.id}`);
    } catch {
      // mutation error handled by react-query
    }
  };

  const handleSubmit = async () => {
    if (!name.trim() || createChannel.isPending) return;
    try {
      const body = buildBody();
      if (enabledIntegrations.length > 0) {
        body.activate_integrations = enabledIntegrations;
      }
      const channel = await createChannel.mutateAsync(body);
      navigate(`/channels/${channel.id}`);
    } catch {
      // mutation error handled by react-query
    }
  };

  const canProceed = name.trim().length > 0;

  const errorBanner = createChannel.isError ? (
    <span style={{ color: "#f87171", fontSize: 12, marginTop: 8, display: "block" }}>
      {createChannel.error instanceof Error ? createChannel.error.message : "Failed to create channel"}
    </span>
  ) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", backgroundColor: theme.surface }}>
      {/* Header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 12,
        padding: "12px 16px",
        borderBottom: `1px solid ${theme.surfaceBorder}`,
      }}>
        <button
          type="button"
          className="header-icon-btn"
          onClick={goBack}
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={theme.textMuted} />
        </button>
        <span style={{ flex: 1, color: theme.text, fontWeight: 600, fontSize: 14 }}>New Channel</span>
        {/* Step indicator */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          {(["basics", "integrations"] as WizardStep[])
            .filter((s) => s !== "integrations" || hasActivatable)
            .map((s) => (
              <div
                key={s}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: step === s ? theme.accent : theme.surfaceBorder,
                }}
              />
            ))}
        </div>
      </div>

      {/* Step 1: Basics */}
      {step === "basics" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          {/* Scrollable form content */}
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            <div style={{ padding: 20, maxWidth: 560, width: "100%", boxSizing: "border-box" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Section title="Channel Name">
                  <TextInput
                    value={name}
                    onChangeText={setName}
                    placeholder="my-channel"
                  />
                </Section>

                {/* Model picker */}
                {!useBotMode && (
                  <Section title="Model">
                    <LlmModelDropdown
                      value={selectedModel}
                      onChange={(modelId) => setSelectedModel(modelId)}
                      placeholder="Default (from bot)"
                      allowClear
                    />
                  </Section>
                )}

                {/* Bot mode toggle */}
                <button
                  type="button"
                  onClick={() => setUseBotMode(!useBotMode)}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                    background: "none", border: "none", cursor: "pointer", padding: 0,
                    font: "inherit",
                  }}
                >
                  <span style={{ color: theme.textMuted, fontSize: 12, textDecoration: "underline" }}>
                    {useBotMode ? "Pick a model instead" : "Or use an existing bot"}
                  </span>
                </button>

                {useBotMode && (
                  <Section title="Bot">
                    <BotPicker
                      value={botId}
                      onChange={setBotId}
                      bots={bots ?? []}
                    />
                  </Section>
                )}

                {/* Category */}
                <Section title="Category (optional)">
                  <TextInput
                    value={category}
                    onChangeText={setCategory}
                    placeholder="e.g. Work, Personal, Projects"
                  />
                  {categorySuggestions.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                      {categorySuggestions.slice(0, 5).map((cat) => (
                        <button
                          type="button"
                          key={cat}
                          onClick={() => setCategory(cat)}
                          style={{
                            backgroundColor: theme.surfaceBorder,
                            padding: "3px 8px",
                            borderRadius: 4,
                            border: "none",
                            cursor: "pointer",
                            font: "inherit",
                            fontSize: 11,
                            color: theme.textMuted,
                          }}
                        >
                          {cat}
                        </button>
                      ))}
                    </div>
                  )}
                </Section>

                <Toggle
                  value={isPrivate}
                  onChange={setIsPrivate}
                  label="Private"
                  description="Only the owner and admins can see this channel"
                />

                {isAdmin && (
                  <Section title="Owner" description="Admins can assign a different user as the owner.">
                    <UserSelect
                      value={ownerUserId}
                      onChange={setOwnerUserId}
                    />
                  </Section>
                )}

                {/* Member bots (multi-bot channel) */}
                {(bots ?? []).filter((b) => b.id !== (useBotMode ? botId : "default")).length > 0 && (
                  <Section title="Member Bots (optional)" description="Add additional bots that can participate when @-mentioned">
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {(bots ?? [])
                        .filter((b) => b.id !== (useBotMode ? botId : "default"))
                        .map((b) => {
                          const selected = memberBotIds.includes(b.id);
                          return (
                            <button
                              type="button"
                              key={b.id}
                              onClick={() => setMemberBotIds((prev) =>
                                selected ? prev.filter((x) => x !== b.id) : [...prev, b.id]
                              )}
                              style={{
                                display: "flex",
                                flexDirection: "row",
                                alignItems: "center",
                                gap: 8,
                                padding: "6px 10px",
                                borderRadius: 6,
                                border: `1px solid ${selected ? theme.accent : theme.surfaceBorder}`,
                                background: selected ? `${theme.accent}10` : "transparent",
                                cursor: "pointer",
                                font: "inherit",
                                textAlign: "left",
                                color: "inherit",
                              }}
                            >
                              {selected && <Check size={14} color={theme.accent} />}
                              <span style={{ fontSize: 13, color: theme.text, flex: 1 }}>{b.name}</span>
                              <span style={{ fontSize: 11, color: theme.textDim }}>{b.id}</span>
                            </button>
                          );
                        })}
                    </div>
                  </Section>
                )}
              </div>
            </div>
          </div>

          {/* Sticky footer — always visible */}
          <div
            style={{
              borderTop: `1px solid ${theme.surfaceBorder}`,
              padding: "14px 20px",
              maxWidth: 560,
              width: "100%",
              boxSizing: "border-box",
            }}
          >
            {errorBanner}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {hasActivatable ? (
                <button
                  type="button"
                  onClick={() => canProceed && setStep("integrations")}
                  disabled={!canProceed}
                  style={{
                    backgroundColor: canProceed ? theme.accent : theme.surfaceBorder,
                    padding: "12px 20px",
                    borderRadius: 8,
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                    opacity: canProceed ? 1 : 0.5,
                    border: "none",
                    cursor: canProceed ? "pointer" : "default",
                    font: "inherit",
                  }}
                >
                  <span style={{ color: canProceed ? "#fff" : theme.textDim, fontSize: 14, fontWeight: 600 }}>
                    Continue
                  </span>
                  <ArrowRight size={16} color={canProceed ? "#fff" : theme.textDim} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleQuickCreate}
                  disabled={!canProceed || createChannel.isPending}
                  style={{
                    backgroundColor: canProceed ? theme.accent : theme.surfaceBorder,
                    padding: "12px 20px",
                    borderRadius: 8,
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                    opacity: canProceed && !createChannel.isPending ? 1 : 0.5,
                    border: "none",
                    cursor: canProceed && !createChannel.isPending ? "pointer" : "default",
                    font: "inherit",
                  }}
                >
                  <Check size={16} color={canProceed ? "#fff" : theme.textDim} />
                  <span style={{ color: canProceed ? "#fff" : theme.textDim, fontSize: 14, fontWeight: 600 }}>
                    {createChannel.isPending ? "Creating..." : "Create Channel"}
                  </span>
                </button>
              )}

              {hasActivatable && (
                <button
                  type="button"
                  onClick={handleQuickCreate}
                  disabled={!canProceed || createChannel.isPending}
                  style={{
                    border: `1px solid ${theme.surfaceBorder}`,
                    padding: "10px 20px",
                    borderRadius: 8,
                    textAlign: "center",
                    cursor: canProceed && !createChannel.isPending ? "pointer" : "default",
                    background: "none",
                    font: "inherit",
                    color: theme.textMuted,
                    fontSize: 14,
                  }}
                >
                  {createChannel.isPending ? "Creating..." : "Quick Create (skip setup)"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Step 2: Integrations — scrollable content + sticky footer */}
      {step === "integrations" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            <div style={{ padding: 20, maxWidth: 560, width: "100%", boxSizing: "border-box" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div>
                  <span style={{ color: theme.text, fontWeight: 600, fontSize: 14, display: "block" }}>
                    Activate Integrations
                  </span>
                  <span style={{ color: theme.textMuted, fontSize: 12, marginTop: 4, display: "block" }}>
                    Integrations inject specialized tools and skills into your channel.
                  </span>
                </div>

                <IntegrationActivationList
                  integrations={activatableIntegrations ?? []}
                  enabled={enabledIntegrations}
                  onToggle={handleToggleIntegration}
                />
              </div>
            </div>
          </div>

          {/* Sticky footer */}
          <div
            style={{
              borderTop: `1px solid ${theme.surfaceBorder}`,
              padding: "14px 20px",
              maxWidth: 560,
              width: "100%",
              boxSizing: "border-box",
            }}
          >
            {errorBanner}
            <div style={{ display: "flex", flexDirection: "row", gap: 10 }}>
              <button
                type="button"
                onClick={() => setStep("basics")}
                style={{
                  border: `1px solid ${theme.surfaceBorder}`,
                  padding: "10px 20px",
                  borderRadius: 8,
                  textAlign: "center",
                  flex: 1,
                  cursor: "pointer",
                  background: "none",
                  font: "inherit",
                  color: theme.textMuted,
                  fontSize: 14,
                }}
              >
                Back
              </button>

              <button
                type="button"
                onClick={handleSubmit}
                disabled={createChannel.isPending}
                style={{
                  backgroundColor: theme.accent,
                  padding: "12px 20px",
                  borderRadius: 8,
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  flex: 1,
                  border: "none",
                  cursor: createChannel.isPending ? "default" : "pointer",
                  font: "inherit",
                }}
              >
                <Check size={16} color="#fff" />
                <span style={{ color: "#fff", fontSize: 14, fontWeight: 600 }}>
                  {createChannel.isPending ? "Creating..." : "Create Channel"}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
