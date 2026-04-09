import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useBotHooks,
  useCreateBotHook,
  useUpdateBotHook,
  useDeleteBotHook,
  type BotHookItem,
} from "@/src/api/hooks/useBotHooks";

const TRIGGER_OPTIONS = [
  { value: "before_access", label: "Before Access", desc: "Runs before any read/write/exec on matching path" },
  { value: "after_write", label: "After Write", desc: "Runs after file mutation on matching path (debounced)" },
  { value: "after_exec", label: "After Exec", desc: "Runs after command execution in matching directory" },
];

const TRIGGER_COLORS: Record<string, (t: any) => { bg: string; fg: string }> = {
  before_access: (t) => ({ bg: t.warningSubtle, fg: t.warning }),
  after_write: (t) => ({ bg: t.successSubtle, fg: t.success }),
  after_exec: (t) => ({ bg: t.accentSubtle, fg: t.accent }),
};

interface HookFormState {
  name: string;
  trigger: string;
  path: string;
  command: string;
  cooldown_seconds: number;
  on_failure: string;
  enabled: boolean;
}

const EMPTY_FORM: HookFormState = {
  name: "",
  trigger: "before_access",
  path: "",
  command: "",
  cooldown_seconds: 60,
  on_failure: "",
  enabled: true,
};

function HookForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial: HookFormState;
  onSubmit: (data: HookFormState) => void;
  onCancel: () => void;
  submitLabel: string;
}) {
  const t = useThemeTokens();
  const [form, setForm] = useState<HookFormState>(initial);

  const inputStyle = {
    padding: "8px 10px",
    borderRadius: 6,
    border: `1px solid ${t.surfaceBorder}`,
    background: t.inputBg,
    color: t.text,
    fontSize: 13,
    fontFamily: "monospace" as const,
    width: "100%",
  };

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 10,
      padding: 14, borderRadius: 8,
      background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{ display: "flex", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>Name</label>
          <input
            style={inputStyle}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. vault-sync-pull"
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>Trigger</label>
          <select
            style={{ ...inputStyle, fontFamily: "inherit" }}
            value={form.trigger}
            onChange={(e) => setForm({ ...form, trigger: e.target.value })}
          >
            {TRIGGER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>
          Path Pattern (glob)
        </label>
        <input
          style={inputStyle}
          value={form.path}
          onChange={(e) => setForm({ ...form, path: e.target.value })}
          placeholder="/workspace/repos/myrepo/**"
        />
      </div>

      <div>
        <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>Command</label>
        <textarea
          style={{ ...inputStyle, minHeight: 60, resize: "vertical" }}
          value={form.command}
          onChange={(e) => setForm({ ...form, command: e.target.value })}
          placeholder="cd /workspace/repos/myrepo && git pull --ff-only"
        />
      </div>

      <div style={{ display: "flex", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>
            Cooldown (seconds)
          </label>
          <input
            type="number"
            style={inputStyle}
            value={form.cooldown_seconds}
            onChange={(e) => setForm({ ...form, cooldown_seconds: parseInt(e.target.value) || 60 })}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, color: t.textDim, marginBottom: 4, display: "block" }}>On Failure</label>
          <select
            style={{ ...inputStyle, fontFamily: "inherit" }}
            value={form.on_failure || (form.trigger === "before_access" ? "block" : "warn")}
            onChange={(e) => setForm({ ...form, on_failure: e.target.value })}
          >
            <option value="block">Block (abort operation)</option>
            <option value="warn">Warn (log and continue)</option>
          </select>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button
          onClick={() => onSubmit(form)}
          disabled={!form.name || !form.command}
          style={{
            padding: "8px 16px", borderRadius: 6,
            background: t.accent, border: "none",
            cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#fff",
            opacity: (!form.name || !form.command) ? 0.5 : 1,
          }}
        >
          {submitLabel}
        </button>
        <button
          onClick={onCancel}
          style={{
            padding: "8px 16px", borderRadius: 6,
            background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
            cursor: "pointer", fontSize: 12, color: t.textMuted,
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function hookToForm(h: BotHookItem): HookFormState {
  return {
    name: h.name,
    trigger: h.trigger,
    path: h.conditions?.path || "",
    command: h.command,
    cooldown_seconds: h.cooldown_seconds,
    on_failure: h.on_failure,
    enabled: h.enabled,
  };
}

export function BotHooksSection({ botId }: { botId: string }) {
  const t = useThemeTokens();
  const { data: hooks, isLoading } = useBotHooks(botId);
  const createMutation = useCreateBotHook();
  const updateMutation = useUpdateBotHook(botId);
  const deleteMutation = useDeleteBotHook(botId);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const handleCreate = (form: HookFormState) => {
    createMutation.mutate({
      bot_id: botId,
      name: form.name,
      trigger: form.trigger,
      conditions: form.path ? { path: form.path } : {},
      command: form.command,
      cooldown_seconds: form.cooldown_seconds,
      on_failure: form.on_failure || undefined,
      enabled: form.enabled,
    }, { onSuccess: () => setShowCreate(false) });
  };

  const handleUpdate = (hookId: string, form: HookFormState) => {
    updateMutation.mutate({
      hookId,
      data: {
        name: form.name,
        trigger: form.trigger,
        conditions: form.path ? { path: form.path } : {},
        command: form.command,
        cooldown_seconds: form.cooldown_seconds,
        on_failure: form.on_failure,
        enabled: form.enabled,
      },
    }, { onSuccess: () => setEditingId(null) });
  };

  const handleDelete = (hookId: string) => {
    if (confirm("Delete this hook?")) {
      deleteMutation.mutate(hookId);
    }
  };

  const handleToggle = (hook: BotHookItem) => {
    updateMutation.mutate({
      hookId: hook.id,
      data: { enabled: !hook.enabled },
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Hooks</div>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Lifecycle hooks that run shell commands automatically in response to file access or command execution.
        Hooks run in the bot's workspace container.
      </div>

      {isLoading ? (
        <ActivityIndicator color={t.accent} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {hooks?.map((h) => {
            if (editingId === h.id) {
              return (
                <HookForm
                  key={h.id}
                  initial={hookToForm(h)}
                  onSubmit={(form) => handleUpdate(h.id, form)}
                  onCancel={() => setEditingId(null)}
                  submitLabel="Save"
                />
              );
            }

            const colors = (TRIGGER_COLORS[h.trigger] || TRIGGER_COLORS.before_access)(t);
            return (
              <div
                key={h.id}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 12px", borderRadius: 6,
                  background: t.inputBg, border: `1px solid ${t.surfaceRaised}`,
                  opacity: h.enabled ? 1 : 0.5,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{h.name}</span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 3,
                      background: colors.bg, color: colors.fg,
                    }}>
                      {h.trigger}
                    </span>
                    <span style={{
                      fontSize: 10, padding: "1px 6px", borderRadius: 3,
                      background: h.on_failure === "block" ? t.dangerSubtle : t.surfaceOverlay,
                      color: h.on_failure === "block" ? t.danger : t.textDim,
                    }}>
                      {h.on_failure}
                    </span>
                  </div>
                  {h.conditions?.path && (
                    <div style={{ fontSize: 11, fontFamily: "monospace", color: t.textDim, marginBottom: 2 }}>
                      {h.conditions.path}
                    </div>
                  )}
                  <div style={{
                    fontSize: 11, fontFamily: "monospace", color: t.textMuted,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>
                    {h.command}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <button
                    onClick={() => handleToggle(h)}
                    title={h.enabled ? "Disable" : "Enable"}
                    style={{
                      padding: "4px 8px", borderRadius: 4, fontSize: 11,
                      background: h.enabled ? t.successSubtle : t.surfaceOverlay,
                      border: `1px solid ${h.enabled ? t.success + "33" : t.surfaceBorder}`,
                      color: h.enabled ? t.success : t.textDim,
                      cursor: "pointer",
                    }}
                  >
                    {h.enabled ? "On" : "Off"}
                  </button>
                  <button
                    onClick={() => setEditingId(h.id)}
                    style={{
                      padding: "4px 8px", borderRadius: 4, fontSize: 11,
                      background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
                      color: t.textMuted, cursor: "pointer",
                    }}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(h.id)}
                    style={{
                      padding: "4px 8px", borderRadius: 4, fontSize: 11,
                      background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
                      color: t.danger, cursor: "pointer",
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })}

          {(!hooks || hooks.length === 0) && (
            <div style={{
              padding: 20, textAlign: "center", borderRadius: 8,
              background: t.surfaceOverlay, border: `1px dashed ${t.surfaceBorder}`,
              color: t.textDim, fontSize: 13,
            }}>
              No hooks configured. Hooks run shell commands automatically when files are accessed or modified.
            </div>
          )}
        </div>
      )}

      {showCreate ? (
        <HookForm
          initial={EMPTY_FORM}
          onSubmit={handleCreate}
          onCancel={() => setShowCreate(false)}
          submitLabel="Create Hook"
        />
      ) : (
        <button
          onClick={() => setShowCreate(true)}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            padding: "10px 16px", borderRadius: 6,
            background: t.accent, border: "none",
            cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#fff",
          }}
        >
          Add Hook
        </button>
      )}
    </div>
  );
}
