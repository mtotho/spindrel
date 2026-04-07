import { useState } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  Check, X, Copy, ChevronDown, ChevronRight,
  RotateCcw, Play, Square, RefreshCw, Download, Key, Trash2, Power,
  Link, Unlink,
} from "lucide-react";
import { DetailHeader } from "@/src/components/layout/DetailHeader";
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
  useIntegrationApiKey,
  useProvisionIntegrationApiKey,
  useRevokeIntegrationApiKey,
  useSetIntegrationDisabled,
  useOAuthStatus,
  useOAuthDisconnect,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { useAuthStore } from "@/src/stores/auth";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { StatusBadge, CapBadge, EnvVarPill, formatUptime } from "../components";
import { IntegrationDebugSection } from "./IntegrationDebugSection";

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function SectionBox({ title, children }: { title: string; children: React.ReactNode }) {
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
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
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
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, fontFamily: "monospace" }}>
              {s.key}
            </label>
            <SourceBadge source={s.source} />
            {!s.required && <span style={{ fontSize: 9, color: t.textDim }}>optional</span>}
            {s.source === "db" && (
              <button
                onClick={() => handleReset(s.key)}
                title="Reset to env/default"
                style={{ background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", alignItems: "center" }}
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
                display: "flex",
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
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
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
        <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
          {!isRunning && (
            <button
              onClick={() => startMut.mutate()}
              disabled={anyPending}
              title="Start"
              style={{
                display: "flex", alignItems: "center", gap: 4,
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
                  display: "flex", alignItems: "center", gap: 4,
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
                  display: "flex", alignItems: "center", gap: 4,
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
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textDim, cursor: "pointer" }}>
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {deps.map((d) => (
          <span
            key={d.package}
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
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
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => installMut.mutate()}
            disabled={installMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {deps.map((d) => (
          <span
            key={d.package}
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
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
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => installMut.mutate()}
            disabled={installMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
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
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
              background: "rgba(34,197,94,0.1)", color: "#22c55e",
            }}
          >
            <Link size={10} />
            Connected{status.email ? ` as ${status.email}` : ""}
          </span>
          <button
            onClick={() => {
              if (window.confirm("Disconnect Google account? Bots will lose access to Google services.")) {
                disconnectMut.mutate();
              }
            }}
            disabled={disconnectMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
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
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {oauth.scope_services.map((svc) => {
          const active = selectedScopes.includes(svc);
          return (
            <button
              key={svc}
              onClick={() => toggleScope(svc)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
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
          display: "flex", alignItems: "center", gap: 6, alignSelf: "flex-start",
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
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
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
            <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
              <button
                onClick={handleProvision}
                disabled={provisionMut.isPending}
                title="Regenerate key"
                style={{
                  display: "flex", alignItems: "center", gap: 4,
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
                  display: "flex", alignItems: "center", gap: 4,
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: t.textDim }}>No key provisioned</span>
          <button
            onClick={handleProvision}
            disabled={provisionMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
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
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 10px", background: "rgba(234,179,8,0.08)",
            borderRadius: 6, border: "1px solid rgba(234,179,8,0.2)",
          }}
        >
          <code style={{ flex: 1, fontSize: 11, fontFamily: "monospace", color: t.text, wordBreak: "break-all" }}>
            {displayKey}
          </code>
          <button
            onClick={handleCopyKey}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 2, display: "flex", alignItems: "center", flexShrink: 0 }}
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
          display: "flex", alignItems: "center", gap: 4,
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

function DisableToggle({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const mut = useSetIntegrationDisabled(item.id);
  const isDisabled = item.disabled;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 14px",
        borderRadius: 8,
        background: isDisabled ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.06)",
        border: `1px solid ${isDisabled ? "rgba(239,68,68,0.2)" : "rgba(34,197,94,0.15)"}`,
      }}
    >
      <Power size={14} color={isDisabled ? "#ef4444" : "#22c55e"} />
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: isDisabled ? "#ef4444" : "#22c55e",
          flex: 1,
        }}
      >
        {isDisabled ? "Integration Disabled" : "Integration Enabled"}
      </span>
      <button
        onClick={() => {
          if (!isDisabled && !window.confirm("Disable this integration? Its process will be stopped and tools will be unloaded.")) return;
          mut.mutate(!isDisabled);
        }}
        disabled={mut.isPending}
        style={{
          padding: "4px 14px",
          borderRadius: 5,
          border: "none",
          background: isDisabled ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
          color: isDisabled ? "#22c55e" : "#ef4444",
          fontSize: 11,
          fontWeight: 600,
          cursor: mut.isPending ? "wait" : "pointer",
          opacity: mut.isPending ? 0.5 : 1,
        }}
      >
        {mut.isPending ? "..." : isDisabled ? "Enable" : "Disable"}
      </button>
    </div>
  );
}

// ===========================================================================
// Main detail screen
// ===========================================================================

export default function IntegrationDetailScreen() {
  const t = useThemeTokens();
  const { integrationId } = useLocalSearchParams<{ integrationId: string }>();
  const router = useRouter();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const item = data?.integrations?.find((i) => i.id === integrationId);

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  if (!item) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <div style={{ color: t.textDim, fontSize: 13 }}>Integration not found.</div>
          <button
            onClick={() => router.push("/admin/integrations" as any)}
            style={{
              padding: "6px 16px", borderRadius: 6, border: "none",
              background: t.accent, color: "#fff", fontSize: 12,
              fontWeight: 600, cursor: "pointer",
            }}
          >
            Back to Integrations
          </button>
        </div>
      </View>
    );
  }

  const envSetCount = item.env_vars.filter((v) => v.is_set).length;

  return (
    <View className="flex-1 bg-surface">
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: isWide ? 20 : 12, gap: 14, maxWidth: 720 }}
      >
        {/* Header */}
        <DetailHeader
          parentLabel="Integrations"
          parentHref="/admin/integrations"
          title={item.name}
          right={<StatusBadge status={item.disabled ? "disabled" : item.status} />}
          inline
        />

        {/* Disable/Enable toggle */}
        <DisableToggle item={item} />

        {/* Sections — dimmed when disabled (pointerEvents left as auto to allow scrolling) */}
        <div style={{ opacity: item.disabled ? 0.5 : 1, display: "flex", flexDirection: "column", gap: 14 }}>

        {/* Overview */}
        <SectionBox title="Overview">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <CapBadge label="router" active={item.has_router} />
            <CapBadge label="dispatcher" active={item.has_dispatcher} />
            <CapBadge label="hooks" active={item.has_hooks} />
            <CapBadge label="tools" active={item.has_tools} />
            <CapBadge label="skills" active={item.has_skills} />
            <CapBadge label="capabilities" active={item.has_carapaces} />
            <CapBadge label="process" active={item.has_process} />
          </div>
          <WebhookRow webhook={item.webhook} />
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textDim }}>
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

        {/* Detected tools / skills / capabilities */}
        {((item.tool_names && item.tool_names.length > 0) ||
          (item.tool_files && item.tool_files.length > 0) ||
          (item.skill_files && item.skill_files.length > 0) ||
          (item.carapace_files && item.carapace_files.length > 0)) && (
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
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
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
            {item.carapace_files && item.carapace_files.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Capabilities ({item.carapace_files.length})
                </span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {item.carapace_files.map((n) => (
                    <span
                      key={n}
                      style={{
                        fontSize: 11, fontFamily: "monospace",
                        padding: "2px 8px", borderRadius: 4,
                        background: "rgba(34,197,94,0.1)", color: "#22c55e",
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
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
    </View>
  );
}
