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
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
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
        description="Bots that can respond in this channel. The primary agent owns the channel; members respond on @-mention."
      >
        <div className="flex items-center gap-3 rounded-md border border-surface-border bg-surface-raised px-3.5 py-3">
          <div className="relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-overlay">
            <Bot size={18} className="text-text" />
            <span
              className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-success ring-2 ring-surface-raised"
              aria-hidden
              title="Active"
            />
          </div>
          <div className="flex-1 min-w-0">
            <div className="truncate text-[14px] font-semibold text-text tracking-[-0.01em]">
              {primaryBot?.name || primaryBotId}
            </div>
            <div className="mt-0.5 text-[11px] text-text-dim">
              Primary agent · owns this channel
            </div>
          </div>
          <Link
            to={`/admin/bots/${primaryBotId}`}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-accent hover:bg-surface-overlay/60 transition-colors"
          >
            <ExternalLink size={11} />
            <span>Open config</span>
          </Link>
        </div>
      </Section>

      {/* Member bots */}
      <Section
        title="Member Bots"
        description="Additional agents that respond when @-mentioned."
        action={
          availableBots.length > 0 && !showPicker ? (
            <button
              type="button"
              onClick={() => setShowPicker(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-transparent px-2.5 py-1 text-[12px] font-medium text-accent hover:bg-surface-overlay/60 transition-colors"
            >
              <Plus size={12} />
              Add Bot
            </button>
          ) : undefined
        }
      >
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
    <div className="overflow-hidden rounded-md border border-surface-border bg-surface-raised">
      {bots.map((b) => (
        <button
          key={b.id}
          type="button"
          onClick={() => onSelect(b.id)}
          disabled={isPending}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-text hover:bg-accent/[0.08] disabled:cursor-wait transition-colors"
        >
          <Bot size={14} className="text-text-dim" />
          {b.name}
        </button>
      ))}
      <button
        type="button"
        onClick={onCancel}
        className="w-full px-3 py-1.5 text-center text-[11px] text-text-dim hover:bg-surface-overlay/60 transition-colors"
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
  const [expanded, setExpanded] = useState(false);
  const cfg = member.config || {};

  const badges: string[] = [];
  if (cfg.auto_respond) badges.push("auto-respond");
  if (cfg.response_style) badges.push(cfg.response_style);
  if (cfg.priority && cfg.priority !== 0) badges.push(`priority ${cfg.priority}`);
  if (cfg.max_rounds) badges.push(`${cfg.max_rounds} rounds`);

  return (
    <div className="overflow-hidden rounded-md border border-surface-border bg-surface-raised">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-overlay/60 transition-colors"
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
        <span className="flex-1 min-w-0 truncate text-[13px] font-medium text-text">
          {member.bot_name || member.bot_id}
        </span>
        {!expanded && badges.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            {badges.map((b) => (
              <span
                key={b}
                className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim"
              >
                {b}
              </span>
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
