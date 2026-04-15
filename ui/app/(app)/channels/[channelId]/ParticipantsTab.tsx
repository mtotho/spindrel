import { Spinner } from "@/src/components/shared/Spinner";
/**
 * ParticipantsTab — self-managing tab for multi-bot channel member configuration.
 * Handles its own mutations; no parent Save button needed.
 */
import { useState, useCallback } from "react";
import { Bot, ChevronDown, ChevronRight, Plus, X, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelBotMembers,
  useAddBotMember,
  useRemoveBotMember,
  useUpdateBotMemberConfig,
} from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import {
  Section, FormRow, SelectInput, Toggle, EmptyState,
} from "@/src/components/shared/FormControls";
import { AdvancedSection, StatusBadge } from "@/src/components/shared/SettingsControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import type { ChannelBotMember, ChannelBotMemberConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
interface Props {
  channelId: string;
  primaryBotId: string;
}

export function ParticipantsTab({ channelId, primaryBotId }: Props) {
  const t = useThemeTokens();
  const { data: members = [], isLoading } = useChannelBotMembers(channelId);
  const addMember = useAddBotMember(channelId);
  const removeMember = useRemoveBotMember(channelId);
  const updateConfig = useUpdateBotMemberConfig(channelId);
  const { data: allBots = [] } = useBots();
  const [showPicker, setShowPicker] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<ChannelBotMember | null>(null);

  const primaryBot = allBots.find((b) => b.id === primaryBotId);
  const memberBotIds = new Set(members.map((m) => m.bot_id));
  const availableBots = allBots.filter(
    (b) => b.id !== primaryBotId && !memberBotIds.has(b.id)
  );

  if (isLoading) {
    return (
      <div style={{ padding: 32, display: "flex", flexDirection: "row", justifyContent: "center" }}>
        <Spinner color={t.accent} />
      </div>
    );
  }

  return (
    <>
      {/* Primary bot */}
      <Section title="Participants">
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, padding: "8px 0" }}>
          <Bot size={16} color={t.accent} />
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
            {primaryBot?.name || primaryBotId}
          </span>
          <Link to={`/admin/bots/${primaryBotId}`} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3, textDecoration: "none" }}>
            <ExternalLink size={10} color={t.accent} />
            <span style={{ fontSize: 11, color: t.accent }}>config</span>
          </Link>
          <StatusBadge label="primary" variant="info" />
        </div>
      </Section>

      {/* Member bots */}
      <Section
        title="Member Bots"
        description="Members respond when @-mentioned in chat."
        action={
          availableBots.length > 0 && !showPicker ? (
            <button
              onClick={() => setShowPicker(true)}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 5,
                padding: "5px 10px",
                fontSize: 12,
                fontWeight: 500,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                background: "transparent",
                color: t.accent,
                cursor: "pointer",
              }}
            >
              <Plus size={12} />
              Add Bot
            </button>
          ) : undefined
        }
      >
        {/* Bot picker dropdown */}
        {showPicker && (
          <BotPicker
            bots={availableBots}
            onSelect={(botId) => {
              addMember.mutate(botId);
              setShowPicker(false);
            }}
            onCancel={() => setShowPicker(false)}
            isPending={addMember.isPending}
          />
        )}

        {/* Member list */}
        {members.length === 0 && !showPicker && (
          <EmptyState message="Add bots to this channel. Members respond when @-mentioned in chat." />
        )}

        {members.map((m) => (
          <MemberCard
            key={m.id}
            member={m}
            onRemove={() => setConfirmRemove(m)}
            isRemoving={removeMember.isPending}
            onUpdateConfig={(config) =>
              updateConfig.mutate({ botId: m.bot_id, config })
            }
          />
        ))}
      </Section>

      {/* Confirm remove dialog */}
      <ConfirmDialog
        open={confirmRemove !== null}
        title="Remove member bot"
        message={`Remove ${confirmRemove?.bot_name || confirmRemove?.bot_id || ""} from this channel? Any per-member config will be lost.`}
        confirmLabel="Remove"
        variant="danger"
        onConfirm={() => {
          if (confirmRemove) removeMember.mutate(confirmRemove.bot_id);
          setConfirmRemove(null);
        }}
        onCancel={() => setConfirmRemove(null)}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Bot picker
