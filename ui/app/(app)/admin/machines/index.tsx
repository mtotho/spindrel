import { useEffect, useMemo, useState } from "react";
import { Copy, ExternalLink, Monitor, Plug, RefreshCw, SearchCheck, Trash2 } from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useAdminMachines,
  useDeleteMachineTarget,
  useEnrollMachineTarget,
  useProbeMachineTarget,
  type MachineControlEnrollField,
  type MachineTarget,
  type MachineProviderState,
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

function initialDraft(fields?: MachineControlEnrollField[] | null): MachineEnrollDraft {
  return buildMachineEnrollDraft(fields);
}

function targetStateText(target: MachineTarget): string {
  return target.status_label || (target.ready ? "Ready" : "Unavailable");
}

function ProviderSection({ provider }: { provider: MachineProviderState }) {
  const t = useThemeTokens();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const enroll = useEnrollMachineTarget(provider.provider_id);
  const remove = useDeleteMachineTarget(provider.provider_id);
  const probe = useProbeMachineTarget(provider.provider_id);
  const [labelDraft, setLabelDraft] = useState("");
  const [configDraft, setConfigDraft] = useState<MachineEnrollDraft>(() => initialDraft(provider.enroll_fields));
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setConfigDraft(initialDraft(provider.enroll_fields));
  }, [provider.enroll_fields]);

  const pending = enroll.isPending || remove.isPending || probe.isPending;
  const launch = enroll.data?.launch ?? null;
  const config = normalizeMachineEnrollConfig(provider.enroll_fields, configDraft);

  async function handleCopy(command: string) {
    await writeToClipboard(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  function handleConfigChange(key: string, value: string | boolean) {
    setConfigDraft((current) => ({ ...current, [key]: value }));
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
            Provider setup is incomplete. Configure the required settings on the integration page, then return here to enroll or probe targets.
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
              fields={provider.enroll_fields}
              draft={configDraft}
              onChange={handleConfigChange}
              disabled={pending || !provider.config_ready}
              t={t}
            />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ fontSize: 11, color: t.textDim }}>
                {provider.enroll_fields?.length
                  ? "Enter provider-specific target details, then enroll the machine."
                  : "Enroll a new machine target for this provider."}
              </div>
              <button
                type="button"
                onClick={() => enroll.mutate({ label: labelDraft || null, config })}
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
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                      {target.label}
                    </span>
                    <span style={{ fontSize: 11, color: target.ready ? t.success : t.textDim }}>
                      {targetStateText(target)}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    {[target.hostname, target.platform].filter(Boolean).join(" · ") || target.target_id}
                  </div>
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

      <div
        style={{
          flex: 1,
          overflow: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 16,
            padding: 20,
            maxWidth: 960,
            margin: "0 auto",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <div style={{ fontSize: 13, color: t.textDim, lineHeight: "20px" }}>
            Machine enrollment and target lifecycle live here. Session-level lease grant and revoke remain chat-scoped.
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
