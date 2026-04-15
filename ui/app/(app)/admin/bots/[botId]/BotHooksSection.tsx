import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { Plus, Pencil, Trash2, Zap, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  FormRow, TextInput, SelectInput, Row, Col,
} from "@/src/components/shared/FormControls";
import { ActionButton, StatusBadge, InfoBanner } from "@/src/components/shared/SettingsControls";
import {
  useBotHooks,
  useCreateBotHook,
  useUpdateBotHook,
  useDeleteBotHook,
  type BotHookItem,
} from "@/src/api/hooks/useBotHooks";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TRIGGER_OPTIONS = [
  { value: "before_access", label: "Before Access" },
  { value: "after_write", label: "After Write" },
  { value: "after_exec", label: "After Exec" },
];

const TRIGGER_BADGE: Record<string, { variant: "warning" | "success" | "info"; label: string }> = {
  before_access: { variant: "warning", label: "before access" },
  after_write: { variant: "success", label: "after write" },
  after_exec: { variant: "info", label: "after exec" },
};

const ON_FAILURE_OPTIONS = [
  { value: "block", label: "Block" },
  { value: "warn", label: "Warn" },
];

const TRIGGER_DESCRIPTIONS: Record<string, string> = {
  before_access: "Runs before any file read, write, or exec on a matching path. Use for freshness (e.g. git pull).",
  after_write: "Runs after file mutations on a matching path, debounced. Use for propagation (e.g. git commit + push).",
  after_exec: "Runs after command execution in a matching working directory. Use for cleanup.",
};

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

interface HookFormState {
  name: string;
  trigger: string;
  path: string;
  command: string;
  cooldown_seconds: string;
  on_failure: string;
}

const EMPTY_FORM: HookFormState = {
  name: "",
  trigger: "before_access",
  path: "",
  command: "",
  cooldown_seconds: "60",
  on_failure: "block",
};

function hookToForm(h: BotHookItem): HookFormState {
  return {
    name: h.name,
    trigger: h.trigger,
    path: h.conditions?.path || "",
    command: h.command,
    cooldown_seconds: String(h.cooldown_seconds),
    on_failure: h.on_failure,
  };
}

// ---------------------------------------------------------------------------
// HookForm — create / edit
// ---------------------------------------------------------------------------

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
  const triggerDesc = TRIGGER_DESCRIPTIONS[form.trigger];

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 14,
      padding: 16, borderRadius: 10,
      background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <Row>
        <Col>
          <FormRow label="Name">
            <TextInput
              value={form.name}
              onChangeText={(v) => setForm({ ...form, name: v })}
              placeholder="e.g. vault-sync-pull"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="Trigger">
            <SelectInput
              value={form.trigger}
              onChange={(v) => setForm({
                ...form,
                trigger: v,
                on_failure: v === "before_access" ? "block" : "warn",
              })}
              options={TRIGGER_OPTIONS}
            />
          </FormRow>
        </Col>
      </Row>

      {triggerDesc && (
        <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5", marginTop: -6 }}>
          {triggerDesc}
        </div>
      )}

      <FormRow label="Path Pattern" description="Glob matched against the container path (e.g. /workspace/repos/vault/**)">
        <TextInput
          value={form.path}
          onChangeText={(v) => setForm({ ...form, path: v })}
          placeholder="/workspace/repos/myrepo/**"
          style={{ fontFamily: "monospace", fontSize: 14 }}
        />
      </FormRow>

      <FormRow label="Command" description="Shell command executed in the bot's workspace container">
        <textarea
          value={form.command}
          onChange={(e) => setForm({ ...form, command: e.target.value })}
          placeholder="cd /workspace/repos/myrepo && git pull --ff-only"
          style={{
            background: t.codeBg,
            border: `1px solid ${t.codeBorder}`,
            borderRadius: 8,
            padding: "10px 12px",
            color: t.codeText,
            fontSize: 13,
            fontFamily: "monospace",
            width: "100%",
            minHeight: 72,
            resize: "vertical",
            outline: "none",
            lineHeight: "1.5",
          }}
        />
      </FormRow>

      <Row>
        <Col minWidth={160}>
          <FormRow label="Cooldown" description="Min seconds between firings">
            <TextInput
              value={form.cooldown_seconds}
              onChangeText={(v) => setForm({ ...form, cooldown_seconds: v })}
              type="number"
              placeholder="60"
            />
          </FormRow>
        </Col>
        <Col minWidth={160}>
          <FormRow label="On Failure" description={form.on_failure === "block" ? "Abort the triggering operation" : "Log warning and continue"}>
            <SelectInput
              value={form.on_failure}
              onChange={(v) => setForm({ ...form, on_failure: v })}
              options={ON_FAILURE_OPTIONS}
            />
          </FormRow>
        </Col>
      </Row>

      <div style={{ display: "flex", flexDirection: "row", gap: 8, marginTop: 2 }}>
        <ActionButton
          label={submitLabel}
          onPress={() => onSubmit(form)}
          disabled={!form.name.trim() || !form.command.trim()}
          size="small"
        />
        <ActionButton
          label="Cancel"
          onPress={onCancel}
          variant="secondary"
          size="small"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// HookRow — single hook display
// ---------------------------------------------------------------------------

