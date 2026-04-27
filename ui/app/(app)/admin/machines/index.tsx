import { useEffect, useMemo, useState } from "react";
import { Copy, Download, ExternalLink, KeyRound, Monitor, Pencil, Plug, RefreshCw, SearchCheck, Trash2 } from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";
import { Section, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useAdminMachines,
  useCreateMachineProfile,
  useDeleteMachineProfile,
  useDeleteMachineTarget,
  useEnrollMachineTarget,
  useMachineTargetSetup,
  useProbeMachineTarget,
  useUpdateMachineProfile,
  type MachineControlEnrollField,
  type MachineProviderProfile,
  type MachineProviderState,
  type MachineTarget,
} from "@/src/api/hooks/useMachineTargets";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import {
  MachineEnrollFields,
  buildMachineEnrollDraft,
  normalizeMachineEnrollConfig,
  type MachineEnrollDraft,
} from "@/src/components/machineControl/MachineEnrollFields";
import { ProfileSetupGuide } from "@/src/components/machineControl/ProfileSetupGuide";

function formatDateTime(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

function targetStateText(target: MachineTarget): string {
  return target.status_label || (target.ready ? "Ready" : "Unavailable");
}

function targetStatusVariant(target: MachineTarget): "success" | "warning" | "danger" | "neutral" {
  if (target.ready) return "success";
  if (target.status === "error") return "danger";
  if (target.status === "probing" || target.status === "connecting") return "warning";
  return "neutral";
}

function initialDraft(fields?: MachineControlEnrollField[] | null): MachineEnrollDraft {
  return buildMachineEnrollDraft(fields);
}

function profileConfiguredSecrets(profile: MachineProviderProfile): string[] {
  const configured = profile.metadata?.configured_secrets;
  return Array.isArray(configured) ? configured.map((value) => String(value)) : [];
}

function buildMachineStarterPrompt(target: MachineTarget): string {
  return [
    `Use machine control with the target "${target.label || target.target_id}" in this session.`,
    "Start by calling machine_status so I can grant the session lease if needed.",
    "Use machine_inspect_command for readonly discovery first.",
    "Use machine_exec_command only when real execution on that machine is necessary; if approval is required, wait for me to approve it.",
  ].join(" ");
}

function ProviderSection({ provider }: { provider: MachineProviderState }) {
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const enroll = useEnrollMachineTarget(provider.provider_id);
  const setup = useMachineTargetSetup(provider.provider_id);
  const remove = useDeleteMachineTarget(provider.provider_id);
  const probe = useProbeMachineTarget(provider.provider_id);
  const createProfile = useCreateMachineProfile(provider.provider_id);
  const updateProfile = useUpdateMachineProfile(provider.provider_id);
  const deleteProfile = useDeleteMachineProfile(provider.provider_id);

  const [labelDraft, setLabelDraft] = useState("");
  const [configDraft, setConfigDraft] = useState<MachineEnrollDraft>(() => initialDraft(provider.enroll_fields));
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [profileLabelDraft, setProfileLabelDraft] = useState("");
  const [profileConfigDraft, setProfileConfigDraft] = useState<MachineEnrollDraft>(() => initialDraft(provider.profile_fields));

  const profiles = provider.profiles ?? [];
  const effectiveEnrollFields = useMemo<MachineControlEnrollField[]>(() => {
    const fields = [...(provider.enroll_fields ?? [])];
    if (provider.supports_profiles) {
      fields.unshift({
        key: "profile_id",
        type: "select",
        label: "Profile",
        description: "Credentials and trust profile for this target.",
        required: true,
        options: profiles.map((profile) => ({ value: profile.profile_id, label: profile.label })),
      });
    }
    return fields;
  }, [profiles, provider.enroll_fields, provider.supports_profiles]);

  useEffect(() => {
    setConfigDraft(initialDraft(effectiveEnrollFields));
  }, [provider.provider_id, JSON.stringify(effectiveEnrollFields)]);

  useEffect(() => {
    setProfileConfigDraft(initialDraft(provider.profile_fields));
    setProfileLabelDraft("");
    setEditingProfileId(null);
  }, [provider.provider_id, JSON.stringify(provider.profile_fields)]);

  const profilePending = createProfile.isPending || updateProfile.isPending || deleteProfile.isPending;
  const pending = enroll.isPending || setup.isPending || remove.isPending || probe.isPending || profilePending;
  const launch = enroll.data?.launch ?? null;
  const targetConfig = normalizeMachineEnrollConfig(effectiveEnrollFields, configDraft);
  const profileConfig = normalizeMachineEnrollConfig(provider.profile_fields, profileConfigDraft);
  const canEnrollTargets = provider.config_ready && (!provider.supports_profiles || profiles.length > 0);
  const editingProfile = editingProfileId
    ? profiles.find((profile) => profile.profile_id === editingProfileId) ?? null
    : null;

  async function handleCopy(command: string) {
    await writeToClipboard(command);
    setCopiedKey("launch");
    window.setTimeout(() => setCopiedKey(null), 1200);
  }

  async function handleCopyTargetSetup(target: MachineTarget, kind: "launch" | "service") {
    const result = await setup.mutateAsync(target.target_id);
    const payload = result.setup ?? {};
    const command = kind === "service" ? payload.install_systemd_user_command : payload.launch_command;
    if (!command) return;
    await writeToClipboard(command);
    setCopiedKey(`${target.target_id}:${kind}`);
    window.setTimeout(() => setCopiedKey(null), 1200);
  }

  async function handleCopyStarterPrompt(target: MachineTarget) {
    await writeToClipboard(buildMachineStarterPrompt(target));
    setCopiedKey(`${target.target_id}:prompt`);
    window.setTimeout(() => setCopiedKey(null), 1200);
  }

  function handleStartEditProfile(profile: MachineProviderProfile) {
    setEditingProfileId(profile.profile_id);
    setProfileLabelDraft(profile.label);
    setProfileConfigDraft(initialDraft(provider.profile_fields));
  }

  function handleCancelEditProfile() {
    setEditingProfileId(null);
    setProfileLabelDraft("");
    setProfileConfigDraft(initialDraft(provider.profile_fields));
  }

  async function handleRemove(targetId: string, label: string) {
    const accepted = await confirm(
      `Remove ${label} from ${provider.label}? This revokes any active lease and disconnects the target until it is enrolled again.`,
      { title: "Remove machine target?", confirmLabel: "Remove", variant: "danger" },
    );
    if (accepted) await remove.mutateAsync(targetId);
  }

  async function handleDeleteProfile(profile: MachineProviderProfile) {
    if (profile.target_count > 0) return;
    const accepted = await confirm(
      `Delete profile ${profile.label}? Targets using this profile will no longer be able to connect until a replacement profile is assigned.`,
      { title: "Delete machine profile?", confirmLabel: "Delete", variant: "danger" },
    );
    if (!accepted) return;
    await deleteProfile.mutateAsync(profile.profile_id);
    if (editingProfileId === profile.profile_id) handleCancelEditProfile();
  }

  async function handleSubmitProfile() {
    if (editingProfileId) {
      await updateProfile.mutateAsync({
        profileId: editingProfileId,
        body: { label: profileLabelDraft || null, config: profileConfig },
      });
    } else {
      await createProfile.mutateAsync({
        label: profileLabelDraft || null,
        config: profileConfig,
      });
    }
    handleCancelEditProfile();
  }

  return (
    <>
      <ConfirmDialogSlot />
      <Section
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span>{provider.label}</span>
            <StatusBadge
              label={`${provider.ready_target_count}/${provider.target_count} ready`}
              variant={provider.ready_target_count > 0 ? "success" : "neutral"}
            />
            {provider.supports_profiles && <QuietPill label={`${profiles.length} profiles`} />}
          </span>
        }
        description={`Driver ${provider.driver} from ${provider.integration_name}. Session-level machine leases are granted from chat; profiles and targets are managed here.`}
        action={
          <a
            href={provider.integration_admin_href}
            className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
          >
            Integration settings
            <ExternalLink size={12} />
          </a>
        }
      >
        <div className="flex flex-col gap-5">
          {!provider.config_ready && (
            <InfoBanner variant="warning">
              Provider setup is incomplete. Configure required provider-wide settings on the integration page, then return here.
            </InfoBanner>
          )}

          {provider.supports_profiles && (
            <div className="flex flex-col gap-3">
              <SettingsGroupLabel label="Profiles" count={profiles.length} icon={<KeyRound size={13} className="text-text-dim" />} />
              {profiles.length === 0 ? (
                <EmptyState message="No profiles exist yet. Create one before enrolling targets for this provider." />
              ) : (
                <div className="flex flex-col gap-1.5">
                  {profiles.map((profile) => {
                    const configuredSecrets = profileConfiguredSecrets(profile);
                    return (
                      <SettingsControlRow
                        key={`${provider.provider_id}:${profile.profile_id}`}
                        leading={<KeyRound size={14} />}
                        title={profile.label}
                        description={
                          <span className="space-y-0.5">
                            <span className="block">{profile.summary || "No summary available"}</span>
                            {configuredSecrets.length > 0 && (
                              <span className="block">Secrets: {configuredSecrets.join(", ")}</span>
                            )}
                            <span className="block">
                              Created {formatDateTime(profile.created_at) ?? "unknown"}
                              {profile.updated_at ? ` · Updated ${formatDateTime(profile.updated_at) ?? profile.updated_at}` : ""}
                            </span>
                          </span>
                        }
                        meta={<QuietPill label={`${profile.target_count} targets`} />}
                        action={
                          <div className="flex flex-wrap items-center gap-1.5">
                            <ActionButton
                              label="Edit"
                              onPress={() => handleStartEditProfile(profile)}
                              variant="secondary"
                              size="small"
                              disabled={pending}
                              icon={<Pencil size={12} />}
                            />
                            <ActionButton
                              label="Delete"
                              onPress={() => void handleDeleteProfile(profile)}
                              variant="danger"
                              size="small"
                              disabled={pending || profile.target_count > 0}
                              icon={<Trash2 size={12} />}
                            />
                          </div>
                        }
                      />
                    );
                  })}
                </div>
              )}

              <div className="rounded-md bg-surface-raised/35 p-3.5">
                <div className="mb-3 text-[12px] font-semibold text-text">
                  {editingProfile ? `Edit profile: ${editingProfile.label}` : "Create profile"}
                </div>
                <div className="flex flex-col gap-3">
                  {!editingProfile && provider.profile_setup_guide && (
                    <ProfileSetupGuide guide={provider.profile_setup_guide} />
                  )}
                  <TextInput
                    value={profileLabelDraft}
                    onChangeText={setProfileLabelDraft}
                    placeholder="Profile label"
                  />
                  <MachineEnrollFields
                    fields={provider.profile_fields}
                    draft={profileConfigDraft}
                    onChange={(key, value) => setProfileConfigDraft((current) => ({ ...current, [key]: value }))}
                    disabled={pending || !provider.config_ready}
                  />
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-[11px] leading-snug text-text-dim">
                      {editingProfile
                        ? "Leave secret fields blank to preserve their current values."
                        : "Profiles carry provider-specific credentials and trust material."}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {editingProfile && (
                        <ActionButton
                          label="Cancel"
                          onPress={handleCancelEditProfile}
                          variant="secondary"
                          size="small"
                          disabled={pending}
                        />
                      )}
                      <ActionButton
                        label={editingProfile ? (updateProfile.isPending ? "Saving..." : "Save profile") : (createProfile.isPending ? "Creating..." : "Create profile")}
                        onPress={() => void handleSubmitProfile()}
                        disabled={pending || !provider.config_ready}
                        size="small"
                        icon={<KeyRound size={13} />}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {provider.supports_enroll && (
            <div className="flex flex-col gap-3">
              <SettingsGroupLabel label="Enroll target" icon={<Plug size={13} className="text-text-dim" />} />
              <div className="rounded-md bg-surface-raised/35 p-3.5">
                <div className="flex flex-col gap-3">
                  <TextInput
                    value={labelDraft}
                    onChangeText={setLabelDraft}
                    placeholder="Optional machine label"
                  />
                  <MachineEnrollFields
                    fields={effectiveEnrollFields}
                    draft={configDraft}
                    onChange={(key, value) => setConfigDraft((current) => ({ ...current, [key]: value }))}
                    disabled={pending || !canEnrollTargets}
                  />
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-[11px] leading-snug text-text-dim">
                      {!provider.config_ready
                        ? "Provider setup is incomplete."
                        : provider.supports_profiles && profiles.length === 0
                          ? "Create a profile before enrolling targets for this provider."
                          : effectiveEnrollFields.length
                            ? "Enter provider-specific target details, then enroll the machine."
                            : "Enroll a new machine target for this provider."}
                    </div>
                    <ActionButton
                      label={enroll.isPending ? "Enrolling..." : "Enroll machine"}
                      onPress={() => enroll.mutate({ label: labelDraft || null, config: targetConfig })}
                      disabled={pending || !canEnrollTargets}
                      size="small"
                      icon={<Plug size={13} />}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {launch?.example_command && (
            <div className="flex flex-col gap-2 rounded-md bg-surface-raised/35 p-3.5">
              <SettingsGroupLabel label="Launch command" />
              <code className="block break-words rounded-md bg-surface-overlay/35 px-3 py-2 font-mono text-[12px] text-text">
                {launch.example_command}
              </code>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[11px] text-text-dim">
                  Run this on the target machine to finish provider-specific setup.
                </div>
                <ActionButton
                  label={copiedKey === "launch" ? "Copied" : "Copy command"}
                  onPress={() => void handleCopy(launch.example_command || "")}
                  variant="secondary"
                  size="small"
                  icon={<Copy size={12} />}
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3">
            <SettingsGroupLabel label="Targets" count={provider.targets.length} icon={<Monitor size={13} className="text-text-dim" />} />
            {provider.targets.length === 0 ? (
              <EmptyState message="No enrolled machine targets yet." />
            ) : (
              <div className="flex flex-col gap-1.5">
                {provider.targets.map((target) => (
                  <SettingsControlRow
                    key={`${target.provider_id}:${target.target_id}`}
                    leading={<Monitor size={14} />}
                    title={
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate">{target.label}</span>
                        <StatusBadge label={targetStateText(target)} variant={targetStatusVariant(target)} />
                      </span>
                    }
                    description={
                      <span className="space-y-0.5">
                        <span className="block">{[target.hostname, target.platform].filter(Boolean).join(" · ") || target.target_id}</span>
                        {target.profile_label && <span className="block">Profile: {target.profile_label}</span>}
                        {target.reason && <span className="block">{target.reason}</span>}
                        <span className="block">Capabilities: {target.capabilities.join(", ") || "none"}</span>
                        <span className="block">
                          Enrolled {formatDateTime(target.enrolled_at) ?? "unknown"}
                          {target.checked_at ? ` · Checked ${formatDateTime(target.checked_at) ?? target.checked_at}` : ""}
                          {target.last_seen_at ? ` · Last success ${formatDateTime(target.last_seen_at) ?? target.last_seen_at}` : ""}
                        </span>
                      </span>
                    }
                    action={
                      <div className="flex flex-wrap items-center gap-1.5">
                        {target.ready && (
                          <ActionButton
                            label={copiedKey === `${target.target_id}:prompt` ? "Copied" : "Copy prompt"}
                            onPress={() => void handleCopyStarterPrompt(target)}
                            variant="secondary"
                            size="small"
                            disabled={pending}
                            icon={<Copy size={12} />}
                          />
                        )}
                        {target.driver === "companion" && (
                          <>
                            <ActionButton
                              label={copiedKey === `${target.target_id}:launch` ? "Copied" : "Copy launcher"}
                              onPress={() => void handleCopyTargetSetup(target, "launch")}
                              variant="secondary"
                              size="small"
                              disabled={pending}
                              icon={<Copy size={12} />}
                            />
                            <ActionButton
                              label={copiedKey === `${target.target_id}:service` ? "Copied" : "Copy service install"}
                              onPress={() => void handleCopyTargetSetup(target, "service")}
                              variant="secondary"
                              size="small"
                              disabled={pending}
                              icon={<Download size={12} />}
                            />
                          </>
                        )}
                        <ActionButton
                          label="Probe"
                          onPress={() => probe.mutate(target.target_id)}
                          variant="secondary"
                          size="small"
                          disabled={pending || !provider.config_ready}
                          icon={<SearchCheck size={12} />}
                        />
                        {provider.supports_remove_target && (
                          <ActionButton
                            label="Remove"
                            onPress={() => void handleRemove(target.target_id, target.label)}
                            variant="danger"
                            size="small"
                            disabled={pending}
                            icon={<Trash2 size={12} />}
                          />
                        )}
                      </div>
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </Section>
    </>
  );
}

export default function AdminMachinesPage() {
  const { data, isLoading, refetch, isFetching } = useAdminMachines(true);
  const providers = useMemo(() => data?.providers ?? [], [data]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Machines"
        subtitle="Manage provider profiles, target enrollment, and readiness probes."
        right={
          <ActionButton
            label={isFetching ? "Refreshing" : "Refresh"}
            onPress={() => void refetch()}
            variant="secondary"
            size="small"
            icon={<RefreshCw size={14} />}
          />
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-7 px-4 py-5 md:px-6">
          <div className="max-w-[72ch] text-[13px] leading-relaxed text-text-dim">
            Machine profile management, target enrollment, probing, and removal live here. Session leases are granted from chat, and exec-capable commands may still ask for approval.
          </div>
          <InfoBanner variant="info">
            Local Companion pairs this workstation through an outbound reconnecting process. SSH controls headless or LAN machines through explicit key and known_hosts profiles.
          </InfoBanner>

          {isLoading ? (
            <div className="flex min-h-[180px] items-center justify-center">
              <Spinner />
            </div>
          ) : providers.length === 0 ? (
            <EmptyState message="No machine-control providers are available." />
          ) : (
            <div className="flex flex-col gap-7">
              {providers.map((provider) => (
                <ProviderSection key={provider.provider_id} provider={provider} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
