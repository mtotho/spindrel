import { useEffect, useMemo, useState } from "react";
import { Copy, ExternalLink, KeyRound, Monitor, Pencil, Plug, RefreshCw, SearchCheck, Trash2 } from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useAdminMachines,
  useCreateMachineProfile,
  useDeleteMachineProfile,
  useDeleteMachineTarget,
  useEnrollMachineTarget,
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

function SectionCard({ children }: { children: React.ReactNode }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 16,
        borderRadius: 10,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.inputBg,
      }}
    >
      {children}
    </div>
  );
}

function formatDateTime(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

function targetStateText(target: MachineTarget): string {
  return target.status_label || (target.ready ? "Ready" : "Unavailable");
}

function initialDraft(fields?: MachineControlEnrollField[] | null): MachineEnrollDraft {
  return buildMachineEnrollDraft(fields);
}

function profileConfiguredSecrets(profile: MachineProviderProfile): string[] {
  const configured = profile.metadata?.configured_secrets;
  return Array.isArray(configured) ? configured.map((value) => String(value)) : [];
}

function ProviderSection({ provider }: { provider: MachineProviderState }) {
  const t = useThemeTokens();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const enroll = useEnrollMachineTarget(provider.provider_id);
  const remove = useDeleteMachineTarget(provider.provider_id);
  const probe = useProbeMachineTarget(provider.provider_id);
  const createProfile = useCreateMachineProfile(provider.provider_id);
  const updateProfile = useUpdateMachineProfile(provider.provider_id);
  const deleteProfile = useDeleteMachineProfile(provider.provider_id);

  const [labelDraft, setLabelDraft] = useState("");
  const [configDraft, setConfigDraft] = useState<MachineEnrollDraft>(() => initialDraft(provider.enroll_fields));
  const [copied, setCopied] = useState(false);

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
        description: "Choose the credentials/trust profile for this target",
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
  const pending = enroll.isPending || remove.isPending || probe.isPending || profilePending;
  const launch = enroll.data?.launch ?? null;
  const targetConfig = normalizeMachineEnrollConfig(effectiveEnrollFields, configDraft);
  const profileConfig = normalizeMachineEnrollConfig(provider.profile_fields, profileConfigDraft);
  const canEnrollTargets = provider.config_ready && (!provider.supports_profiles || profiles.length > 0);

  async function handleCopy(command: string) {
    await writeToClipboard(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  function handleConfigChange(key: string, value: string | boolean) {
    setConfigDraft((current) => ({ ...current, [key]: value }));
  }

  function handleProfileConfigChange(key: string, value: string | boolean) {
    setProfileConfigDraft((current) => ({ ...current, [key]: value }));
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
      {
        title: "Remove machine target?",
        confirmLabel: "Remove",
        variant: "danger",
      },
    );
    if (!accepted) return;
    await remove.mutateAsync(targetId);
  }

  async function handleDeleteProfile(profile: MachineProviderProfile) {
    if (profile.target_count > 0) return;
    const accepted = await confirm(
      `Delete profile ${profile.label}? Targets using this profile will no longer be able to connect until a replacement profile is assigned.`,
      {
        title: "Delete machine profile?",
        confirmLabel: "Delete",
        variant: "danger",
      },
    );
    if (!accepted) return;
    await deleteProfile.mutateAsync(profile.profile_id);
    if (editingProfileId === profile.profile_id) handleCancelEditProfile();
  }

  async function handleSubmitProfile() {
    if (editingProfileId) {
      await updateProfile.mutateAsync({
        profileId: editingProfileId,
        body: {
          label: profileLabelDraft || null,
          config: profileConfig,
        },
      });
    } else {
      await createProfile.mutateAsync({
        label: profileLabelDraft || null,
        config: profileConfig,
      });
    }
    handleCancelEditProfile();
  }

  const editingProfile = editingProfileId
    ? profiles.find((profile) => profile.profile_id === editingProfileId) ?? null
    : null;

  return (
    <>
      <ConfirmDialogSlot />
      <SectionCard>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>{provider.label}</span>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {provider.ready_target_count}/{provider.target_count} ready
              </span>
              {provider.supports_profiles ? (
                <span style={{ fontSize: 11, color: t.textDim }}>
                  {profiles.length} profile{profiles.length === 1 ? "" : "s"}
                </span>
              ) : null}
            </div>
            <div style={{ fontSize: 12, color: t.textDim }}>
              Driver: {provider.driver} · Integration: {provider.integration_name} · Status: {provider.integration_status}
            </div>
          </div>
          <a
            href={provider.integration_admin_href}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              fontWeight: 600,
              color: t.accent,
              textDecoration: "none",
            }}
          >
            Integration settings
            <ExternalLink size={12} />
          </a>
        </div>

        {!provider.config_ready ? (
          <div
            style={{
              padding: 12,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
              fontSize: 12,
              color: t.textDim,
            }}
          >
            Provider setup is incomplete. Configure the required provider-wide settings on the integration page, then return here to manage profiles and targets.
          </div>
        ) : null}

        {provider.supports_profiles ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
              padding: 12,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <KeyRound size={14} color={t.accent} />
              <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Profiles</div>
            </div>

            {profiles.length === 0 ? (
              <div style={{ fontSize: 12, color: t.textDim }}>
                No profiles exist yet. Create one before enrolling targets for this provider.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                {profiles.map((profile, index) => (
                  <div
                    key={`${provider.provider_id}:${profile.profile_id}`}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 12,
                      padding: "12px 0",
                      borderTop: index === 0 ? "none" : `1px solid ${t.surfaceBorder}`,
                    }}
                  >
                    <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{profile.label}</span>
                        <span style={{ fontSize: 11, color: t.textDim }}>
                          {profile.target_count} target{profile.target_count === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: t.textDim }}>
                        {profile.summary || "No summary available"}
                      </div>
                      {profileConfiguredSecrets(profile).length ? (
                        <div style={{ fontSize: 11, color: t.textDim }}>
                          Secrets: {profileConfiguredSecrets(profile).join(", ")}
                        </div>
                      ) : null}
                      <div style={{ fontSize: 11, color: t.textDim }}>
                        Created {formatDateTime(profile.created_at) ?? "unknown"}
                        {profile.updated_at ? ` · Updated ${formatDateTime(profile.updated_at) ?? profile.updated_at}` : ""}
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <button
                        type="button"
                        onClick={() => handleStartEditProfile(profile)}
                        disabled={pending}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          borderRadius: 6,
                          border: `1px solid ${t.surfaceBorder}`,
                          background: "transparent",
                          color: t.text,
                          padding: "6px 10px",
                          fontSize: 12,
                          fontWeight: 700,
                          opacity: pending ? 0.7 : 1,
                        }}
                      >
                        <Pencil size={12} />
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDeleteProfile(profile)}
                        disabled={pending || profile.target_count > 0}
                        title={profile.target_count > 0 ? "Move or remove the targets using this profile before deleting it." : undefined}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          borderRadius: 6,
                          border: `1px solid ${t.danger}`,
                          background: t.dangerSubtle,
                          color: t.danger,
                          padding: "6px 10px",
                          fontSize: 12,
                          fontWeight: 700,
                          opacity: pending || profile.target_count > 0 ? 0.55 : 1,
                        }}
                      >
                        <Trash2 size={12} />
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 10,
                padding: 12,
                borderRadius: 8,
                border: `1px solid ${t.surfaceBorder}`,
                background: t.inputBg,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>
                {editingProfile ? `Edit Profile: ${editingProfile.label}` : "Create profile"}
              </div>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: t.textDim }}>Label</span>
                <input
                  value={profileLabelDraft}
                  onChange={(event) => setProfileLabelDraft(event.target.value)}
                  placeholder="Profile label"
                  style={{
                    minHeight: 36,
                    borderRadius: 6,
                    border: `1px solid ${t.inputBorder}`,
                    background: t.inputBg,
                    color: t.text,
                    padding: "8px 10px",
                    fontSize: 12,
                  }}
                />
              </label>
              <MachineEnrollFields
                fields={provider.profile_fields}
                draft={profileConfigDraft}
                onChange={handleProfileConfigChange}
                disabled={pending || !provider.config_ready}
                t={t}
              />
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ fontSize: 11, color: t.textDim }}>
                  {editingProfile
                    ? "Leave any secret field blank to preserve its current value."
                    : "Profiles provide provider-specific credentials and trust data for targets."}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {editingProfile ? (
                    <button
                      type="button"
                      onClick={handleCancelEditProfile}
                      disabled={pending}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        borderRadius: 6,
                        border: `1px solid ${t.surfaceBorder}`,
                        background: "transparent",
                        color: t.text,
                        padding: "8px 12px",
                        fontSize: 12,
                        fontWeight: 700,
                        opacity: pending ? 0.7 : 1,
                      }}
                    >
                      Cancel
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleSubmitProfile()}
                    disabled={pending || !provider.config_ready}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      borderRadius: 6,
                      border: `1px solid ${t.accentBorder}`,
                      background: t.accentSubtle,
                      color: t.accent,
                      padding: "8px 12px",
                      fontSize: 12,
                      fontWeight: 700,
                      opacity: pending || !provider.config_ready ? 0.7 : 1,
                    }}
                  >
                    <KeyRound size={14} />
                    {editingProfile ? (updateProfile.isPending ? "Saving..." : "Save profile") : (createProfile.isPending ? "Creating..." : "Create profile")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {provider.supports_enroll ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              padding: 12,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
            }}
          >
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", width: "100%" }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: t.textDim }}>Label</span>
                <input
                  value={labelDraft}
                  onChange={(event) => setLabelDraft(event.target.value)}
                  placeholder="Optional machine label"
                  style={{
                    minHeight: 36,
                    borderRadius: 6,
                    border: `1px solid ${t.inputBorder}`,
                    background: t.inputBg,
                    color: t.text,
                    padding: "8px 10px",
                    fontSize: 12,
                  }}
                />
              </label>
            </div>
            <MachineEnrollFields
              fields={effectiveEnrollFields}
              draft={configDraft}
              onChange={handleConfigChange}
              disabled={pending || !canEnrollTargets}
              t={t}
            />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ fontSize: 11, color: t.textDim }}>
                {!provider.config_ready
                  ? "Provider setup is incomplete."
                  : provider.supports_profiles && profiles.length === 0
                    ? "Create a profile before enrolling targets for this provider."
                    : effectiveEnrollFields.length
                      ? "Enter provider-specific target details, then enroll the machine."
                      : "Enroll a new machine target for this provider."}
              </div>
              <button
                type="button"
                onClick={() => enroll.mutate({ label: labelDraft || null, config: targetConfig })}
                disabled={pending || !canEnrollTargets}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  borderRadius: 6,
                  border: `1px solid ${t.accentBorder}`,
                  background: t.accentSubtle,
                  color: t.accent,
                  padding: "8px 12px",
                  fontSize: 12,
                  fontWeight: 700,
                  opacity: pending || !canEnrollTargets ? 0.7 : 1,
                }}
              >
                <Plug size={14} />
                {enroll.isPending ? "Enrolling..." : "Enroll machine"}
              </button>
            </div>
          </div>
        ) : null}

        {launch?.example_command ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              padding: 12,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Launch command</div>
            <code
              style={{
                display: "block",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                color: t.text,
              }}
            >
              {launch.example_command}
            </code>
            <div>
              <button
                type="button"
                onClick={() => void handleCopy(launch.example_command || "")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  borderRadius: 6,
                  border: `1px solid ${t.surfaceBorder}`,
                  background: "transparent",
                  color: copied ? t.success : t.text,
                  padding: "6px 10px",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                <Copy size={12} />
                {copied ? "Copied" : "Copy command"}
              </button>
            </div>
            <div style={{ fontSize: 11, color: t.textDim }}>
              Run that on the target machine to finish provider-specific setup for this target.
            </div>
          </div>
        ) : null}

        {provider.targets.length === 0 ? (
          <div style={{ fontSize: 12, color: t.textDim }}>
            No enrolled machine targets yet.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {provider.targets.map((target, index) => (
              <div
                key={`${target.provider_id}:${target.target_id}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 0",
                  borderTop: index === 0 ? "none" : `1px solid ${t.surfaceBorder}`,
                }}
              >
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Monitor size={14} color={target.ready ? t.accent : t.textDim} />
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{target.label}</span>
                    <span style={{ fontSize: 11, color: target.ready ? t.success : t.textDim }}>
                      {targetStateText(target)}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    {[target.hostname, target.platform].filter(Boolean).join(" · ") || target.target_id}
                  </div>
                  {target.profile_label ? (
                    <div style={{ fontSize: 11, color: t.textDim }}>
                      Profile: {target.profile_label}
                    </div>
                  ) : null}
                  {target.reason ? (
                    <div style={{ fontSize: 11, color: t.textDim }}>
                      {target.reason}
                    </div>
                  ) : null}
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    Capabilities: {target.capabilities.join(", ") || "none"}
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    Enrolled {formatDateTime(target.enrolled_at) ?? "unknown"}
                    {target.checked_at ? ` · Checked ${formatDateTime(target.checked_at) ?? target.checked_at}` : ""}
                    {target.last_seen_at ? ` · Last success ${formatDateTime(target.last_seen_at) ?? target.last_seen_at}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    onClick={() => probe.mutate(target.target_id)}
                    disabled={pending || !provider.config_ready}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      borderRadius: 6,
                      border: `1px solid ${t.surfaceBorder}`,
                      background: "transparent",
                      color: t.text,
                      padding: "6px 10px",
                      fontSize: 12,
                      fontWeight: 700,
                      opacity: pending || !provider.config_ready ? 0.7 : 1,
                    }}
                  >
                    <SearchCheck size={12} />
                    Probe
                  </button>
                  {provider.supports_remove_target ? (
                    <button
                      type="button"
                      onClick={() => void handleRemove(target.target_id, target.label)}
                      disabled={pending}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        borderRadius: 6,
                        border: `1px solid ${t.danger}`,
                        background: t.dangerSubtle,
                        color: t.danger,
                        padding: "6px 10px",
                        fontSize: 12,
                        fontWeight: 700,
                        opacity: pending ? 0.7 : 1,
                      }}
                    >
                      <Trash2 size={12} />
                      Remove
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </>
  );
}

export default function AdminMachinesPage() {
  const t = useThemeTokens();
  const { data, isLoading, refetch, isFetching } = useAdminMachines(true);
  const providers = useMemo(() => data?.providers ?? [], [data]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="detail"
        title="Machines"
        right={(
          <button
            type="button"
            onClick={() => void refetch()}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              borderRadius: 6,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent",
              color: t.text,
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            <RefreshCw size={14} />
            {isFetching ? "Refreshing" : "Refresh"}
          </button>
        )}
      />

      <div style={{ flex: 1, overflow: "auto" }}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 16,
            padding: 24,
            maxWidth: 1040,
            margin: "0 auto",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <div style={{ fontSize: 13, color: t.textDim, lineHeight: "20px" }}>
            Machine profile management, target enrollment, probing, and removal live here. Session-level lease grant and revoke remain chat-scoped.
          </div>

          {isLoading ? (
            <div style={{ padding: 24 }}>
              <Spinner />
            </div>
          ) : providers.length === 0 ? (
            <SectionCard>
              <div style={{ fontSize: 13, color: t.textDim }}>
                No machine-control providers are available.
              </div>
            </SectionCard>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
