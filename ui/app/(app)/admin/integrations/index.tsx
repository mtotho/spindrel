import { useState } from "react";
import { View, ActivityIndicator, Platform, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useIntegrations,
  useIntegrationSettings,
  useUpdateIntegrationSettings,
  useDeleteIntegrationSetting,
  useStartProcess,
  useStopProcess,
  useRestartProcess,
  useAutoStart,
  useSetAutoStart,
  useInstallDeps,
  useIntegrationApiKey,
  useProvisionIntegrationApiKey,
  useRevokeIntegrationApiKey,
  type IntegrationItem,
  type IntegrationEnvVar,
} from "@/src/api/hooks/useIntegrations";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { Check, X, Copy, ChevronDown, ChevronRight, RotateCcw, Play, Square, RefreshCw, Download, Key, Trash2 } from "lucide-react";

const STATUS_COLORS: Record<string, { dot: string; label: string; bg: string }> = {
  ready: { dot: "#22c55e", label: "Ready", bg: "rgba(34,197,94,0.12)" },
  partial: { dot: "#eab308", label: "Partial", bg: "rgba(234,179,8,0.12)" },
  not_configured: { dot: "#6b7280", label: "Not Configured", bg: "rgba(107,114,128,0.12)" },
};

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.not_configured;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.dot,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: 4,
          background: c.dot,
          flexShrink: 0,
        }}
      />
      {c.label}
    </span>
  );
}

function EnvVarPill({ v }: { v: IntegrationEnvVar }) {
  const t = useThemeTokens();
  // Three states: green (explicitly set or has default), red (required + not set), gray (optional + not set + no default)
  const isGreen = v.is_set;
  const isRed = !v.is_set && v.required;
  // neutral gray: optional, not set, no default
  const bg = isGreen
    ? "rgba(34,197,94,0.1)"
    : isRed
      ? "rgba(239,68,68,0.1)"
      : "rgba(107,114,128,0.08)";
  const fg = isGreen ? "#22c55e" : isRed ? "#ef4444" : "#6b7280";

  return (
    <span
      title={v.description + (v.default ? ` (default: ${v.default})` : "")}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 500,
        background: bg,
        color: fg,
        fontFamily: "monospace",
      }}
    >
      {isGreen ? <Check size={10} /> : isRed ? <X size={10} /> : null}
      {v.key}
      {v.default && !isRed && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "sans-serif" }}>
          {v.default}
        </span>
      )}
      {!v.required && !v.default && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "sans-serif" }}>
          opt
        </span>
      )}
    </span>
  );
}

function CapBadge({ label, active }: { label: string; active: boolean }) {
  const t = useThemeTokens();
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "1px 6px",
        borderRadius: 3,
        background: active ? t.accentSubtle : "transparent",
        color: active ? t.accent : t.surfaceBorder,
        border: active ? "none" : `1px solid ${t.surfaceBorder}`,
      }}
    >
      {label}
    </span>
  );
}

function WebhookRow({ webhook }: { webhook: IntegrationItem["webhook"] }) {
  const t = useThemeTokens();
  const [copied, setCopied] = useState(false);
  if (!webhook) return null;

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await writeToClipboard(webhook.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
      <span style={{ color: t.textDim }}>Webhook:</span>
      <code style={{ color: t.textMuted, fontFamily: "monospace", fontSize: 11 }}>
        {webhook.path}
      </code>
      <button
        onClick={handleCopy}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 2,
          display: "flex",
          alignItems: "center",
        }}
        title="Copy full URL"
      >
        {copied ? (
          <Check size={12} color="#22c55e" />
        ) : (
          <Copy size={12} color={t.textDim} />
        )}
      </button>
    </div>
  );
}

function SourceBadge({ source }: { source: "db" | "env" | "default" }) {
  const colors: Record<string, { bg: string; color: string }> = {
    db: { bg: "rgba(59,130,246,0.12)", color: "#3b82f6" },
    env: { bg: "rgba(168,85,247,0.12)", color: "#a855f7" },
    default: { bg: "rgba(107,114,128,0.08)", color: "#6b7280" },
  };
  const c = colors[source] || colors.default;
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 600,
        padding: "1px 5px",
        borderRadius: 3,
        background: c.bg,
        color: c.color,
        textTransform: "uppercase",
        letterSpacing: 0.3,
      }}
    >
      {source}
    </span>
  );
}

