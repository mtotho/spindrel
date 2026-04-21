import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import {
  Check, X, Copy, ChevronDown, ChevronRight,
  RotateCcw, Play, Square, RefreshCw, Download, Key, Trash2, Power,
  Link, Unlink,
} from "lucide-react";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
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
  useInstallNpmDeps,
  useInstallSystemDep,
  useIntegrationApiKey,
  useProvisionIntegrationApiKey,
  useRevokeIntegrationApiKey,
  useSetIntegrationStatus,
  useOAuthStatus,
  useOAuthDisconnect,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { useAuthStore } from "@/src/stores/auth";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { StatusBadge, CapBadge, EnvVarPill, formatUptime } from "../components";
import { IntegrationDebugSection } from "./IntegrationDebugSection";
import { ManifestEditor } from "./ManifestEditor";
import { ProcessLogsSection } from "./ProcessLogsSection";
import { DeviceStatusSection } from "./DeviceStatusSection";

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

export function SectionBox({ title, children }: { title: string; children: React.ReactNode }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: 0.6,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source badge
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Webhook row (copyable)
// ---------------------------------------------------------------------------

function WebhookRow({ webhook }: { webhook: IntegrationItem["webhook"] }) {
  const t = useThemeTokens();
  const [copied, setCopied] = useState(false);
  if (!webhook) return null;

  const handleCopy = async () => {
    await writeToClipboard(webhook.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, fontSize: 12 }}>
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
          display: "flex", flexDirection: "row",
          alignItems: "center",
        }}
        title="Copy full URL"
      >
        {copied ? <Check size={12} color="#22c55e" /> : <Copy size={12} color={t.textDim} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings form
// ---------------------------------------------------------------------------

function SettingsForm({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationSettings(integrationId);
  const updateMut = useUpdateIntegrationSettings(integrationId);
  const deleteMut = useDeleteIntegrationSetting(integrationId);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);

  const settings = data?.settings ?? [];

  if (settings.length > 0 && !initialized) {
    const initial: Record<string, string> = {};
    for (const s of settings) {
      initial[s.key] = s.secret && s.is_set ? "" : (s.value ?? "");
    }
    setDraft(initial);
    setInitialized(true);
  }

  if (isLoading) {
    return <div style={{ padding: 12, fontSize: 12, color: t.textDim }}>Loading settings...</div>;
  }

  if (settings.length === 0) {
    return <div style={{ fontSize: 12, color: t.textDim }}>No configurable settings.</div>;
  }

  const handleSave = () => {
    const updates: Record<string, string> = {};
    for (const s of settings) {
      const val = draft[s.key] ?? "";
      if (s.secret && s.is_set && val === "") continue;
      if (!s.secret && val === (s.value ?? "")) continue;
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
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, fontFamily: "monospace" }}>
              {s.key}
            </label>
            <SourceBadge source={s.source} />
            {!s.required && <span style={{ fontSize: 9, color: t.textDim }}>optional</span>}
            {s.source === "db" && (
              <button
                onClick={() => handleReset(s.key)}
                title="Reset to env/default"
                style={{ background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", flexDirection: "row", alignItems: "center" }}
              >
                <RotateCcw size={11} color={t.textDim} />
              </button>
            )}
          </div>
          {s.type === "model_selection" ? (
            <LlmModelDropdown
              value={draft[s.key] ?? ""}
              onChange={(modelId) => setDraft((prev) => ({ ...prev, [s.key]: modelId }))}
              placeholder={s.description || "Select model..."}
              allowClear
            />
          ) : s.type === "boolean" ? (
            <button
              onClick={() => {
                const current = (draft[s.key] ?? s.value ?? s.default ?? "true").toLowerCase();
                setDraft((prev) => ({ ...prev, [s.key]: current === "true" ? "false" : "true" }));
              }}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 8,
                padding: "6px 10px",
                background: "none",
                border: "none",
                cursor: "pointer",
              }}
            >
              <div style={{
                width: 36,
                height: 20,
                borderRadius: 10,
                backgroundColor: (draft[s.key] ?? s.value ?? s.default ?? "true").toLowerCase() === "true"
                  ? t.accent : t.surfaceOverlay,
                position: "relative",
                transition: "background-color 0.15s",
              }}>
                <div style={{
                  width: 16,
                  height: 16,
                  borderRadius: 8,
                  backgroundColor: "#fff",
                  position: "absolute",
                  top: 2,
                  left: (draft[s.key] ?? s.value ?? s.default ?? "true").toLowerCase() === "true" ? 18 : 2,
                  transition: "left 0.15s",
                }} />
              </div>
              <span style={{ fontSize: 12, color: t.text }}>
                {(draft[s.key] ?? s.value ?? s.default ?? "true").toLowerCase() === "true" ? "Enabled" : "Disabled"}
              </span>
            </button>
          ) : (
            <input
              type={s.secret ? "password" : "text"}
              value={draft[s.key] ?? ""}
              onChange={(e) => setDraft((prev) => ({ ...prev, [s.key]: e.target.value }))}
              placeholder={s.secret && s.is_set ? "\u2022\u2022\u2022\u2022\u2022 (unchanged)" : s.description}
              style={{
                background: t.surface,
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
          )}
          {s.description && <div style={{ fontSize: 11, color: t.textDim }}>{s.description}</div>}
        </div>
      ))}
      <div style={{ display: "flex", flexDirection: "row", gap: 8, marginTop: 4 }}>
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
        {updateMut.isSuccess && <span style={{ fontSize: 12, color: "#22c55e", alignSelf: "center" }}>Saved</span>}
        {updateMut.isError && <span style={{ fontSize: 12, color: "#ef4444", alignSelf: "center" }}>Error saving</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Process controls
// ---------------------------------------------------------------------------

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
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 5 }}>
          <span style={{ width: 8, height: 8, borderRadius: 4, background: isRunning ? "#22c55e" : "#6b7280", flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{isRunning ? "Running" : "Stopped"}</span>
          {isRunning && ps?.pid && (
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>pid {ps.pid}</span>
          )}
          {isRunning && ps?.uptime_seconds != null && (
            <span style={{ fontSize: 11, color: t.textDim }}>{formatUptime(ps.uptime_seconds)}</span>
          )}
          {!isRunning && ps?.exit_code != null && ps.exit_code !== 0 && (
            <span style={{ fontSize: 11, color: "#ef4444" }}>exit {ps.exit_code}</span>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "row", gap: 4, marginLeft: "auto" }}>
          {!isRunning && (
            <button
              onClick={() => startMut.mutate()}
              disabled={anyPending}
              title="Start"
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "3px 10px", borderRadius: 4, border: "none",
                background: "rgba(34,197,94,0.15)", color: "#22c55e",
                fontSize: 11, fontWeight: 600,
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
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 4, border: "none",
                  background: "rgba(239,68,68,0.15)", color: "#ef4444",
                  fontSize: 11, fontWeight: 600,
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
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 4, border: "none",
                  background: "rgba(59,130,246,0.15)", color: "#3b82f6",
                  fontSize: 11, fontWeight: 600,
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
      {(startMut.isError || stopMut.isError || restartMut.isError) && (
        <div style={{
          fontSize: 11, color: "#ef4444", padding: "4px 8px",
          background: "rgba(239,68,68,0.1)", borderRadius: 4,
        }}>
          {(() => {
            const err = startMut.error || stopMut.error || restartMut.error;
            if (!err) return "Process action failed";
            const body = (err as any)?.body;
            if (body) {
              try { return JSON.parse(body)?.detail || body; } catch { return body; }
            }
            return err.message || "Process action failed";
          })()}
        </div>
      )}
      <label style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, fontSize: 11, color: t.textDim, cursor: "pointer" }}>
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

// ---------------------------------------------------------------------------
// Dependency section
// ---------------------------------------------------------------------------

function DependencySection({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const installMut = useInstallDeps(item.id);

  const deps = item.python_dependencies;
  if (!deps || deps.length === 0) return null;

  const allInstalled = deps.every((d) => d.installed);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {deps.map((d) => (
          <span
            key={d.package}
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
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
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => installMut.mutate()}
            disabled={installMut.isPending}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "5px 14px", borderRadius: 5, border: "none",
              background: t.accent, color: "#fff", fontSize: 12, fontWeight: 600,
              cursor: installMut.isPending ? "wait" : "pointer",
              opacity: installMut.isPending ? 0.6 : 1,
            }}
          >
            <Download size={12} />
            {installMut.isPending ? "Installing..." : "Install Dependencies"}
          </button>
          {installMut.isSuccess && <span style={{ fontSize: 11, color: "#22c55e" }}>Installed — restart server to activate tools</span>}
          {installMut.isError && <span style={{ fontSize: 11, color: "#ef4444" }}>Install failed</span>}
        </div>
      )}
      {allInstalled && <span style={{ fontSize: 11, color: "#22c55e" }}>All dependencies installed</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// npm dependency section
// ---------------------------------------------------------------------------

function NpmDependencySection({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const installMut = useInstallNpmDeps(item.id);

  const deps = item.npm_dependencies;
  if (!deps || deps.length === 0) return null;

  const allInstalled = deps.every((d) => d.installed);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {deps.map((d) => (
          <span
            key={d.package}
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
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
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => installMut.mutate()}
            disabled={installMut.isPending}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "5px 14px", borderRadius: 5, border: "none",
              background: t.accent, color: "#fff", fontSize: 12, fontWeight: 600,
              cursor: installMut.isPending ? "wait" : "pointer",
              opacity: installMut.isPending ? 0.6 : 1,
            }}
          >
            <Download size={12} />
            {installMut.isPending ? "Installing..." : "Install npm Packages"}
          </button>
          {installMut.isSuccess && <span style={{ fontSize: 11, color: "#22c55e" }}>Installed</span>}
          {installMut.isError && <span style={{ fontSize: 11, color: "#ef4444" }}>Install failed</span>}
        </div>
      )}
      {allInstalled && <span style={{ fontSize: 11, color: "#22c55e" }}>All npm packages installed</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// System dependency section (binaries like chromium)
// ---------------------------------------------------------------------------

function SystemDependencySection({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const installMut = useInstallSystemDep(item.id);
  const deps = item.system_dependencies;
  if (!deps || deps.length === 0) return null;

  const allInstalled = deps.every((d) => d.installed);
  const missing = deps.filter((d) => !d.installed);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-row flex-wrap gap-1.5">
        {deps.map((d) => (
          <span
            key={d.binary}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium font-mono ${
              d.installed
                ? "bg-green-500/10 text-green-500"
                : "bg-red-500/10 text-red-500"
            }`}
          >
            {d.installed ? <Check size={10} /> : <X size={10} />}
            {d.binary}
          </span>
        ))}
      </div>
      {!allInstalled && (
        <div className="flex flex-row items-center gap-2 flex-wrap">
          <button
            onClick={() => {
              for (const d of missing) {
                installMut.mutate(d.apt_package);
              }
            }}
            disabled={installMut.isPending}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "5px 14px", borderRadius: 5, border: "none",
              background: t.accent, color: "#fff", fontSize: 12, fontWeight: 600,
              cursor: installMut.isPending ? "wait" : "pointer",
              opacity: installMut.isPending ? 0.6 : 1,
            }}
          >
            <Download size={12} />
            {installMut.isPending ? "Installing..." : "Install System Dependencies"}
          </button>
          {installMut.isSuccess && <span className="text-[11px] text-green-500">Installed</span>}
          {installMut.isError && <span className="text-[11px] text-red-500">Install failed</span>}
        </div>
      )}
      {allInstalled && <span className="text-[11px] text-green-500">All system dependencies available</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OAuth section
// ---------------------------------------------------------------------------

function OAuthSection({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const oauth = item.oauth;
  if (!oauth) return null;

  // Gate: required env vars must be configured before OAuth is available
  const requiredVarsSet = item.env_vars
    .filter((v) => v.required)
    .every((v) => v.is_set);

  const { data: status, isLoading } = useOAuthStatus(item.id, oauth.status);
  const disconnectMut = useOAuthDisconnect(item.id, oauth.disconnect);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [selectedScopes, setSelectedScopes] = useState<string[]>(
    oauth.scope_services.slice(0, 3)
  );

  const handleConnect = () => {
    const { serverUrl } = useAuthStore.getState();
    const scopeParam = selectedScopes.join(",");
    window.open(`${serverUrl}${oauth.auth_start}?scopes=${scopeParam}`, "_blank");
  };

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };

  if (!requiredVarsSet) {
    return (
      <div style={{ fontSize: 12, color: t.textDim }}>
        Save the required credentials above first, then connect your Google account here.
      </div>
    );
  }

  if (isLoading) {
    return <div style={{ fontSize: 12, color: t.textDim }}>Checking connection...</div>;
  }

  if (status?.connected) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
              background: "rgba(34,197,94,0.1)", color: "#22c55e",
            }}
          >
            <Link size={10} />
            Connected{status.email ? ` as ${status.email}` : ""}
          </span>
          <button
            onClick={async () => {
              const ok = await confirm(
                "Disconnect Google account? Bots will lose access to Google services.",
                { title: "Disconnect", confirmLabel: "Disconnect", variant: "danger" },
              );
              if (ok) disconnectMut.mutate();
            }}
            disabled={disconnectMut.isPending}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "3px 10px", borderRadius: 4, border: "none",
              background: "rgba(239,68,68,0.15)", color: "#ef4444",
              fontSize: 11, fontWeight: 600,
              cursor: disconnectMut.isPending ? "wait" : "pointer",
              opacity: disconnectMut.isPending ? 0.5 : 1,
            }}
          >
            <Unlink size={10} /> Disconnect
          </button>
        </div>
        {status.scopes && status.scopes.length > 0 && (
          <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
            {status.scopes.map((s) => (
              <span
                key={s}
                style={{
                  fontSize: 10, fontFamily: "monospace",
                  padding: "1px 6px", borderRadius: 3,
                  background: "rgba(107,114,128,0.08)", color: t.textMuted,
                }}
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontSize: 12, color: t.textDim }}>
        Select services to authorize, then connect your Google account.
      </div>
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {oauth.scope_services.map((svc) => {
          const active = selectedScopes.includes(svc);
          return (
            <button
              key={svc}
              onClick={() => toggleScope(svc)}
              style={{
                display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "3px 10px", borderRadius: 4, border: "none",
                background: active ? "rgba(59,130,246,0.15)" : "rgba(107,114,128,0.08)",
                color: active ? "#3b82f6" : t.textDim,
                fontSize: 11, fontWeight: 500, cursor: "pointer",
              }}
            >
              {active ? <Check size={10} /> : <X size={10} />}
              {svc}
            </button>
          );
        })}
      </div>
      <button
        onClick={handleConnect}
        disabled={selectedScopes.length === 0}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
          padding: "6px 16px", borderRadius: 6, border: "none",
          background: selectedScopes.length > 0 ? t.accent : t.surfaceOverlay,
          color: selectedScopes.length > 0 ? "#fff" : t.textDim,
          fontSize: 12, fontWeight: 600,
          cursor: selectedScopes.length > 0 ? "pointer" : "not-allowed",
          opacity: selectedScopes.length > 0 ? 1 : 0.6,
        }}
      >
        <Link size={13} />
        Connect Google Account
      </button>
      <ConfirmDialogSlot />
    </div>
  );
}

// ---------------------------------------------------------------------------
// API key section
// ---------------------------------------------------------------------------

function ApiKeySection({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationApiKey(integrationId, true);
  const provisionMut = useProvisionIntegrationApiKey(integrationId);
  const revokeMut = useRevokeIntegrationApiKey(integrationId);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
        if (result.key_value) setRevealedKey(result.key_value);
      },
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {isLoading ? (
        <span style={{ fontSize: 12, color: t.textDim }}>Loading...</span>
      ) : data?.provisioned ? (
        <>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
                background: "rgba(34,197,94,0.1)", color: "#22c55e", fontFamily: "monospace",
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
            <div style={{ display: "flex", flexDirection: "row", gap: 4, marginLeft: "auto" }}>
              <button
                onClick={handleProvision}
                disabled={provisionMut.isPending}
                title="Regenerate key"
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 4, border: "none",
                  background: "rgba(59,130,246,0.15)", color: "#3b82f6",
                  fontSize: 11, fontWeight: 600,
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
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 4, border: "none",
                  background: "rgba(239,68,68,0.15)", color: "#ef4444",
                  fontSize: 11, fontWeight: 600,
                  cursor: revokeMut.isPending ? "wait" : "pointer",
                  opacity: revokeMut.isPending ? 0.5 : 1,
                }}
              >
                <Trash2 size={10} /> Revoke
              </button>
            </div>
          </div>
          {data.scopes && data.scopes.length > 0 && (
            <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
              {data.scopes.map((s) => (
                <span
                  key={s}
                  style={{
                    fontSize: 10, fontFamily: "monospace",
                    padding: "1px 6px", borderRadius: 3,
                    background: "rgba(107,114,128,0.08)", color: t.textMuted,
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: t.textDim }}>No key provisioned</span>
          <button
            onClick={handleProvision}
            disabled={provisionMut.isPending}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "4px 12px", borderRadius: 5, border: "none",
              background: t.accent, color: "#fff", fontSize: 11, fontWeight: 600,
              cursor: provisionMut.isPending ? "wait" : "pointer",
              opacity: provisionMut.isPending ? 0.6 : 1,
            }}
          >
            <Key size={11} />
            {provisionMut.isPending ? "Generating..." : "Generate Key"}
          </button>
        </div>
      )}

      {displayKey && (
        <div
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            padding: "6px 10px", background: "rgba(234,179,8,0.08)",
            borderRadius: 6, border: "1px solid rgba(234,179,8,0.2)",
          }}
        >
          <code style={{ flex: 1, fontSize: 11, fontFamily: "monospace", color: t.text, wordBreak: "break-all" }}>
            {displayKey}
          </code>
          <button
            onClick={handleCopyKey}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", flexDirection: "row", alignItems: "center", flexShrink: 0 }}
            title="Copy key"
          >
            {copied ? <Check size={14} color="#22c55e" /> : <Copy size={14} color={t.textDim} />}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// README section (collapsible)
// ---------------------------------------------------------------------------

function ReadmeSection({ content }: { content: string }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
          background: "none", border: "none", cursor: "pointer", padding: 0,
          fontSize: 12, fontWeight: 600, color: t.accent,
        }}
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Setup Instructions
      </button>
      {expanded && (
        <div
          style={{
            marginTop: 8, background: t.surface, borderRadius: 6,
            border: `1px solid ${t.surfaceBorder}`, overflow: "auto", maxHeight: 400,
          }}
        >
          <MarkdownViewer content={content} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Disable/Enable toggle
// ---------------------------------------------------------------------------

function StatusControl({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const mut = useSetIntegrationStatus(item.id);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const isEnabled = item.lifecycle_status === "enabled";
  const missingRequired = item.env_vars.filter((v) => v.required && !v.is_set);
  const needsSetup = isEnabled && missingRequired.length > 0;

  const meta = !isEnabled
    ? { bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)", color: t.textMuted, label: "Available — not adopted" }
    : needsSetup
      ? { bg: "rgba(234,179,8,0.08)", border: "rgba(234,179,8,0.25)", color: "#eab308", label: "Enabled · Needs Setup" }
      : { bg: "rgba(34,197,94,0.06)", border: "rgba(34,197,94,0.15)", color: "#22c55e", label: "Enabled" };

  const onRemove = async () => {
    const ok = await confirm(
      "Remove from Active? The process will stop and tools will unload. Your settings are preserved — re-adding is instant.",
      { title: "Remove from Active", confirmLabel: "Remove", variant: "warning" },
    );
    if (!ok) return;
    mut.mutate("available");
  };
  const onEnable = () => mut.mutate("enabled");

  return (
    <div className="flex flex-col gap-2">
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 10,
          padding: "8px 14px",
          borderRadius: 8,
          background: meta.bg,
          border: `1px solid ${meta.border}`,
        }}
      >
        <Power size={14} color={meta.color} />
        <span style={{ fontSize: 12, fontWeight: 600, color: meta.color, flex: 1 }}>
          {meta.label}
        </span>
        {!isEnabled ? (
          <button
            onClick={onEnable}
            disabled={mut.isPending}
            style={{
              padding: "4px 14px",
              borderRadius: 5,
              border: "none",
              background: t.accent,
              color: "#fff",
              fontSize: 11,
              fontWeight: 600,
              cursor: mut.isPending ? "wait" : "pointer",
              opacity: mut.isPending ? 0.5 : 1,
            }}
          >
            {mut.isPending ? "..." : "Enable"}
          </button>
        ) : (
          <button
            onClick={onRemove}
            disabled={mut.isPending}
            style={{
              padding: "4px 14px",
              borderRadius: 5,
              border: "none",
              background: "rgba(239,68,68,0.15)",
              color: "#ef4444",
              fontSize: 11,
              fontWeight: 600,
              cursor: mut.isPending ? "wait" : "pointer",
              opacity: mut.isPending ? 0.5 : 1,
            }}
          >
            {mut.isPending ? "..." : "Disable"}
          </button>
        )}
      </div>

      {needsSetup && (
        <div
          style={{
            display: "flex", flexDirection: "row", alignItems: "flex-start",
            gap: 8,
            padding: "8px 14px",
            borderRadius: 8,
            background: "rgba(234,179,8,0.08)",
            border: "1px solid rgba(234,179,8,0.2)",
          }}
        >
          <span style={{ fontSize: 11, color: "#eab308", lineHeight: "18px", flex: 1 }}>
            Fill {missingRequired.length} required setting{missingRequired.length === 1 ? "" : "s"} to activate:{" "}
            <span style={{ fontFamily: "monospace", fontWeight: 600 }}>
              {missingRequired.map((v) => v.key).join(", ")}
            </span>
            . Integration will enable automatically once complete.
          </span>
        </div>
      )}
      <ConfirmDialogSlot />
    </div>
  );
}

// ===========================================================================
// Main detail screen
// ===========================================================================

export default function IntegrationDetailScreen() {
  const t = useThemeTokens();
  const { integrationId } = useParams<{ integrationId: string }>();
  const navigate = useNavigate();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;

  const item = data?.integrations?.find((i) => i.id === integrationId);

  if (isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  if (!item) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <div style={{ color: t.textDim, fontSize: 13 }}>Integration not found.</div>
          <button
            onClick={() => navigate("/admin/integrations")}
            style={{
              padding: "6px 16px", borderRadius: 6, border: "none",
              background: t.accent, color: "#fff", fontSize: 12,
              fontWeight: 600, cursor: "pointer",
            }}
          >
            Back to Integrations
          </button>
        </div>
      </div>
    );
  }

  const envSetCount = item.env_vars.filter((v) => v.is_set).length;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Integrations"
        backTo="/admin/integrations"
        title={item.name}
        right={<StatusBadge status={item.lifecycle_status === "enabled" && item.env_vars.some((v) => v.required && !v.is_set) ? "needs_setup" : item.lifecycle_status} />}
      />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: isWide ? 20 : 12, gap: 14, maxWidth: 720 }}
      >
        {/* Lifecycle status control */}
        <StatusControl item={item} />

        {/* Sections — dimmed when not yet adopted */}
        <div style={{ opacity: item.lifecycle_status === "available" ? 0.6 : 1, display: "flex", flexDirection: "column", gap: 14 }}>

        {/* Overview */}
        <SectionBox title="Overview">
          <div style={{ display: "flex", flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
            <CapBadge label="router" active={item.has_router} />
            <CapBadge label="renderer" active={item.has_renderer} />
            <CapBadge label="hooks" active={item.has_hooks} />
            <CapBadge label="tools" active={item.has_tools} />
            <CapBadge label="skills" active={item.has_skills} />
            <CapBadge label="widgets" active={item.has_tool_widgets} />
            <CapBadge label="process" active={item.has_process} />
          </div>
          <WebhookRow webhook={item.webhook} />
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, fontSize: 11, color: t.textDim }}>
            <span>Source:</span>
            <span
              style={{
                fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 3,
                background: "rgba(107,114,128,0.08)", color: t.textMuted,
                textTransform: "uppercase", letterSpacing: 0.3,
              }}
            >
              {item.source}
            </span>
          </div>
        </SectionBox>

        {/* Device / connection status (generic — shown when process reports devices) */}
        <DeviceStatusSection integrationId={item.id} />

        {/* Manifest editor — Visual/YAML toggle with MCP server status */}
        <ManifestEditor integrationId={item.id} />

        {/* Declared events */}
        {item.events && item.events.length > 0 && (
          <SectionBox title={`Events (${item.events.length})`}>
            <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>
              Events this integration can emit. Use in task triggers or channel binding filters.
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {item.events.map((ev) => (
                <div
                  key={ev.type}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                    padding: "6px 10px", borderRadius: 6,
                    background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: t.accent, minWidth: 120 }}>
                    {ev.type}
                  </span>
                  <span style={{ fontSize: 11, color: t.text, flex: 1 }}>
                    {ev.label}
                  </span>
                  {ev.category && (
                    <span style={{
                      fontSize: 9, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5,
                      padding: "2px 6px", borderRadius: 4,
                      background: ev.category === "webhook" ? "rgba(59,130,246,0.15)" :
                                  ev.category === "message" ? "rgba(34,197,94,0.15)" :
                                  ev.category === "poll" ? "rgba(234,179,8,0.15)" :
                                  "rgba(168,85,247,0.15)",
                      color: ev.category === "webhook" ? "#3b82f6" :
                             ev.category === "message" ? "#22c55e" :
                             ev.category === "poll" ? "#eab308" :
                             "#a855f7",
                    }}>
                      {ev.category}
                    </span>
                  )}
                  {ev.description && (
                    <span style={{ fontSize: 10, color: t.textDim, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {ev.description}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </SectionBox>
        )}

        {/* Detected tools / skills / widgets */}
        {((item.tool_names && item.tool_names.length > 0) ||
          (item.tool_files && item.tool_files.length > 0) ||
          (item.skill_files && item.skill_files.length > 0) ||
          (item.tool_widget_names && item.tool_widget_names.length > 0)) && (
          <SectionBox title="Detected Assets">
            {/* Tools — prefer live registered names, fall back to file names */}
            {(() => {
              const names = item.tool_names && item.tool_names.length > 0
                ? item.tool_names
                : item.tool_files && item.tool_files.length > 0
                  ? item.tool_files
                  : null;
              if (!names) return null;
              const isLive = !!(item.tool_names && item.tool_names.length > 0);
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Tools ({names.length}){!isLive && " — files on disk, not yet loaded"}
                  </span>
                  <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
                    {names.map((n) => (
                      <span
                        key={n}
                        style={{
                          fontSize: 11, fontFamily: "monospace",
                          padding: "2px 8px", borderRadius: 4,
                          background: isLive ? "rgba(59,130,246,0.1)" : "rgba(107,114,128,0.08)",
                          color: isLive ? "#3b82f6" : t.textMuted,
                        }}
                      >
                        {n}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })()}
            {item.skill_files && item.skill_files.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Skills ({item.skill_files.length})
                </span>
                <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
                  {item.skill_files.map((n) => (
                    <span
                      key={n}
                      style={{
                        fontSize: 11, fontFamily: "monospace",
                        padding: "2px 8px", borderRadius: 4,
                        background: "rgba(168,85,247,0.1)", color: "#a855f7",
                      }}
                    >
                      {n}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {item.tool_widget_names && item.tool_widget_names.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Tool Widgets ({item.tool_widget_names.length})
                </span>
                <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
                  {item.tool_widget_names.map((n) => (
                    <span
                      key={n}
                      style={{
                        fontSize: 11, fontFamily: "monospace",
                        padding: "2px 8px", borderRadius: 4,
                        background: "rgba(168,85,247,0.1)", color: "#a855f7",
                      }}
                    >
                      {n}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </SectionBox>
        )}

        {/* README — show early so users see setup instructions before config */}
        {item.readme && <ReadmeSection content={item.readme} />}

        {/* Environment variables */}
        {item.env_vars.length > 0 && (
          <SectionBox title={`Environment Variables (${envSetCount}/${item.env_vars.length} set)`}>
            <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {item.env_vars.map((v) => (
                <EnvVarPill key={v.key} v={v} />
              ))}
            </div>
          </SectionBox>
        )}

        {/* Configuration */}
        {item.env_vars.length > 0 && (
          <SectionBox title="Configuration">
            <SettingsForm integrationId={item.id} />
          </SectionBox>
        )}

        {/* Python dependencies */}
        {item.python_dependencies && item.python_dependencies.length > 0 && (
          <SectionBox title="Python Dependencies">
            <DependencySection item={item} />
          </SectionBox>
        )}

        {/* npm dependencies */}
        {item.npm_dependencies && item.npm_dependencies.length > 0 && (
          <SectionBox title="npm Dependencies">
            <NpmDependencySection item={item} />
          </SectionBox>
        )}

        {/* System dependencies */}
        {item.system_dependencies && item.system_dependencies.length > 0 && (
          <SectionBox title="System Dependencies">
            <SystemDependencySection item={item} />
          </SectionBox>
        )}

        {/* OAuth connection */}
        {item.oauth && (
          <SectionBox title="OAuth Connection">
            <OAuthSection item={item} />
          </SectionBox>
        )}

        {/* Process */}
        {item.has_process && (
          <SectionBox title="Process">
            {item.process_launchable !== false ? (
              <ProcessControls integrationId={item.id} />
            ) : (
              <div style={{ fontSize: 12, color: t.textDim }}>
                {item.process_description || "Background process disabled (no CMD defined)."}
              </div>
            )}
          </SectionBox>
        )}

        {/* Process logs (generic — shown for any integration with a process) */}
        {item.has_process && (
          <ProcessLogsSection
            integrationId={item.id}
            processRunning={item.process_status?.status === "running"}
          />
        )}

        {/* API key */}
        {item.api_permissions && (
          <SectionBox title="API Key">
            <ApiKeySection integrationId={item.id} />
          </SectionBox>
        )}

        {/* Activity & Debug */}
        <IntegrationDebugSection
          integrationId={item.id}
          debugActions={item.debug_actions}
        />

        </div>{/* end disabled wrapper */}
      </RefreshableScrollView>
    </div>
  );
}
