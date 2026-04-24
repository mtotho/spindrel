import { Spinner } from "@/src/components/shared/Spinner";
/**
 * ParticipantsTab — self-managing tab for multi-bot channel member configuration.
 * Handles its own mutations; no parent Save button needed.
 */
import { useState, useCallback } from "react";
import { Bot, ChevronDown, ChevronRight, Plus, X, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
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
import { ActionButton, AdvancedSection, QuietPill, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import type { ChannelBotMember, ChannelBotMemberConfig } from "@/src/types/api";

const INPUT_CLASS =
  "w-full bg-input border border-input-border rounded-md px-3 py-2 text-[13px] text-text " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 transition-colors";

interface Props {
  channelId: string;
  primaryBotId: string;
}

export function ParticipantsTab({ channelId, primaryBotId }: Props) {
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
      <div className="flex justify-center p-8">
        <Spinner />
      </div>
    );
  }

  return (
    <>
      <Section
        title="Participants"
        description="Bots that can participate in this channel. The primary agent owns default routing; members can be routed active turns by @mention or auto-respond."
      >
        <SettingsControlRow
          leading={<Bot size={14} />}
          title={primaryBot?.name || primaryBotId}
          description="Primary agent - owns this channel"
          meta={<StatusBadge label="active" variant="success" />}
          action={
            <Link
              to={`/admin/bots/${primaryBotId}`}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-accent hover:bg-surface-overlay/60 transition-colors"
            >
              <ExternalLink size={11} />
              <span>Open config</span>
            </Link>
          }
        />
      </Section>

      {/* Member bots */}
      <Section
        title="Member Bots"
        description="Additional agents that can receive active turns by @mention or auto-respond."
        action={
          availableBots.length > 0 && !showPicker ? (
            <ActionButton
              label="Add Bot"
              onPress={() => setShowPicker(true)}
              icon={<Plus size={12} />}
              size="small"
            />
          ) : undefined
        }
      >
        <div className="max-w-[76ch] text-[12px] leading-relaxed text-text-dim">
          Member bots are still channel participants for passive context. Even when
          they only answer on @-mention, channel activity can be included in their
          memory compaction and dreaming/learning jobs according to passive-memory
          and bot learning settings.
        </div>

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

        {members.length === 0 && !showPicker && (
          <EmptyState message="Add bots to this channel. Members respond when @-mentioned, but still share passive channel context for memory and learning." />
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
  return (
    <div className="flex flex-col gap-1">
      {bots.map((b) => (
        <SettingsControlRow
          key={b.id}
          onClick={() => onSelect(b.id)}
          disabled={isPending}
          leading={<Bot size={14} />}
          title={b.name}
          compact
        />
      ))}
      <div>
        <ActionButton label="Cancel" onPress={onCancel} variant="ghost" size="small" />
      </div>
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
  const [expanded, setExpanded] = useState(false);
  const cfg = member.config || {};

  const badges: string[] = [];
  if (cfg.auto_respond) badges.push("auto-respond");
  if (cfg.response_style) badges.push(cfg.response_style);
  if (cfg.priority && cfg.priority !== 0) badges.push(`priority ${cfg.priority}`);
  if (cfg.max_rounds) badges.push(`${cfg.max_rounds} rounds`);

  return (
    <div className="overflow-hidden rounded-md bg-surface-raised/40">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="grid min-h-[38px] w-full grid-cols-[16px_20px_minmax(0,1fr)_auto_auto_auto] items-center gap-2 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 max-sm:grid-cols-[16px_20px_minmax(0,1fr)_auto_auto]"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-text-dim shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-text-dim shrink-0" />
        )}
        <div className="relative shrink-0">
          <Bot size={14} className="text-text-dim" />
          {/* running-status dot: accent = auto-respond, dim = @-mention only. */}
          <span
            aria-hidden
            className={`absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full ring-2 ring-surface-raised ${cfg.auto_respond ? "bg-accent" : "bg-text-dim/60"}`}
          />
        </div>
        <span className="min-w-0 truncate text-[13px] font-medium text-text">
          {member.bot_name || member.bot_id}
        </span>
        {!expanded && badges.length > 0 && (
          <div className="hidden items-center justify-end gap-1 sm:flex">
            {badges.map((b) => (
              <QuietPill key={b} label={b} title={b} />
            ))}
          </div>
        )}
        <Link
          to={`/admin/bots/${member.bot_id}`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex shrink-0 items-center p-1 text-accent hover:text-accent-hover transition-colors"
          title="Bot settings"
        >
          <ExternalLink size={12} />
        </Link>
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            if (!isRemoving) onRemove();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              if (!isRemoving) onRemove();
            }
          }}
          title="Remove from channel"
          aria-disabled={isRemoving}
          className="inline-flex shrink-0 cursor-pointer items-center p-1 text-text-dim hover:text-danger aria-disabled:pointer-events-none aria-disabled:opacity-50 transition-colors"
        >
          <X size={14} />
        </span>
      </button>

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

  return (
    <div className="flex flex-col gap-3 border-t border-surface-border px-3 pt-2 pb-3">
      <FormRow label="Auto-respond" description="Active routing only. Off means @mention-only; passive context can still feed memory/learning when channel settings allow it.">
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
          className={INPUT_CLASS}
          onBlur={(e) => handleBlurNumber("max_rounds", e.target.value)}
        />
      </FormRow>

      <FormRow label="Priority" description="Order when multiple auto-respond bots (lower = first)">
        <input
          type="number"
          defaultValue={config.priority != null ? String(config.priority) : ""}
          placeholder="0"
          className={INPUT_CLASS}
          onBlur={(e) => handleBlurNumber("priority", e.target.value)}
        />
      </FormRow>

      <AdvancedSection>
        <div className="flex flex-col gap-3">
          <FormRow label="Model override">
            <LlmModelDropdown
              value={config.model_override ?? ""}
              onChange={(modelId) => onUpdate({ model_override: modelId || null })}
              placeholder="Inherit from bot"
              allowClear
              className="md:max-w-[560px]"
            />
          </FormRow>

          <FormRow label="System prompt addon" description="Extra instructions appended to this bot's system prompt">
            <textarea
              defaultValue={config.system_prompt_addon ?? ""}
              onBlur={(e) => onUpdate({ system_prompt_addon: e.target.value || null })}
              placeholder="Additional instructions for this member in this channel..."
              rows={3}
              className={`${INPUT_CLASS} font-[inherit] resize-y`}
            />
          </FormRow>
        </div>
      </AdvancedSection>
    </div>
  );
}