function SettingsForm({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationSettings(integrationId);
  const updateMut = useUpdateIntegrationSettings(integrationId);
  const deleteMut = useDeleteIntegrationSetting(integrationId);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);

  const settings = data?.settings ?? [];

  // Initialize draft from loaded settings (once)
  if (settings.length > 0 && !initialized) {
    const initial: Record<string, string> = {};
    for (const s of settings) {
      // For secrets that are set, leave empty (placeholder will show)
      initial[s.key] = s.secret && s.is_set ? "" : (s.value ?? "");
    }
    setDraft(initial);
    setInitialized(true);
  }

  if (isLoading) {
    return (
      <div style={{ padding: 12, fontSize: 12, color: t.textDim }}>
        Loading settings...
      </div>
    );
  }

  if (settings.length === 0) {
    return (
      <div style={{ padding: 12, fontSize: 12, color: t.textDim }}>
        No configurable settings for this integration.
      </div>
    );
  }

  const handleSave = () => {
    // Only send fields that were actually changed
    const updates: Record<string, string> = {};
    for (const s of settings) {
      const val = draft[s.key] ?? "";
      // For secrets: empty string means "keep existing", so skip
      if (s.secret && s.is_set && val === "") continue;
      // For non-secrets: only send if different from current value
      if (!s.secret && val === (s.value ?? "")) continue;
      // If we got here, it's a real change
      if (val !== "" || s.source === "db") {
        updates[s.key] = val;
      }
    }
    if (Object.keys(updates).length > 0) {
      updateMut.mutate(updates);
    }
  };

  const handleReset = (key: string) => {
    deleteMut.mutate(key);
    setDraft((prev) => ({ ...prev, [key]: "" }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {settings.map((s) => (
        <div key={s.key} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <label
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: t.textMuted,
                fontFamily: "monospace",
              }}
            >
              {s.key}
            </label>
            <SourceBadge source={s.source} />
            {!s.required && (
              <span style={{ fontSize: 9, color: t.textDim }}>optional</span>
            )}
            {s.source === "db" && (
              <button
                onClick={() => handleReset(s.key)}
                title="Reset to env/default"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 2,
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <RotateCcw size={11} color={t.textDim} />
              </button>
            )}
          </div>
          <input
            type={s.secret ? "password" : "text"}
            value={draft[s.key] ?? ""}
            onChange={(e) => setDraft((prev) => ({ ...prev, [s.key]: e.target.value }))}
            placeholder={
              s.secret && s.is_set
                ? "\u2022\u2022\u2022\u2022\u2022 (unchanged)"
                : s.description
            }
            style={{
              background: t.inputBg,
              border: `1px solid ${t.inputBorder}`,
              borderRadius: 6,
              padding: "6px 10px",
              color: t.inputText,
              fontSize: 13,
              width: "100%",
              outline: "none",
            }}
            onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
            onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
          />
          {s.description && (
            <div style={{ fontSize: 11, color: t.textDim }}>{s.description}</div>
          )}
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button
          onClick={handleSave}
          disabled={updateMut.isPending}
          style={{
            padding: "6px 16px",
            borderRadius: 6,
            border: "none",
            background: t.accent,
            color: "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: updateMut.isPending ? "wait" : "pointer",
            opacity: updateMut.isPending ? 0.6 : 1,
          }}
        >
          {updateMut.isPending ? "Saving..." : "Save"}
        </button>
        {updateMut.isSuccess && (
          <span style={{ fontSize: 12, color: "#22c55e", alignSelf: "center" }}>
            Saved
          </span>
        )}
        {updateMut.isError && (
          <span style={{ fontSize: 12, color: "#ef4444", alignSelf: "center" }}>
            Error saving
          </span>
        )}
      </div>
    </div>
  );
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function ProcessControls({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const startMut = useStartProcess(integrationId);
  const stopMut = useStopProcess(integrationId);
  const restartMut = useRestartProcess(integrationId);
  const { data: autoStartData } = useAutoStart(integrationId, true);
  const setAutoStartMut = useSetAutoStart(integrationId);
  const { data: integrations } = useIntegrations();

  const item = integrations?.integrations?.find((i) => i.id === integrationId);
  const ps = item?.process_status;
  const isRunning = ps?.status === "running";
  const anyPending = startMut.isPending || stopMut.isPending || restartMut.isPending;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 10,
        background: t.surface,
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {/* Status indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              background: isRunning ? "#22c55e" : "#6b7280",
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
            {isRunning ? "Running" : "Stopped"}
          </span>
          {isRunning && ps?.pid && (
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              pid {ps.pid}
            </span>
          )}
          {isRunning && ps?.uptime_seconds != null && (
            <span style={{ fontSize: 11, color: t.textDim }}>
              {formatUptime(ps.uptime_seconds)}
            </span>
          )}
          {!isRunning && ps?.exit_code != null && ps.exit_code !== 0 && (
            <span style={{ fontSize: 11, color: "#ef4444" }}>
              exit {ps.exit_code}
            </span>
          )}
        </div>

        {/* Buttons */}
        <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
          {!isRunning && (
            <button
              onClick={() => startMut.mutate()}
              disabled={anyPending}
              title="Start"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "3px 10px",
                borderRadius: 4,
                border: "none",
                background: "rgba(34,197,94,0.15)",
                color: "#22c55e",
                fontSize: 11,
                fontWeight: 600,
                cursor: anyPending ? "wait" : "pointer",
                opacity: anyPending ? 0.5 : 1,
              }}
            >
              <Play size={10} /> Start
            </button>
          )}
          {isRunning && (
            <>
              <button
                onClick={() => stopMut.mutate()}
                disabled={anyPending}
                title="Stop"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 10px",
                  borderRadius: 4,
                  border: "none",
                  background: "rgba(239,68,68,0.15)",
                  color: "#ef4444",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: anyPending ? "wait" : "pointer",
                  opacity: anyPending ? 0.5 : 1,
                }}
              >
                <Square size={10} /> Stop
              </button>
              <button
                onClick={() => restartMut.mutate()}
                disabled={anyPending}
                title="Restart"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 10px",
                  borderRadius: 4,
                  border: "none",
                  background: "rgba(59,130,246,0.15)",
                  color: "#3b82f6",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: anyPending ? "wait" : "pointer",
                  opacity: anyPending ? 0.5 : 1,
                }}
              >
                <RefreshCw size={10} /> Restart
              </button>
            </>
          )}
        </div>
      </div>

      {/* Auto-start toggle */}
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: t.textDim,
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={autoStartData?.auto_start ?? true}
          onChange={(e) => setAutoStartMut.mutate(e.target.checked)}
          style={{ margin: 0 }}
        />
        Auto-start on server startup
      </label>
    </div>
  );
}

