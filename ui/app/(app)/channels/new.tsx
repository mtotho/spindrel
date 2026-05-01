import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  Check,
  ChevronRight,
  Hash,
  Lock,
  Plug,
  Sparkles,
  UserRound,
} from "lucide-react";

import { useBots, useCreateBot } from "@/src/api/hooks/useBots";
import {
  useAvailableIntegrations,
  useChannelCategories,
  useCreateChannel,
  useGlobalActivatableIntegrations,
} from "@/src/api/hooks/useChannels";
import { apiFetch } from "@/src/api/client";
import { BindableIntegrationsList, type PendingBinding } from "@/src/components/channels/BindableIntegrationsList";
import { IntegrationActivationList } from "@/src/components/channels/IntegrationActivationList";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { FormRow, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  ActionButton,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSegmentedControl,
} from "@/src/components/shared/SettingsControls";
import { UserSelect } from "@/src/components/shared/UserSelect";
import {
  botIdFromName,
  buildChannelCreatePayload,
  buildNewBotCreatePayload,
  type NewChannelBotMode,
  validateNewBotDraft,
} from "@/src/lib/newChannelCreate";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useIsAdmin } from "@/src/hooks/useScope";
import { useAuthStore } from "@/src/stores/auth";

type WizardStep = "details" | "integrations";

function shortModel(model: string | undefined): string {
  if (!model) return "No model";
  const parts = model.split("/");
  return parts[parts.length - 1] || model;
}

function mutationMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function NewChannelScreen() {
  const navigate = useNavigate();
  const goBack = useGoBack("/");
  const [searchParams] = useSearchParams();
  const requestedBotId = searchParams.get("bot_id") ?? "";

  const { data: bots } = useBots();
  const { data: activatableIntegrations } = useGlobalActivatableIntegrations();
  const { data: availableIntegrations } = useAvailableIntegrations();
  const { data: existingCategories } = useChannelCategories();
  const createChannel = useCreateChannel();
  const createBot = useCreateBot();

  const isAdmin = useIsAdmin();
  const currentUser = useAuthStore((s) => s.user);
  const currentUserId = currentUser?.id;

  const botList = bots ?? [];
  const existingBotIds = useMemo(() => botList.map((candidate) => candidate.id), [botList]);
  const requestedBotExists = requestedBotId && existingBotIds.includes(requestedBotId);

  const [step, setStep] = useState<WizardStep>("details");
  const [botMode, setBotMode] = useState<NewChannelBotMode>("existing");
  const [botId, setBotId] = useState(requestedBotId);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [ownerUserId, setOwnerUserId] = useState<string | null>(currentUserId ?? null);
  const [newBotName, setNewBotName] = useState("");
  const [newBotId, setNewBotId] = useState("");
  const [newBotIdTouched, setNewBotIdTouched] = useState(false);
  const [newBotModel, setNewBotModel] = useState("");
  const [newBotModelProviderId, setNewBotModelProviderId] = useState<string | null | undefined>(undefined);
  const [enabledIntegrations, setEnabledIntegrations] = useState<string[]>([]);
  const [pendingBindings, setPendingBindings] = useState<Record<string, PendingBinding>>({});
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (requestedBotExists) setBotId(requestedBotId);
  }, [requestedBotExists, requestedBotId]);

  useEffect(() => {
    if (!newBotIdTouched) setNewBotId(botIdFromName(newBotName));
  }, [newBotIdTouched, newBotName]);

  const selectedBot = botList.find((candidate) => candidate.id === botId) ?? null;
  const bindableIntegrations = useMemo(
    () => (availableIntegrations ?? []).filter((integration) => integration.binding),
    [availableIntegrations],
  );
  const hasActivatable = (activatableIntegrations?.length ?? 0) > 0;
  const hasBindable = bindableIntegrations.length > 0;
  const hasIntegrationStep = hasActivatable || hasBindable;

  const categorySuggestions = useMemo(() => {
    const trimmed = category.trim().toLowerCase();
    if (!existingCategories || !trimmed) return [];
    return existingCategories.filter(
      (candidate) => candidate.toLowerCase().includes(trimmed) && candidate !== category,
    );
  }, [category, existingCategories]);

  const newBotError = botMode === "create"
    ? validateNewBotDraft({
      id: newBotId,
      name: newBotName,
      model: newBotModel,
      existingBotIds,
    })
    : null;
  const channelNameError = name.trim() ? null : "Name the channel.";
  const selectedBotError = botMode === "existing" && !selectedBot ? "Choose a bot for this channel." : null;
  const cannotCreateReason = channelNameError ?? selectedBotError ?? newBotError;
  const canCreate = !cannotCreateReason;
  const isCreating = createChannel.isPending || createBot.isPending;
  const errorMessage = localError
    ?? (createBot.isError ? mutationMessage(createBot.error, "Failed to create bot") : null)
    ?? (createChannel.isError ? mutationMessage(createChannel.error, "Failed to create channel") : null);
  const ownerLabel = ownerUserId && ownerUserId === currentUserId
    ? currentUser?.display_name || currentUser?.email || ownerUserId
    : ownerUserId;

  const handleToggleIntegration = (integrationType: string) => {
    setEnabledIntegrations((prev) =>
      prev.includes(integrationType)
        ? prev.filter((item) => item !== integrationType)
        : [...prev, integrationType],
    );
  };

  const handleBindingSubmit = (type: string, pending: PendingBinding) => {
    setPendingBindings((prev) => ({ ...prev, [type]: pending }));
  };

  const handleBindingRemove = (type: string) => {
    setPendingBindings((prev) => {
      const next = { ...prev };
      delete next[type];
      return next;
    });
  };

  const applyPendingBindings = async (channelId: string) => {
    for (const [integrationType, pending] of Object.entries(pendingBindings)) {
      try {
        await apiFetch(`/api/v1/channels/${channelId}/integrations`, {
          method: "POST",
          body: JSON.stringify({
            integration_type: integrationType,
            client_id: pending.clientId,
            display_name: pending.displayName || undefined,
            dispatch_config: Object.keys(pending.dispatchConfig).length > 0
              ? pending.dispatchConfig
              : undefined,
          }),
        });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn(`Failed to bind ${integrationType} on new channel`, err);
      }
    }
  };

  const createPrimaryBotIfNeeded = async (): Promise<string> => {
    if (botMode === "existing") return botId;
    const payload = buildNewBotCreatePayload({
      id: newBotId,
      name: newBotName,
      model: newBotModel,
      modelProviderId: newBotModelProviderId,
      ownerUserId,
      isAdmin,
    });
    const bot = await createBot.mutateAsync(payload);
    setBotMode("existing");
    setBotId(bot.id);
    return bot.id;
  };

  const createChannelWithOptions = async ({ includeIntegrations }: { includeIntegrations: boolean }) => {
    if (!canCreate || isCreating) return;
    setLocalError(null);
    let resolvedBotId = botId;
    try {
      resolvedBotId = await createPrimaryBotIfNeeded();
    } catch (err) {
      setLocalError(mutationMessage(err, "Failed to create bot"));
      return;
    }

    try {
      const body = buildChannelCreatePayload({
        name,
        botId: resolvedBotId,
        isPrivate,
        category,
        ownerUserId,
        isAdmin,
        enabledIntegrations: includeIntegrations ? enabledIntegrations : [],
      });
      const channel = await createChannel.mutateAsync(body);
      if (includeIntegrations) await applyPendingBindings(channel.id);
      navigate(`/channels/${channel.id}`);
    } catch (err) {
      setLocalError(mutationMessage(err, "Failed to create channel"));
    }
  };

  const primaryActionLabel = isCreating ? "Creating..." : "Create channel";

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="detail"
        title="New Channel"
        subtitle="Choose the bot first, then name the workspace thread."
        parentLabel="Channels"
        onBack={goBack}
        chrome="flow"
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-28 pt-4 sm:px-6 lg:px-8 lg:pb-8">
        <div className="mx-auto grid w-full max-w-[1180px] gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <main className="flex min-w-0 flex-col gap-6">
            <section className="rounded-md bg-surface-raised/35 p-4 sm:p-5">
              <SettingsGroupLabel label="Primary bot" icon={<Bot size={13} className="text-accent" />} />
              <div className="mt-2 flex flex-col gap-4">
                <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="text-[18px] font-semibold leading-tight text-text">Who should run this channel?</h2>
                    <p className="mt-1 max-w-[62ch] text-[13px] leading-relaxed text-text-muted">
                      Every channel has one primary bot. You can add member bots later from channel settings.
                    </p>
                  </div>
                  <SettingsSegmentedControl
                    value={botMode}
                    onChange={(next) => {
                      setBotMode(next);
                      setLocalError(null);
                    }}
                    options={[
                      { value: "existing", label: "Existing", icon: <Bot size={13} /> },
                      ...(isAdmin ? [{ value: "create" as const, label: "Create bot", icon: <Sparkles size={13} /> }] : []),
                    ]}
                    className="self-start"
                  />
                </div>

                {botMode === "existing" ? (
                  <div className="grid gap-3">
                    <FormRow label="Bot" description={requestedBotId && !requestedBotExists ? `The requested bot "${requestedBotId}" is not available.` : undefined}>
                      <BotPicker
                        value={botId}
                        onChange={(next) => {
                          setBotId(next);
                          setLocalError(null);
                        }}
                        bots={botList}
                        placeholder="Choose a primary bot..."
                      />
                    </FormRow>
                    {selectedBot ? (
                      <SettingsControlRow
                        leading={<Bot size={15} />}
                        title={selectedBot.name}
                        description={`${selectedBot.id} · ${shortModel(selectedBot.model)}`}
                        meta={
                          <span className="flex items-center gap-1.5">
                            {(selectedBot.local_tools?.length ?? 0) > 0 && <QuietPill label={`${selectedBot.local_tools?.length ?? 0} tools`} tone="info" />}
                            {(selectedBot.skills?.length ?? 0) > 0 && <QuietPill label={`${selectedBot.skills?.length ?? 0} skills`} />}
                          </span>
                        }
                        active
                      />
                    ) : (
                      <InfoBanner variant="info" icon={<ChevronRight size={14} />}>
                        Pick an existing bot before creating the channel.
                      </InfoBanner>
                    )}
                  </div>
                ) : (
                  <div className="grid gap-4">
                    <div className="grid gap-3 md:grid-cols-2">
                      <FormRow label="Bot name">
                        <TextInput
                          value={newBotName}
                          onChangeText={(value) => {
                            setNewBotName(value);
                            if (!name.trim()) setName(value);
                            setLocalError(null);
                          }}
                          placeholder="Kitchen Assistant"
                        />
                      </FormRow>
                      <FormRow label="Primary model">
                        <LlmModelDropdown
                          value={newBotModel}
                          selectedProviderId={newBotModelProviderId}
                          onChange={(model, providerId) => {
                            setNewBotModel(model);
                            setNewBotModelProviderId(providerId);
                            setLocalError(null);
                          }}
                          allowClear={false}
                        />
                      </FormRow>
                    </div>
                    <FormRow
                      label="Bot ID"
                      description="Stable id used by APIs and channel settings. It is generated from the name until you edit it."
                    >
                      <TextInput
                        value={newBotId}
                        onChangeText={(value) => {
                          setNewBotIdTouched(true);
                          setNewBotId(value);
                          setLocalError(null);
                        }}
                        placeholder="kitchen-assistant"
                      />
                    </FormRow>
                    {newBotError && <InfoBanner variant="warning">{newBotError}</InfoBanner>}
                  </div>
                )}
              </div>
            </section>

            <section className="flex flex-col gap-4">
              <SettingsGroupLabel label="Channel details" icon={<Hash size={13} className="text-text-dim" />} />
              <div className="grid gap-4 rounded-md bg-surface-raised/30 p-4 sm:p-5">
                <FormRow label="Channel name">
                  <TextInput
                    value={name}
                    onChangeText={(value) => {
                      setName(value);
                      setLocalError(null);
                    }}
                    placeholder="kitchen"
                  />
                </FormRow>

                <div className="grid gap-4 md:grid-cols-2">
                  <FormRow label="Category" description="Optional grouping for the channel list.">
                    <TextInput
                      value={category}
                      onChangeText={setCategory}
                      placeholder="Home, Work, Projects"
                    />
                    {categorySuggestions.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {categorySuggestions.slice(0, 5).map((candidate) => (
                          <button
                            key={candidate}
                            type="button"
                            onClick={() => setCategory(candidate)}
                            className="rounded-full bg-surface-overlay px-2 py-1 text-[11px] font-medium text-text-muted transition-colors hover:text-text"
                          >
                            {candidate}
                          </button>
                        ))}
                      </div>
                    )}
                  </FormRow>

                  {isAdmin && (
                    <FormRow label="Owner" description="Also used as the owner for an inline-created bot.">
                      <UserSelect value={ownerUserId} onChange={setOwnerUserId} />
                    </FormRow>
                  )}
                </div>

                <Toggle
                  value={isPrivate}
                  onChange={setIsPrivate}
                  label="Private"
                  description="Only the owner and admins can see this channel."
                />
              </div>
            </section>

            {hasIntegrationStep && step === "integrations" && (
              <section className="flex flex-col gap-4">
                <SettingsGroupLabel label="Optional integrations" icon={<Plug size={13} className="text-text-dim" />} />
                <div className="grid gap-5 rounded-md bg-surface-raised/30 p-4 sm:p-5">
                  {hasBindable && (
                    <div className="flex flex-col gap-3">
                      <div>
                        <h3 className="text-[13px] font-semibold text-text">Connect external service</h3>
                        <p className="mt-1 max-w-[65ch] text-[12px] leading-relaxed text-text-dim">
                          Route this channel to Slack, messaging, voice, or another external surface. You can add this later.
                        </p>
                      </div>
                      <BindableIntegrationsList
                        integrations={bindableIntegrations}
                        pending={pendingBindings}
                        onSubmit={handleBindingSubmit}
                        onRemove={handleBindingRemove}
                      />
                    </div>
                  )}

                  {hasActivatable && (
                    <div className="flex flex-col gap-3">
                      <div>
                        <h3 className="text-[13px] font-semibold text-text">Activate integrations</h3>
                        <p className="mt-1 max-w-[65ch] text-[12px] leading-relaxed text-text-dim">
                          Add integration tools and skills to the channel at creation time.
                        </p>
                      </div>
                      <IntegrationActivationList
                        integrations={activatableIntegrations ?? []}
                        enabled={enabledIntegrations}
                        onToggle={handleToggleIntegration}
                      />
                    </div>
                  )}
                </div>
              </section>
            )}
          </main>

          <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
            <section className="rounded-md bg-surface-raised/35 p-4">
              <SettingsGroupLabel label="Create summary" icon={<Check size={13} className={canCreate ? "text-success" : "text-text-dim"} />} />
              <div className="mt-3 flex flex-col gap-2">
                <SettingsControlRow
                  compact
                  leading={<Bot size={14} />}
                  title={botMode === "create" ? (newBotName || "New bot") : (selectedBot?.name ?? "No bot selected")}
                  description={botMode === "create" ? `${newBotId || "bot-id"} · ${shortModel(newBotModel)}` : selectedBot ? `${selectedBot.id} · ${shortModel(selectedBot.model)}` : "Required"}
                  active={!!(botMode === "create" ? !newBotError : selectedBot)}
                />
                <SettingsControlRow
                  compact
                  leading={<Hash size={14} />}
                  title={name.trim() || "No channel name"}
                  description={category.trim() || "No category"}
                  active={!!name.trim()}
                />
                <SettingsControlRow
                  compact
                  leading={isPrivate ? <Lock size={14} /> : <UserRound size={14} />}
                  title={isPrivate ? "Private" : "Visible"}
                  description={ownerLabel && isAdmin ? `Owner ${ownerLabel}` : "Default owner"}
                />
              </div>

              {errorMessage && (
                <div className="mt-3">
                  <InfoBanner variant="danger">{errorMessage}</InfoBanner>
                </div>
              )}

              {!canCreate && (
                <div className="mt-3">
                  <InfoBanner variant="info">{cannotCreateReason}</InfoBanner>
                </div>
              )}

              <div className="mt-4 flex flex-col gap-2">
                <ActionButton
                  label={primaryActionLabel}
                  icon={<Check size={14} />}
                  disabled={!canCreate || isCreating}
                  onPress={() => void createChannelWithOptions({ includeIntegrations: step === "integrations" })}
                />
                {hasIntegrationStep && (
                  <ActionButton
                    label={step === "integrations" ? "Skip integrations" : "Set up integrations"}
                    variant="secondary"
                    icon={step === "integrations" ? <ArrowLeft size={14} /> : <Plug size={14} />}
                    disabled={!canCreate || isCreating}
                    onPress={() => {
                      if (step === "integrations") {
                        void createChannelWithOptions({ includeIntegrations: false });
                      } else {
                        setStep("integrations");
                      }
                    }}
                  />
                )}
              </div>
            </section>

            <section className="rounded-md bg-surface-raised/25 p-4">
              <SettingsGroupLabel label="What happens next" />
              <div className="mt-2 space-y-2 text-[12px] leading-relaxed text-text-muted">
                <p>The channel opens immediately with its primary bot and an active session.</p>
                <p>Member bots, prompts, permissions, and integrations can be tuned from channel settings after creation.</p>
              </div>
            </section>
          </aside>
        </div>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-surface-border bg-surface/95 px-4 py-3 backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-[1180px] items-center gap-2">
          <ActionButton
            label={primaryActionLabel}
            icon={<Check size={14} />}
            disabled={!canCreate || isCreating}
            onPress={() => void createChannelWithOptions({ includeIntegrations: step === "integrations" })}
          />
          {hasIntegrationStep && (
            <ActionButton
              label={step === "integrations" ? "Skip" : "Integrations"}
              variant="secondary"
              icon={<Plug size={14} />}
              disabled={!canCreate || isCreating}
              onPress={() => {
                if (step === "integrations") {
                  void createChannelWithOptions({ includeIntegrations: false });
                } else {
                  setStep("integrations");
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
