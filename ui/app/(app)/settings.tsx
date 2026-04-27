import { useState, useEffect, useCallback, useMemo } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RotateCcw, Check, Sun, Moon, Download, Bell, BellOff } from "lucide-react";
import { useInstallPromptStore } from "@/src/stores/installPrompt";
import {
  disablePush, enablePush, getExistingSubscription,
  isPushSupported, notificationPermission,
} from "@/src/lib/pushSubscription";
import { toast } from "@/src/stores/toast";
import { MemorySchemeSection } from "@/src/components/settings/MemorySchemeSection";
import { SettingsPromptField } from "@/src/components/settings/SettingsPromptField";
import { DreamingManagementSection } from "@/src/components/settings/DreamingManagementSection";
import { apiFetch } from "@/src/api/client";
import { useThemeStore } from "@/src/stores/theme";
import { useThemeTokens } from "@/src/theme/tokens";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { type FallbackModelEntry } from "@/src/components/shared/FallbackModelList";
import { Section } from "@/src/components/shared/FormControls";
import { useUnreadRules, useUpdateUnreadRule } from "@/src/api/hooks/useUnread";
import {
  useSettings,
  useUpdateSettings,
  useResetSetting,
  SettingItem,
  SettingsGroup,
} from "@/src/api/hooks/useSettings";
import { ServerStatusStrip } from "@/src/components/settings/ServerStatusBar";
import { GlobalSection } from "@/src/components/settings/GlobalSection";
import { ModelTiersSection } from "@/src/components/settings/ModelTiersSection";
import { ChatHistoryExtras } from "@/src/components/settings/ChatHistoryExtras";
import { BotOverridesList } from "@/src/components/settings/BotOverridesList";
import { FileModeOnlyBanner } from "@/src/components/settings/FileModeOnlyBanner";
import { MemoryHygieneGroupBanner } from "@/src/components/settings/MemoryHygieneGroupBanner";
import { BackupSection } from "@/src/components/settings/BackupSection";

// ---------------------------------------------------------------------------
// Toggle switch (replaces bare checkbox)
// ---------------------------------------------------------------------------