function DependencySection({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const installMut = useInstallDeps(item.id);

  const deps = item.python_dependencies;
  if (!deps || deps.length === 0) return null;

  const allInstalled = deps.every((d) => d.installed);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 10,
        background: t.surface,
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: 0.5,
        }}
      >
        Python Dependencies
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {deps.map((d) => (
          <span
            key={d.package}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 8px",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              background: d.installed ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
              color: d.installed ? "#22c55e" : "#ef4444",
              fontFamily: "monospace",
            }}
          >
            {d.installed ? <Check size={10} /> : <X size={10} />}
            {d.package}
          </span>
        ))}
      </div>
      {!allInstalled && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => installMut.mutate()}
            disabled={installMut.isPending}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "5px 14px",
              borderRadius: 5,
              border: "none",
              background: t.accent,
              color: "#fff",
              fontSize: 12,
              fontWeight: 600,
              cursor: installMut.isPending ? "wait" : "pointer",
              opacity: installMut.isPending ? 0.6 : 1,
            }}
          >
            <Download size={12} />
            {installMut.isPending ? "Installing..." : "Install Dependencies"}
          </button>
          {installMut.isSuccess && (
            <span style={{ fontSize: 11, color: "#22c55e" }}>
              Installed — restart server to activate tools
            </span>
          )}
          {installMut.isError && (
            <span style={{ fontSize: 11, color: "#ef4444" }}>
              Install failed
            </span>
          )}
        </div>
      )}
      {allInstalled && (
        <span style={{ fontSize: 11, color: "#22c55e" }}>
          All dependencies installed
        </span>
      )}
    </div>
  );
}