function HookRow({
  hook,
  onEdit,
  onToggle,
  onDelete,
}: {
  hook: BotHookItem;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const t = useThemeTokens();
  const badge = TRIGGER_BADGE[hook.trigger] || TRIGGER_BADGE.before_access;

  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 12,
      padding: "12px 14px", borderRadius: 8,
      background: t.inputBg, border: `1px solid ${t.surfaceRaised}`,
      opacity: hook.enabled ? 1 : 0.45,
      transition: "opacity 0.15s",
    }}>
      {/* Left: toggle indicator */}
      <button
        onClick={onToggle}
        title={hook.enabled ? "Disable hook" : "Enable hook"}
        style={{
          width: 8, height: 8, borderRadius: 4, flexShrink: 0, marginTop: 6,
          background: hook.enabled ? t.success : t.surfaceBorder,
          border: "none", cursor: "pointer", padding: 0,
          transition: "background 0.15s",
        }}
      />

      {/* Center: content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{hook.name}</span>
          <StatusBadge label={badge.label} variant={badge.variant} />
          {hook.on_failure === "block" && (
            <StatusBadge label="blocking" variant="danger" />
          )}
          <span style={{ fontSize: 10, color: t.textDim }}>
            {hook.cooldown_seconds}s cooldown
          </span>
        </div>

        {hook.conditions?.path && (
          <div style={{
            fontSize: 12, fontFamily: "monospace", color: t.textDim,
            marginTop: 4, padding: "3px 8px", borderRadius: 4,
            background: t.codeBg, display: "inline-block",
          }}>
            {hook.conditions.path}
          </div>
        )}

        <div style={{
          fontSize: 12, fontFamily: "monospace", color: t.textMuted,
          marginTop: 4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          <Zap size={10} color={t.textDim} style={{ marginRight: 4, verticalAlign: "middle" }} />
          {hook.command}
        </div>
      </div>

      {/* Right: actions */}
      <div style={{ display: "flex", flexDirection: "row", gap: 4, flexShrink: 0, marginTop: 2 }}>
        <button
          onClick={onEdit}
          title="Edit hook"
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
            width: 30, height: 30, borderRadius: 6,
            background: "transparent", border: `1px solid ${t.surfaceBorder}`,
            cursor: "pointer", transition: "background 0.12s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Pencil size={12} color={t.textDim} />
        </button>
        <button
          onClick={onDelete}
          title="Delete hook"
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
            width: 30, height: 30, borderRadius: 6,
            background: "transparent", border: `1px solid ${t.surfaceBorder}`,
            cursor: "pointer", transition: "background 0.12s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = t.dangerSubtle; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Trash2 size={12} color={t.danger} />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BotHooksSection — main export
// ---------------------------------------------------------------------------

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
      name: form.name.trim(),
      trigger: form.trigger,
      conditions: form.path.trim() ? { path: form.path.trim() } : {},
      command: form.command.trim(),
      cooldown_seconds: parseInt(form.cooldown_seconds) || 60,
      on_failure: form.on_failure || undefined,
    }, { onSuccess: () => setShowCreate(false) });
  };

  const handleUpdate = (hookId: string, form: HookFormState) => {
    updateMutation.mutate({
      hookId,
      data: {
        name: form.name.trim(),
        trigger: form.trigger,
        conditions: form.path.trim() ? { path: form.path.trim() } : {},
        command: form.command.trim(),
        cooldown_seconds: parseInt(form.cooldown_seconds) || 60,
        on_failure: form.on_failure,
      },
    }, { onSuccess: () => setEditingId(null) });
  };

  const handleDelete = (hookId: string) => {
    if (confirm("Delete this hook? This cannot be undone.")) {
      deleteMutation.mutate(hookId);
    }
  };

  const handleToggle = (hook: BotHookItem) => {
    updateMutation.mutate({
      hookId: hook.id,
      data: { enabled: !hook.enabled },
    });
  };

  const activeCount = hooks?.filter((h) => h.enabled).length ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Hooks</span>
          {hooks && hooks.length > 0 && (
            <span style={{ fontSize: 11, color: t.textDim }}>
              {activeCount} active
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: t.textDim, lineHeight: "1.5" }}>
          Run shell commands automatically when this bot accesses or modifies files in its workspace.
        </div>
      </div>

      {/* Hook list */}
      {isLoading ? (
        <div style={{ padding: 32, textAlign: "center" }}>
          <Spinner color={t.accent} />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {hooks?.map((h) =>
            editingId === h.id ? (
              <HookForm
                key={h.id}
                initial={hookToForm(h)}
                onSubmit={(form) => handleUpdate(h.id, form)}
                onCancel={() => setEditingId(null)}
                submitLabel="Save Changes"
              />
            ) : (
              <HookRow
                key={h.id}
                hook={h}
                onEdit={() => setEditingId(h.id)}
                onToggle={() => handleToggle(h)}
                onDelete={() => handleDelete(h.id)}
              />
            ),
          )}

          {(!hooks || hooks.length === 0) && !showCreate && (
            <InfoBanner variant="info">
              <div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>No hooks configured</div>
                <div>
                  Hooks let this bot automatically run commands when files are accessed or modified.
                  Common use: <span style={{ fontFamily: "monospace" }}>git pull</span> before reading a
                  cloned repo, or <span style={{ fontFamily: "monospace" }}>git commit && push</span> after writing.
                </div>
              </div>
            </InfoBanner>
          )}
        </div>
      )}

      {/* Create form or add button */}
      {showCreate ? (
        <HookForm
          initial={EMPTY_FORM}
          onSubmit={handleCreate}
          onCancel={() => setShowCreate(false)}
          submitLabel="Create Hook"
        />
      ) : (
        <ActionButton
          label="Add Hook"
          onPress={() => setShowCreate(true)}
          size="small"
          icon={<Plus size={14} />}
        />
      )}
    </div>
  );
}
