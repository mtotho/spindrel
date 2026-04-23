import { useMemo, useState } from "react";
import { Copy, ExternalLink, Monitor, Plug, RefreshCw, Trash2 } from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useAdminMachines,
  useDeleteMachineTarget,
  useEnrollMachineTarget,
  type MachineProviderState,
} from "@/src/api/hooks/useMachineTargets";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

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

function ProviderSection({ provider }: { provider: MachineProviderState }) {
  const t = useThemeTokens();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const enroll = useEnrollMachineTarget(provider.provider_id);
  const remove = useDeleteMachineTarget(provider.provider_id);
  const [labelDraft, setLabelDraft] = useState("");
  const [copied, setCopied] = useState(false);

  const pending = enroll.isPending || remove.isPending;
  const launch = enroll.data?.launch ?? null;

  async function handleCopy(command: string) {
    await writeToClipboard(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
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
                {provider.connected_target_count}/{provider.target_count} connected
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

        {provider.supports_enroll ? (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              alignItems: "center",
              padding: 12,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
            }}
          >
            <input
              value={labelDraft}
              onChange={(event) => setLabelDraft(event.target.value)}
              placeholder="Optional machine label"
              style={{
                minWidth: 220,
                flex: "1 1 220px",
                borderRadius: 6,
                border: `1px solid ${t.inputBorder}`,
                background: t.inputBg,
                color: t.text,
                padding: "8px 10px",
                fontSize: 12,
              }}
            />
            <button
              type="button"
              onClick={() => enroll.mutate({ label: labelDraft || null })}
              disabled={pending}
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
                opacity: pending ? 0.7 : 1,
              }}
            >
              <Plug size={14} />
              Enroll machine
            </button>
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
                    <Monitor size={14} color={target.connected ? t.accent : t.textDim} />
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                      {target.label}
                    </span>
                    <span style={{ fontSize: 11, color: target.connected ? t.success : t.textDim }}>
                      {target.connected ? "Connected" : "Offline"}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    {[target.hostname, target.platform].filter(Boolean).join(" · ") || target.target_id}
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    Capabilities: {target.capabilities.join(", ") || "none"}
                  </div>
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    Enrolled {formatDateTime(target.enrolled_at) ?? "unknown"}
                    {target.last_seen_at ? ` · Last seen ${formatDateTime(target.last_seen_at) ?? target.last_seen_at}` : ""}
                  </div>
                </div>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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
  );
}