function ApiKeySection({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationApiKey(integrationId, true);
  const provisionMut = useProvisionIntegrationApiKey(integrationId);
  const revokeMut = useRevokeIntegrationApiKey(integrationId);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Show the newly generated key
  const newKey = provisionMut.data?.key_value ?? null;
  const displayKey = revealedKey ?? newKey;

  const handleCopyKey = async () => {
    if (displayKey) {
      await writeToClipboard(displayKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleProvision = () => {
    setRevealedKey(null);
    provisionMut.mutate(undefined, {
      onSuccess: (result) => {
        if (result.key_value) {
          setRevealedKey(result.key_value);
        }
      },
    });
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 10,
        background: t.surface,
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: 0.5,
        }}
      >
        Scoped API Key
      </div>

      {isLoading ? (
        <span style={{ fontSize: 12, color: t.textDim }}>Loading...</span>
      ) : data?.provisioned ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 500,
                background: "rgba(34,197,94,0.1)",
                color: "#22c55e",
                fontFamily: "monospace",
              }}
            >
              <Key size={10} />
              {data.key_prefix}...
            </span>
            {data.scopes && (
              <span style={{ fontSize: 10, color: t.textDim }}>
                {data.scopes.length} scope{data.scopes.length !== 1 ? "s" : ""}
              </span>
            )}
            <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
              <button
                onClick={handleProvision}
                disabled={provisionMut.isPending}
                title="Regenerate key"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 10px",
                  borderRadius: 4,
                  border: "none",
                  background: "rgba(59,130,246,0.15)",
                  color: "#3b82f6",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: provisionMut.isPending ? "wait" : "pointer",
                  opacity: provisionMut.isPending ? 0.5 : 1,
                }}
              >
                <RefreshCw size={10} /> Regenerate
              </button>
              <button
                onClick={() => revokeMut.mutate()}
                disabled={revokeMut.isPending}
                title="Revoke key"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 10px",
                  borderRadius: 4,
                  border: "none",
                  background: "rgba(239,68,68,0.15)",
                  color: "#ef4444",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: revokeMut.isPending ? "wait" : "pointer",
                  opacity: revokeMut.isPending ? 0.5 : 1,
                }}
              >
                <Trash2 size={10} /> Revoke
              </button>
            </div>
          </div>
          {data.scopes && data.scopes.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {data.scopes.map((s) => (
                <span
                  key={s}
                  style={{
                    fontSize: 10,
                    fontFamily: "monospace",
                    padding: "1px 6px",
                    borderRadius: 3,
                    background: "rgba(107,114,128,0.08)",
                    color: t.textMuted,
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: t.textDim }}>No key provisioned</span>
          <button
            onClick={handleProvision}
            disabled={provisionMut.isPending}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 12px",
              borderRadius: 5,
              border: "none",
              background: t.accent,
              color: "#fff",
              fontSize: 11,
              fontWeight: 600,
              cursor: provisionMut.isPending ? "wait" : "pointer",
              opacity: provisionMut.isPending ? 0.6 : 1,
            }}
          >
            <Key size={11} />
            {provisionMut.isPending ? "Generating..." : "Generate Key"}
          </button>
        </div>
      )}

      {/* One-time key reveal */}
      {displayKey && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 10px",
            background: "rgba(234,179,8,0.08)",
            borderRadius: 6,
            border: "1px solid rgba(234,179,8,0.2)",
          }}
        >
          <code
            style={{
              flex: 1,
              fontSize: 11,
              fontFamily: "monospace",
              color: t.text,
              wordBreak: "break-all",
            }}
          >
            {displayKey}
          </code>
          <button
            onClick={handleCopyKey}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 2,
              display: "flex",
              alignItems: "center",
              flexShrink: 0,
            }}
            title="Copy key"
          >
            {copied ? <Check size={14} color="#22c55e" /> : <Copy size={14} color={t.textDim} />}
          </button>
        </div>
      )}
    </div>
  );
}

