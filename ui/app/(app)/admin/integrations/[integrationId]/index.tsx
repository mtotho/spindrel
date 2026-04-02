import { useState } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  ChevronLeft, Check, X, Copy, ChevronDown, ChevronRight,
  RotateCcw, Play, Square, RefreshCw, Download, Key, Trash2, BookOpen,
} from "lucide-react";
import { IntegrationGuideModal } from "../IntegrationGuideModal";
import { useGoBack } from "@/src/hooks/useGoBack";
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
  useIntegrationApiKey,
  useProvisionIntegrationApiKey,
  useRevokeIntegrationApiKey,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { StatusBadge, CapBadge, EnvVarPill, formatUptime } from "../components";

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

// ===========================================================================
// Main detail screen
// ===========================================================================

export default function IntegrationDetailScreen() {
  const t = useThemeTokens();
  const { integrationId } = useLocalSearchParams<{ integrationId: string }>();
  const goBack = useGoBack("/admin/integrations");
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const [showGuide, setShowGuide] = useState(false);
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
            onClick={goBack}
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
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={goBack}
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: 4, display: "flex", alignItems: "center",
            }}
          >
            <ChevronLeft size={20} color={t.textMuted} />
          </button>
          <span style={{ fontSize: 18, fontWeight: 700, color: t.text }}>{item.name}</span>
          <StatusBadge status={item.status} />
          <button
            onClick={() => setShowGuide(true)}
            title="Integration Guide"
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 5,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent", color: t.textMuted,
              fontSize: 11, fontWeight: 500,
              cursor: "pointer",
              marginLeft: "auto",
            }}
          >
            <BookOpen size={13} />
            Guide
          </button>
        </div>

        {/* Overview */}
        <SectionBox title="Overview">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <CapBadge label="router" active={item.has_router} />
            <CapBadge label="dispatcher" active={item.has_dispatcher} />
            <CapBadge label="hooks" active={item.has_hooks} />
            <CapBadge label="tools" active={item.has_tools} />
            <CapBadge label="skills" active={item.has_skills} />
            <CapBadge label="carapaces" active={item.has_carapaces} />
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

        {/* Process */}
        {item.has_process && (
          <SectionBox title="Process">
            <ProcessControls integrationId={item.id} />
          </SectionBox>
        )}

        {/* API key */}
        {item.api_permissions && (
          <SectionBox title="API Key">
            <ApiKeySection integrationId={item.id} />
          </SectionBox>
        )}

        {/* README */}
        {item.readme && <ReadmeSection content={item.readme} />}
      </RefreshableScrollView>

      {showGuide && <IntegrationGuideModal onClose={() => setShowGuide(false)} />}
    </View>
  );
}