// ---------------------------------------------------------------------------
function BotPicker({
  bots,
  onSelect,
  onCancel,
  isPending,
}: {
  bots: Array<{ id: string; name: string }>;
  onSelect: (botId: string) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        background: t.surfaceRaised,
        overflow: "hidden",
        boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
      }}
    >
      {bots.map((b) => (
        <button
          key={b.id}
          onClick={() => onSelect(b.id)}
          disabled={isPending}
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 8,
            width: "100%",
            padding: "8px 12px",
            border: "none",
            background: "transparent",
            cursor: isPending ? "wait" : "pointer",
            fontSize: 13,
            color: t.text,
            textAlign: "left",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = `${t.accent}10`; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Bot size={14} color={t.textDim} />
          {b.name}
        </button>
      ))}
      <button
        onClick={onCancel}
        style={{
          width: "100%",
          padding: "6px 12px",
          border: "none",
          borderTop: `1px solid ${t.surfaceBorder}`,
          background: "transparent",
          cursor: "pointer",
          fontSize: 11,
          color: t.textDim,
          textAlign: "center",
        }}
      >
        Cancel
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Member card (expandable with config form)
// ---------------------------------------------------------------------------
function MemberCard({
  member,
  onRemove,
  isRemoving,
  onUpdateConfig,
}: {
  member: ChannelBotMember;
  onRemove: () => void;
  isRemoving: boolean;
  onUpdateConfig: (config: Partial<ChannelBotMemberConfig>) => void;
}) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const cfg = member.config || {};

  // Build summary badges
  const badges: string[] = [];
  if (cfg.auto_respond) badges.push("auto-respond");
  if (cfg.response_style) badges.push(cfg.response_style);
  if (cfg.priority && cfg.priority !== 0) badges.push(`priority ${cfg.priority}`);
  if (cfg.max_rounds) badges.push(`${cfg.max_rounds} rounds`);

  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        background: t.surface,
        overflow: "hidden",
      }}
    >
      {/* Collapsed header */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          cursor: "pointer",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown size={12} color={t.textDim} />
        ) : (
          <ChevronRight size={12} color={t.textDim} />
        )}
        <Bot size={14} color={t.textDim} />
        <span style={{ fontSize: 13, fontWeight: 500, color: t.text, flex: 1, minWidth: 0 }}>
          {member.bot_name || member.bot_id}
        </span>
        {/* Config badges */}
        {!expanded && badges.length > 0 && (
          <div style={{ display: "flex", flexDirection: "row", gap: 4, flexWrap: "wrap" }}>
            {badges.map((b) => (
              <span
                key={b}
                style={{
                  fontSize: 10,
                  color: t.textDim,
                  background: `${t.textDim}15`,
                  borderRadius: 4,
                  padding: "1px 6px",
                }}
              >
                {b}
              </span>
            ))}
          </div>
        )}
        {/* Bot config link */}
        <Link
          to={`/admin/bots/${member.bot_id}`}
          onClick={(e) => e.stopPropagation()}
          style={{ display: "flex", flexDirection: "row", alignItems: "center", padding: 4, flexShrink: 0 }}
          title="Bot settings"
        >
          <ExternalLink size={12} color={t.accent} />
        </Link>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          disabled={isRemoving}
          title="Remove from channel"
          style={{
            border: "none",
            background: "transparent",
            cursor: "pointer",
            padding: 4,
            display: "flex", flexDirection: "row",
            alignItems: "center",
            opacity: 0.5,
            flexShrink: 0,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.5"; }}
        >
          <X size={14} color={t.danger} />
        </button>
      </div>

      {/* Expanded config form — key forces remount when config changes from server */}
      {expanded && (
        <MemberConfigForm
          key={JSON.stringify(cfg)}
          config={cfg}
          onUpdate={onUpdateConfig}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config form (auto-saves on change)
// ---------------------------------------------------------------------------
function MemberConfigForm({
  config,
  onUpdate,
}: {
  config: ChannelBotMemberConfig;
  onUpdate: (patch: Partial<ChannelBotMemberConfig>) => void;
}) {
  const t = useThemeTokens();

  const handleBlurNumber = useCallback(
    (field: "max_rounds" | "priority", raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) {
        onUpdate({ [field]: null });
        return;
      }
      const parsed = parseInt(trimmed, 10);
      if (!isNaN(parsed)) {
        onUpdate({ [field]: parsed });
      }
    },
    [onUpdate]
  );

  const inputStyle: React.CSSProperties = {
    background: t.surface,
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 8,
    padding: "8px 12px",
    color: t.text,
    fontSize: 13,
    width: "100%",
    outline: "none",
    boxSizing: "border-box",
  };

  return (
    <div
      style={{
        padding: "8px 12px 12px",
        borderTop: `1px solid ${t.surfaceBorder}`,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <FormRow label="Auto-respond" description="Respond to all messages, not just @-mentions">
        <Toggle
          value={!!config.auto_respond}
          onChange={(val) => onUpdate({ auto_respond: val })}
        />
      </FormRow>

      <FormRow label="Response style">
        <SelectInput
          value={config.response_style ?? ""}
          onChange={(val) => onUpdate({ response_style: (val as ChannelBotMemberConfig["response_style"]) || null })}
          options={[
            { label: "Inherit from bot", value: "" },
            { label: "Brief", value: "brief" },
            { label: "Normal", value: "normal" },
            { label: "Detailed", value: "detailed" },
          ]}
        />
      </FormRow>

      <FormRow label="Max rounds" description="Max back-and-forth iterations">
        <input
          type="number"
          defaultValue={config.max_rounds != null ? String(config.max_rounds) : ""}
          placeholder="Inherit"
          style={inputStyle}
          onFocus={(e) => { e.target.style.borderColor = t.accent; }}
          onBlur={(e) => {
            e.target.style.borderColor = t.surfaceBorder;
            handleBlurNumber("max_rounds", e.target.value);
          }}
        />
      </FormRow>

      <FormRow label="Priority" description="Order when multiple auto-respond bots (lower = first)">
        <input
          type="number"
          defaultValue={config.priority != null ? String(config.priority) : ""}
          placeholder="0"
          style={inputStyle}
          onFocus={(e) => { e.target.style.borderColor = t.accent; }}
          onBlur={(e) => {
            e.target.style.borderColor = t.surfaceBorder;
            handleBlurNumber("priority", e.target.value);
          }}
        />
      </FormRow>

      <AdvancedSection>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <FormRow label="Model override">
            <LlmModelDropdown
              value={config.model_override ?? ""}
              onChange={(modelId) => onUpdate({ model_override: modelId || null })}
              placeholder="Inherit from bot"
              allowClear
            />
          </FormRow>

          <FormRow label="System prompt addon" description="Extra instructions appended to this bot's system prompt">
            <textarea
              defaultValue={config.system_prompt_addon ?? ""}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = t.surfaceBorder;
                onUpdate({ system_prompt_addon: e.target.value || null });
              }}
              placeholder="Additional instructions for this member in this channel..."
              rows={3}
              style={{
                ...inputStyle,
                fontFamily: "inherit",
                resize: "vertical",
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = t.accent; }}
            />
          </FormRow>
        </div>
      </AdvancedSection>
    </div>
  );
}