function IntegrationCard({ item, isWide }: { item: IntegrationItem; isWide: boolean }) {
  const t = useThemeTokens();
  const [readmeExpanded, setReadmeExpanded] = useState(false);
  const [configExpanded, setConfigExpanded] = useState(false);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: t.inputBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      {/* Header: name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: t.text, flex: 1 }}>
          {item.name}
        </span>
        <StatusBadge status={item.status} />
      </div>

      {/* Env var pills */}
      {item.env_vars.length > 0 && (
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            Environment Variables
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {item.env_vars.map((v) => (
              <EnvVarPill key={v.key} v={v} />
            ))}
          </div>
        </div>
      )}

      {/* Webhook */}
      <WebhookRow webhook={item.webhook} />

      {/* Capability badges */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <CapBadge label="router" active={item.has_router} />
        <CapBadge label="dispatcher" active={item.has_dispatcher} />
        <CapBadge label="hooks" active={item.has_hooks} />
        <CapBadge label="tools" active={item.has_tools} />
        <CapBadge label="skills" active={item.has_skills} />
        <CapBadge label="carapaces" active={item.has_carapaces} />
        <CapBadge label="process" active={item.has_process} />
      </div>

      {/* Python dependencies */}
      <DependencySection item={item} />

      {/* Process controls */}
      {item.has_process && <ProcessControls integrationId={item.id} />}

      {/* API Key section */}
      {item.api_permissions && <ApiKeySection integrationId={item.id} />}

      {/* Configure section */}
      {item.env_vars.length > 0 && (
        <div>
          <button
            onClick={() => setConfigExpanded(!configExpanded)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontSize: 12,
              fontWeight: 600,
              color: t.accent,
            }}
          >
            {configExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Configure
          </button>
          {configExpanded && (
            <div
              style={{
                marginTop: 8,
                padding: 12,
                background: t.surface,
                borderRadius: 6,
                border: `1px solid ${t.surfaceBorder}`,
              }}
            >
              <SettingsForm integrationId={item.id} />
            </div>
          )}
        </div>
      )}

      {/* README expand */}
      {item.readme && (
        <div>
          <button
            onClick={() => setReadmeExpanded(!readmeExpanded)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontSize: 12,
              fontWeight: 600,
              color: t.accent,
            }}
          >
            {readmeExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Setup Instructions
          </button>
          {readmeExpanded && (
            <div
              style={{
                marginTop: 8,
                background: t.surface,
                borderRadius: 6,
                border: `1px solid ${t.surfaceBorder}`,
                overflow: "auto",
                maxHeight: 400,
              }}
            >
              <MarkdownViewer content={item.readme} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  // Deduplicate by id (defensive — backend should already return unique entries)
  const all = data?.integrations
    ? [...new Map(data.integrations.map((i) => [i.id, i])).values()]
    : undefined;
  const integrations = all?.filter((i) => i.source !== "package") ?? [];
  const packages = all?.filter((i) => i.source === "package") ?? [];

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const renderGrid = (items: IntegrationItem[]) => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isWide
          ? "repeat(auto-fill, minmax(400px, 1fr))"
          : "1fr",
        gap: isWide ? 12 : 10,
      }}
    >
      {items.map((item) => (
        <IntegrationCard key={item.id} item={item} isWide={isWide} />
      ))}
    </div>
  );

  const sectionHeader = (label: string) => (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: t.textDim,
        textTransform: "uppercase",
        letterSpacing: 0.8,
        marginTop: 4,
      }}
    >
      {label}
    </div>
  );

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Integrations & Packages" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: isWide ? 20 : 12,
          gap: isWide ? 12 : 10,
        }}
      >
        {isError && (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              fontSize: 13,
              color: "#ef4444",
            }}
          >
            Failed to load integrations.
          </div>
        )}

        {!isError && (!all || all.length === 0) && (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              fontSize: 13,
              color: t.textDim,
            }}
          >
            No integrations or packages discovered.
          </div>
        )}

        {integrations.length > 0 && (
          <>
            {sectionHeader("Integrations")}
            {renderGrid(integrations)}
          </>
        )}

        {packages.length > 0 && (
          <>
            {sectionHeader("Packages")}
            {renderGrid(packages)}
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