function ToggleSwitch({
  value,
  onChange,
  disabled,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => !disabled && onChange(!value)}
      className="relative shrink-0 border-none cursor-pointer"
      style={{
        display: "inline-flex",
        width: 36,
        height: 20,
        borderRadius: 10,
        backgroundColor: value ? "rgb(var(--color-accent))" : "rgb(var(--color-surface-border))",
        transition: "background-color 0.15s",
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      <span
        style={{
          display: "block",
          width: 16,
          height: 16,
          borderRadius: 8,
          backgroundColor: "white",
          position: "absolute",
          top: 2,
          left: value ? 18 : 2,
          transition: "left 0.15s",
        }}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Field renderers
// ---------------------------------------------------------------------------

function SelectField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
      {item.options!.map((opt) => (
        <button
          type="button"
          key={opt}
          onClick={() => !item.read_only && onChange(opt)}
          style={{
            padding: "4px 10px",
            borderRadius: 6,
            fontSize: 11,
            fontWeight: value === opt ? 600 : 400,
            border: value === opt ? "1px solid rgb(var(--color-accent) / 0.4)" : "1px solid rgb(var(--color-surface-border))",
            background: value === opt ? "rgb(var(--color-accent) / 0.12)" : "transparent",
            color: value === opt ? "rgb(var(--color-accent))" : "rgb(var(--color-text-dim))",
            cursor: item.read_only ? "default" : "pointer",
            transition: "all 0.12s",
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function NumberField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useThemeTokens();
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      readOnly={item.read_only}
      type="number"
      placeholder={item.nullable ? "—" : undefined}
      style={{
        width: 90,
        padding: "5px 10px",
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.surfaceRaised,
        color: t.text,
        fontSize: 13,
        outline: "none",
      }}
    />
  );
}

function StringField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useThemeTokens();
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      readOnly={item.read_only}
      placeholder="—"
      style={{
        maxWidth: 480,
        flex: 1,
        padding: "5px 10px",
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.surfaceRaised,
        color: t.text,
        fontSize: 13,
        outline: "none",
      }}
    />
  );
}

function ModelField({
  item,
  value,
  selectedProviderId,
  onChange,
}: {
  item: SettingItem;
  value: string;
  selectedProviderId?: string;
  onChange: (model: string, providerId?: string | null) => void;
}) {
  return (
    <div style={{ maxWidth: 300 }}>
      <LlmModelDropdown
        value={value}
        selectedProviderId={selectedProviderId}
        onChange={onChange}
        placeholder="Select model..."
        allowClear
      />
    </div>
  );
}

function EmbeddingModelField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ maxWidth: 300 }}>
      <LlmModelDropdown
        value={value}
        onChange={onChange}
        placeholder="Select embedding model..."
        allowClear
        variant="embedding"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single setting row
// Horizontal: label+desc left, field right (for bool, number, string, select)
// Vertical: label+desc top, field below (for textarea, model)
// ---------------------------------------------------------------------------

function SettingRow({
  item,
  localValue,
  providerValue,
  onLocalChange,
  onReset,
  isResetting,
}: {
  item: SettingItem;
  localValue: any;
  providerValue?: string;
  onLocalChange: (key: string, value: any) => void;
  onReset: (key: string) => void;
  isResetting: boolean;
}) {
  const t = useThemeTokens();

  const renderField = () => {
    if (item.type === "bool") {
      return (
        <ToggleSwitch
          value={!!localValue}
          onChange={(v) => onLocalChange(item.key, v)}
          disabled={item.read_only}
        />
      );
    }
    if (item.options && item.options.length > 0) {
      return (
        <SelectField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.type === "int" || item.type === "float") {
      return (
        <NumberField
          item={item}
          value={localValue === null || localValue === undefined ? "" : String(localValue)}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.widget === "textarea") {
      return (
        <SettingsPromptField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v: string) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.widget === "model") {
      const providerKey = item.key === "IMAGE_GENERATION_MODEL"
        ? "IMAGE_GENERATION_PROVIDER_ID"
        : item.key === "CONTEXTUAL_RETRIEVAL_MODEL"
        ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID"
        : item.key + "_PROVIDER_ID";
      return (
        <ModelField
          item={item}
          value={String(localValue ?? "")}
          selectedProviderId={providerValue}
          onChange={(model, pid) => {
            onLocalChange(item.key, model);
            onLocalChange(providerKey, pid ?? "");
          }}
        />
      );
    }
    if (item.widget === "embedding_model") {
      return (
        <EmbeddingModelField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    return (
      <StringField
        item={item}
        value={String(localValue ?? "")}
        onChange={(v) => onLocalChange(item.key, v)}
      />
    );
  };

  const isLongString = !item.widget && item.type === "string" && String(localValue ?? "").length > 30;
  const isComplex = item.widget === "textarea" || item.widget === "model" || item.widget === "embedding_model" || isLongString;

  const resetBtn = item.overridden && !item.read_only ? (
    <button
      type="button"
      onClick={() => onReset(item.key)}
      disabled={isResetting}
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "3px 8px", borderRadius: 4,
        background: "transparent", border: "none",
        color: t.textDim, fontSize: 10, cursor: "pointer",
      }}
    >
      {isResetting ? <Spinner size={10} color={t.textDim} /> : <RotateCcw size={10} />}
      Reset
    </button>
  ) : null;

  // Vertical layout for complex fields
  if (isComplex) {
    return (
      <div style={{ padding: "12px 0", display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{item.label}</span>
          {item.overridden && (
            <span style={{ fontSize: 9, fontWeight: 600, color: t.accent, background: "rgb(var(--color-accent) / 0.1)", padding: "1px 6px", borderRadius: 3 }}>
              overridden
            </span>
          )}
          {resetBtn}
        </div>
        <span style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>{item.description}</span>
        {renderField()}
      </div>
    );
  }

  // Horizontal layout for simple fields
  return (
    <div style={{ padding: "10px 0", display: "flex", flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{item.label}</span>
          {item.overridden && (
            <span style={{ fontSize: 9, fontWeight: 600, color: t.accent, background: "rgb(var(--color-accent) / 0.1)", padding: "1px 6px", borderRadius: 3 }}>
              overridden
            </span>
          )}
          {item.read_only && (
            <span style={{ fontSize: 9, color: t.textDim, background: t.surfaceOverlay, padding: "1px 6px", borderRadius: 3 }}>
              read-only
            </span>
          )}
        </div>
        <span style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5", display: "block", marginTop: 2 }}>{item.description}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 0, paddingTop: 2 }}>
        {renderField()}
        {resetBtn}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-section headers
// ---------------------------------------------------------------------------
const SUB_SECTION_HEADERS: Record<string, { title: string; desc?: string }> = {
  MEMORY_FLUSH_ENABLED: { title: "Memory Flush", desc: "Save memories before context compaction. Workspace-files bots use a built-in flush prompt (shown above)." },
  MEMORY_HYGIENE_ENABLED: { title: "Dreaming — Memory Maintenance", desc: "Periodic background review of bot memory files" },
  SKILL_REVIEW_ENABLED: { title: "Dreaming — Skill Review", desc: "Periodic skill curation and cross-channel reflection" },
  MEMORY_MD_NUDGE_THRESHOLD: { title: "Memory Size" },
};

// ---------------------------------------------------------------------------
// Group section nav
// ---------------------------------------------------------------------------

function GroupNav({
  groups,
  activeGroup,
  onSelect,
}: {
  groups: SettingsGroup[];
  activeGroup: string;
  onSelect: (g: string) => void;
}) {
  const t = useThemeTokens();
  return (
    <nav style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {groups.map((g) => {
        const active = activeGroup === g.group;
        return (
          <button
            type="button"
            key={g.group}
            onClick={() => onSelect(g.group)}
            style={{
              textAlign: "left",
              padding: "6px 12px",
              borderRadius: 6,
              background: active ? "rgb(var(--color-accent) / 0.1)" : "transparent",
              color: active ? t.accent : t.textMuted,
              fontSize: 13,
              fontWeight: active ? 500 : 400,
              border: "none",
              cursor: "pointer",
              transition: "all 0.1s",
            }}
          >
            {g.group}
          </button>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Global Fallback Models hooks
// ---------------------------------------------------------------------------

function useGlobalFallbackModels() {
  return useQuery({
    queryKey: ["global-fallback-models"],
    queryFn: () =>
      apiFetch<{ models: FallbackModelEntry[] }>("/api/v1/admin/global-fallback-models"),
  });
}

function useUpdateGlobalFallbackModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (models: FallbackModelEntry[]) =>
      apiFetch("/api/v1/admin/global-fallback-models", {
        method: "PUT",
        body: JSON.stringify({ models }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["global-fallback-models"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Appearance section
// ---------------------------------------------------------------------------

const GLOBAL_GROUP = "Global";
const BACKUP_GROUP = "Backup";

function AppearanceSection() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: "10px 0" }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
        {mode === "dark" ? <Moon size={16} color={t.textMuted} /> : <Sun size={16} color={t.textMuted} />}
        <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>
          {mode === "dark" ? "Dark mode" : "Light mode"}
        </span>
      </div>
      <ToggleSwitch value={mode === "dark"} onChange={toggle} />
    </div>
  );
}

/** Web Push opt-in toggle. Hidden on unsupported platforms (iOS Safari
 *  browser tab, etc.). On iOS the user must first install the PWA to
 *  Home Screen — see `isPushSupported`. */
function NotificationsSection() {
  const t = useThemeTokens();
  const [supported, setSupported] = useState<boolean | null>(null);
  const [subscribed, setSubscribed] = useState(false);
  const [perm, setPerm] = useState<NotificationPermission>("default");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ok = isPushSupported();
    setSupported(ok);
    if (!ok) return;
    setPerm(notificationPermission());
    void getExistingSubscription().then((sub) => setSubscribed(!!sub));
  }, []);

  if (supported === null) return null;
  if (!supported) {
    // iOS Safari in a browser tab: suggest install instead. Skip the
    // message entirely on desktop browsers that lack Notification API.
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    if (!isIOS) return null;
    return (
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: "10px 0" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
            <BellOff size={16} color={t.textDim} />
            <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>Notifications</span>
          </div>
          <span style={{ fontSize: 11, color: t.textDim, paddingLeft: 26 }}>
            Install Spindrel to your Home Screen first (Share → Add to Home Screen). Notifications work only in the installed app on iOS.
          </span>
        </div>
      </div>
    );
  }

  const handleEnable = async () => {
    setBusy(true);
    try {
      const r = await enablePush();
      if (r.ok) {
        setSubscribed(true);
        setPerm(notificationPermission());
        toast({ kind: "success", message: "Notifications enabled" });
      } else {
        const msg =
          r.reason === "denied" ? "Permission denied in the browser."
          : r.reason === "server-disabled" ? "Push is not configured on this server."
          : r.reason === "unsupported" ? "Notifications aren't supported on this device."
          : `Couldn't enable notifications${r.message ? `: ${r.message}` : ""}.`;
        toast({ kind: "error", message: msg, durationMs: 5000 });
      }
    } finally {
      setBusy(false);
    }
  };

  const handleDisable = async () => {
    setBusy(true);
    try {
      await disablePush();
      setSubscribed(false);
      toast({ kind: "info", message: "Notifications disabled" });
    } finally {
      setBusy(false);
    }
  };

  const denied = perm === "denied";
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: "10px 0" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
          {subscribed ? <Bell size={16} color={t.accent} /> : <BellOff size={16} color={t.textMuted} />}
          <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>Push notifications</span>
        </div>
        <span style={{ fontSize: 11, color: t.textDim, paddingLeft: 26 }}>
          {denied
            ? "Blocked in your browser settings — unblock there and try again."
            : subscribed
            ? "This device will receive push notifications from Spindrel bots and tools."
            : "Let Spindrel wake this device when a bot pushes a notification."}
        </span>
      </div>
      <button
        type="button"
        onClick={subscribed ? handleDisable : handleEnable}
        disabled={busy || denied}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: subscribed ? "transparent" : t.accent,
          border: subscribed ? `1px solid ${t.surfaceBorder}` : "none",
          borderRadius: 6, padding: "6px 14px",
          cursor: busy || denied ? "not-allowed" : "pointer",
          color: subscribed ? t.text : "#fff",
          fontSize: 13, fontWeight: 500,
          opacity: busy || denied ? 0.5 : 1,
        }}
      >
        {subscribed ? "Disable" : "Enable"}
      </button>
    </div>
  );
}

function UnreadNotificationsSection() {
  const t = useThemeTokens();
  const rulesQuery = useUnreadRules();
  const updateRule = useUpdateUnreadRule();
  const globalRule = rulesQuery.data?.rules.find((rule) => rule.channel_id === null);
  const targetIds = globalRule?.target_ids ?? [];
  const enabled = globalRule?.enabled ?? true;
  const immediateEnabled = globalRule?.immediate_enabled ?? true;
  const reminderEnabled = globalRule?.reminder_enabled ?? true;
  const reminderDelay = globalRule?.reminder_delay_minutes ?? 5;
  const targets = rulesQuery.data?.targets ?? [];

  const saveRule = (patch: Partial<{
    enabled: boolean;
    target_ids: string[];
    immediate_enabled: boolean;
    reminder_enabled: boolean;
    reminder_delay_minutes: number;
  }>) => {
    updateRule.mutate({
      channel_id: null,
      enabled,
      target_mode: "inherit",
      target_ids: targetIds,
      immediate_enabled: immediateEnabled,
      reminder_enabled: reminderEnabled,
      reminder_delay_minutes: reminderDelay,
      preview_policy: globalRule?.preview_policy ?? "short",
      ...patch,
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "10px 0" }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
            <Bell size={16} color={enabled ? t.accent : t.textMuted} />
            <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>Unread agent replies</span>
          </div>
          <span style={{ fontSize: 11, color: t.textDim, paddingLeft: 26 }}>
            Notify when an agent replies in a session you do not have open.
          </span>
        </div>
        <button
          type="button"
          onClick={() => saveRule({ enabled: !enabled })}
          disabled={updateRule.isPending}
          style={{
            background: enabled ? t.accent : "transparent",
            border: enabled ? "none" : `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "6px 14px",
            color: enabled ? "#fff" : t.text,
            fontSize: 13,
            fontWeight: 500,
            opacity: updateRule.isPending ? 0.5 : 1,
          }}
        >
          {enabled ? "Enabled" : "Disabled"}
        </button>
      </div>
      {targets.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 26 }}>
          <span style={{ fontSize: 11, color: t.textDim }}>Targets</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {targets.map((target) => {
              const selected = targetIds.includes(target.id);
              return (
                <button
                  key={target.id}
                  type="button"
                  onClick={() => saveRule({
                    target_ids: selected
                      ? targetIds.filter((id) => id !== target.id)
                      : [...targetIds, target.id],
                  })}
                  style={{
                    border: `1px solid ${selected ? t.accent : t.surfaceBorder}`,
                    borderRadius: 6,
                    background: selected ? t.accentSubtle : "transparent",
                    color: selected ? t.accent : t.textMuted,
                    padding: "4px 8px",
                    fontSize: 11,
                  }}
                >
                  {target.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, paddingLeft: 26 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: t.textMuted }}>
          <input type="checkbox" checked={immediateEnabled} onChange={(e) => saveRule({ immediate_enabled: e.target.checked })} />
          Immediate
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: t.textMuted }}>
          <input type="checkbox" checked={reminderEnabled} onChange={(e) => saveRule({ reminder_enabled: e.target.checked })} />
          Reminder
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: t.textMuted }}>
          Delay
          <input
            type="number"
            min={1}
            value={reminderDelay}
            onChange={(e) => saveRule({ reminder_delay_minutes: Math.max(1, Number(e.target.value) || 5) })}
            style={{ width: 54, border: `1px solid ${t.surfaceBorder}`, borderRadius: 5, background: "transparent", color: t.text, padding: "3px 5px" }}
          />
          min
        </label>
      </div>
    </div>
  );
}

/** Install-as-app affordance. Only renders when the browser has fired
 *  `beforeinstallprompt` — Chrome/Edge on desktop and Android. Silent on
 *  iOS Safari (users install via Share → Add to Home Screen) and when the
 *  app is already installed (event is cleared in `appinstalled`). */
function InstallAppSection() {
  const event = useInstallPromptStore((s) => s.event);
  const promptInstall = useInstallPromptStore((s) => s.promptInstall);
  const t = useThemeTokens();
  if (!event) return null;
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: "10px 0" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
          <Download size={16} color={t.textMuted} />
          <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>Install Spindrel</span>
        </div>
        <span style={{ fontSize: 11, color: t.textDim, paddingLeft: 26 }}>
          Add to your home screen for a native-app feel.
        </span>
      </div>
      <button
        type="button"
        onClick={() => { void promptInstall(); }}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.accent, borderRadius: 6, padding: "6px 14px",
          border: "none", cursor: "pointer", color: "#fff", fontSize: 13, fontWeight: 500,
        }}
      >
        Install
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings screen
// ---------------------------------------------------------------------------

export default function SettingsScreen() {
  const t = useThemeTokens();
  const { data, isLoading, error } = useSettings();
  const { refreshing, onRefresh } = usePageRefresh();
  const updateMutation = useUpdateSettings();
  const resetMutation = useResetSetting();
  const { width } = useWindowSize();
  const isDesktop = width >= 768;

  const fbQuery = useGlobalFallbackModels();
  const fbUpdateMut = useUpdateGlobalFallbackModels();
  const [fbModels, setFbModels] = useState<FallbackModelEntry[]>([]);
  const [fbDirty, setFbDirty] = useState(false);
  const [fbSaved, setFbSaved] = useState(false);

  useEffect(() => {
    if (fbQuery.data?.models) { setFbModels(fbQuery.data.models); setFbDirty(false); }
  }, [fbQuery.data]);

  const handleFbChange = useCallback((v: FallbackModelEntry[]) => { setFbModels(v); setFbDirty(true); setFbSaved(false); }, []);

  const handleFbSave = useCallback(async () => {
    const clean = fbModels.filter((m) => m.model);
    await fbUpdateMut.mutateAsync(clean);
    setFbDirty(false); setFbSaved(true);
    setTimeout(() => setFbSaved(false), 2000);
  }, [fbModels, fbUpdateMut]);

  const groups = data?.groups ?? [];
  const allGroups = useMemo(
    () => [{ group: GLOBAL_GROUP, settings: [] as SettingItem[] }, ...groups, { group: BACKUP_GROUP, settings: [] as SettingItem[] }],
    [groups]
  );
  const groupNames = useMemo(() => allGroups.map((g) => g.group), [allGroups]);
  const [activeGroup, setActiveGroup] = useHashTab<string>(GLOBAL_GROUP, groupNames);
  const [localValues, setLocalValues] = useState<Record<string, any>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);
  const [resettingKey, setResettingKey] = useState<string | null>(null);

  useEffect(() => {
    if (!groups.length) return;
    const vals: Record<string, any> = {};
    for (const g of groups) for (const s of g.settings) vals[s.key] = s.value;
    setLocalValues(vals); setDirty({});
  }, [data]);

  const handleLocalChange = useCallback((key: string, value: any) => {
    setLocalValues((prev) => ({ ...prev, [key]: value }));
    for (const g of groups) {
      const item = g.settings.find((s) => s.key === key);
      if (item) { setDirty((prev) => ({ ...prev, [key]: value !== item.value && String(value) !== String(item.value) })); break; }
    }
    setSaved(false);
  }, [groups]);

  const changedKeys = useMemo(() => Object.entries(dirty).filter(([, v]) => v).map(([k]) => k), [dirty]);

  const handleSave = useCallback(() => {
    if (!changedKeys.length) return;
    const updates: Record<string, any> = {};
    for (const key of changedKeys) {
      const schema = groups.flatMap((g) => g.settings).find((s) => s.key === key);
      let val = localValues[key];
      if (schema?.type === "int") { val = val === "" && schema.nullable ? null : parseInt(val, 10); if (!schema.nullable && isNaN(val)) continue; }
      else if (schema?.type === "float") { val = parseFloat(val); if (isNaN(val)) continue; }
      updates[key] = val;
    }
    updateMutation.mutate(updates, { onSuccess: () => { setDirty({}); setSaved(true); setTimeout(() => setSaved(false), 2000); } });
  }, [changedKeys, localValues, groups, updateMutation]);

  const handleReset = useCallback((key: string) => {
    setResettingKey(key);
    const item = groups.flatMap((g) => g.settings).find((s) => s.key === key);
    if (item?.widget === "model") {
      const pk = key === "IMAGE_GENERATION_MODEL" ? "IMAGE_GENERATION_PROVIDER_ID" : key === "CONTEXTUAL_RETRIEVAL_MODEL" ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID" : key + "_PROVIDER_ID";
      resetMutation.mutate(pk);
    }
    resetMutation.mutate(key, { onSettled: () => setResettingKey(null) });
  }, [resetMutation, groups]);

  const isGlobal = activeGroup === GLOBAL_GROUP;
  const isBackup = activeGroup === BACKUP_GROUP;
  const activeSettings = groups.find((g) => g.group === activeGroup)?.settings ?? [];
  const visibleSettings = activeSettings.filter((s: any) => !s.ui_hidden);
  const isMemoryGroup = activeGroup === "Memory & Learning";

  if (isLoading) {
    return (
      <div style={{ display: "flex", flex: 1, background: t.surface, alignItems: "center", justifyContent: "center" }}>
        <Spinner size={32} color={t.accent} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display: "flex", flex: 1, background: t.surface, alignItems: "center", justifyContent: "center", padding: 16 }}>
        <span style={{ color: t.danger, fontSize: 13 }}>Failed to load settings: {error instanceof Error ? error.message : "Unknown error"}</span>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, overflow: "hidden" }}>
      <PageHeader variant="list"
        title="Settings"
        right={
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            {saved && (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Check size={14} color="#22c55e" />
                <span style={{ color: "#22c55e", fontSize: 12 }}>Saved</span>
              </div>
            )}
            {changedKeys.length > 0 && (
              <button
                type="button"
                onClick={handleSave}
                disabled={updateMutation.isPending}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  background: t.accent, borderRadius: 6, padding: "6px 14px",
                  border: "none", cursor: "pointer",
                }}
              >
                {updateMutation.isPending ? <Spinner size={14} color="#fff" /> : <Save size={13} color="#fff" />}
                <span style={{ color: "#fff", fontSize: 13, fontWeight: 500 }}>
                  Save{changedKeys.length > 1 ? ` (${changedKeys.length})` : ""}
                </span>
              </button>
            )}
          </div>
        }
      />

      <ServerStatusStrip />

      <div style={{ display: "flex", flexDirection: "row", flex: 1, minHeight: 0 }}>
        {isDesktop && (
          <div style={{ width: 200, borderRight: `1px solid ${t.surfaceBorder}`, padding: "12px 8px", overflowY: "auto", flexShrink: 0 }}>
            <GroupNav groups={allGroups} activeGroup={activeGroup} onSelect={setActiveGroup} />
          </div>
        )}

        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1" contentContainerStyle={{ maxWidth: 900, padding: "16px 20px" }}>
          {/* Mobile group selector */}
          {!isDesktop && (
            <div style={{ display: "flex", flexDirection: "row", gap: 6, overflowX: "auto", marginBottom: 16 }}>
              {allGroups.map((g) => (
                <button
                  type="button"
                  key={g.group}
                  onClick={() => setActiveGroup(g.group)}
                  style={{
                    whiteSpace: "nowrap", padding: "6px 12px", borderRadius: 16, fontSize: 12, flexShrink: 0,
                    background: activeGroup === g.group ? "rgb(var(--color-accent) / 0.12)" : "transparent",
                    color: activeGroup === g.group ? t.accent : t.textMuted,
                    fontWeight: activeGroup === g.group ? 500 : 400,
                    border: `1px solid ${activeGroup === g.group ? "rgb(var(--color-accent) / 0.3)" : t.surfaceBorder}`,
                    cursor: "pointer",
                  }}
                >
                  {g.group}
                </button>
              ))}
            </div>
          )}

          {/* Group title */}
          <h2 style={{ fontSize: 18, fontWeight: 600, color: t.text, margin: "0 0 8px 0" }}>{activeGroup}</h2>

          {isGlobal && <AppearanceSection />}
          {isGlobal && <InstallAppSection />}
          {isGlobal && <NotificationsSection />}
          {isGlobal && <UnreadNotificationsSection />}
          {isGlobal && (
            <>
              <GlobalSection fbModels={fbModels} onFbChange={handleFbChange} onFbSave={handleFbSave} fbDirty={fbDirty} fbSaving={fbUpdateMut.isPending} fbSaved={fbSaved} fbError={fbUpdateMut.isError} fbLoading={fbQuery.isLoading} />
              <ModelTiersSection />
            </>
          )}
          {isBackup && <BackupSection />}

          {/* Memory & Learning: unified section — memory scheme at top */}
          {isMemoryGroup && <MemorySchemeSection />}

          {/* Auto-rendered settings — simple divider list, no card wrappers */}
          {!isGlobal && !isBackup && visibleSettings.map((item, idx) => {
            const FILE_MODE_KEYS = new Set(["SECTION_INDEX_COUNT", "SECTION_INDEX_VERBOSITY"]);
            const historyMode = String(localValues["DEFAULT_HISTORY_MODE"] ?? "file");
            const isFileModeOnly = FILE_MODE_KEYS.has(item.key);
            const dimmed = isFileModeOnly && historyMode !== "file";

            return (
              <div key={item.key} style={dimmed ? { opacity: 0.4 } : undefined}>
                {/* Sub-section header */}
                {SUB_SECTION_HEADERS[item.key] && (
                  <div style={{ paddingTop: idx > 0 ? 20 : 8, paddingBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: t.text, letterSpacing: 0.3 }}>
                      {SUB_SECTION_HEADERS[item.key].title}
                    </span>
                    {SUB_SECTION_HEADERS[item.key].desc && (
                      <span style={{ display: "block", fontSize: 11, color: t.textDim, marginTop: 2 }}>
                        {SUB_SECTION_HEADERS[item.key].desc}
                      </span>
                    )}
                  </div>
                )}
                {/* Banners */}
                {item.key === "MEMORY_HYGIENE_ENABLED" && <MemoryHygieneGroupBanner />}
                {item.key === "SECTION_INDEX_COUNT" && <FileModeOnlyBanner historyMode={historyMode} />}
                {/* Divider between items (not before first) */}
                {idx > 0 && !SUB_SECTION_HEADERS[item.key] && (
                  <div style={{ height: 1, background: t.surfaceBorder, opacity: 0.5 }} />
                )}
                <SettingRow
                  item={item}
                  localValue={localValues[item.key]}
                  providerValue={item.widget === "model" ? String(localValues[
                    item.key === "IMAGE_GENERATION_MODEL" ? "IMAGE_GENERATION_PROVIDER_ID"
                    : item.key === "CONTEXTUAL_RETRIEVAL_MODEL" ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID"
                    : item.key + "_PROVIDER_ID"
                  ] ?? "") : undefined}
                  onLocalChange={handleLocalChange}
                  onReset={handleReset}
                  isResetting={resettingKey === item.key}
                />
              </div>
            );
          })}

          {/* Memory & Learning: dreaming bot management at bottom */}
          {isMemoryGroup && <DreamingManagementSection />}

          {activeGroup === "Attachments" && (
            <div style={{
              background: `rgb(var(--color-accent) / 0.06)`, border: `1px solid rgb(var(--color-accent) / 0.15)`,
              borderRadius: 6, padding: 14, marginBottom: 12,
              display: "flex", flexDirection: "column", gap: 6,
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.text }}>How Summarization Relates to Agent Vision</div>
              <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
                <strong style={{ color: t.text }}>Summarization</strong> pre-processes attachments into text descriptions
                using the summary model configured below. This is <strong style={{ color: t.text }}>separate</strong> from
                the bot&apos;s own model vision. When a bot&apos;s model supports vision, it receives the raw image as
                a native image input <em>alongside</em> the summary. When it doesn&apos;t, the summary is the only way
                the model can understand the image. Text files are extracted and truncated regardless of vision support.
              </div>
            </div>
          )}
          {(activeGroup === "Attachments" || activeGroup === "Model Elevation") && (
            <BotOverridesList group={activeGroup} />
          )}

          {activeGroup === "Chat History" && String(localValues["DEFAULT_HISTORY_MODE"] ?? "file") === "file" && (
            <ChatHistoryExtras verbosity={String(localValues["SECTION_INDEX_VERBOSITY"] ?? "standard")} />
          )}
        </RefreshableScrollView>
      </div>
    </div>
  );
}
