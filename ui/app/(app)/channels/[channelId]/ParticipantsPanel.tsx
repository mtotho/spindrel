import { useState } from "react";
import { ChevronRight, X, Plus, Bot, Users } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannelBotMembers, useAddBotMember, useRemoveBotMember } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { ChannelBotMember } from "@/src/types/api";

interface ParticipantsPanelProps {
  channelId: string;
  primaryBotId: string;
  primaryBotName?: string;
  onClose?: () => void;
  mobile?: boolean;
}

export function ParticipantsPanel({ channelId, primaryBotId, primaryBotName, onClose, mobile }: ParticipantsPanelProps) {
  const t = useThemeTokens();
  const [showPicker, setShowPicker] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<ChannelBotMember | null>(null);
  const { data: members = [] } = useChannelBotMembers(channelId);
  const addMember = useAddBotMember(channelId);
  const removeMember = useRemoveBotMember(channelId);
  const { data: allBots = [] } = useBots();

  const memberBotIds = new Set(members.map((m) => m.bot_id));
  const availableBots = allBots.filter(
    (b) => b.id !== primaryBotId && !memberBotIds.has(b.id)
  );

  const totalCount = 1 + members.length;

  const panel = (
    <div style={{
      width: mobile ? "100%" : 260,
      borderLeft: mobile ? "none" : `1px solid ${t.surfaceBorder}`,
      backgroundColor: t.surfaceRaised,
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
      ...(mobile ? { flex: 1 } : {}),
    }}>
      {/* Header */}
      <div style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Users size={13} color={t.textDim} />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
            Participants ({totalCount})
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close panel"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 6,
              borderRadius: 4,
              display: "flex", flexDirection: "row",
              alignItems: "center",
            }}
          >
            {mobile ? <X size={14} color={t.textDim} /> : <ChevronRight size={14} color={t.textDim} />}
          </button>
        )}
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
        {/* Primary bot */}
        <div style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
          padding: "7px 12px",
        }}>
          <Bot size={14} color={t.accent} />
          <span style={{ fontSize: 13, color: t.text, flex: 1, fontWeight: 500 }}>
            {primaryBotName || primaryBotId}
          </span>
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            color: t.accent,
            background: `${t.accent}15`,
            borderRadius: 4,
            padding: "1px 6px",
          }}>
            primary
          </span>
        </div>

        {/* Member bots */}
        {members.map((m) => (
          <MemberRow
            key={m.id}
            member={m}
            onRemove={() => setConfirmRemove(m)}
            isRemoving={removeMember.isPending}
          />
        ))}

        {/* Empty hint */}
        {members.length === 0 && availableBots.length > 0 && !showPicker && (
          <div style={{ padding: "8px 12px" }}>
            <span style={{ fontSize: 11, color: t.textDim, lineHeight: "16px" }}>
              Add bots to this channel...
            </span>
          </div>
        )}

        {/* Add bot */}
        {availableBots.length > 0 && (
          <div style={{ padding: "4px 12px" }}>
            {showPicker ? (
              <div style={{
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8,
                background: t.surface,
                overflow: "hidden",
                boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
              }}>
                {availableBots.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => {
                      addMember.mutate(b.id);
                      setShowPicker(false);
                    }}
                    disabled={addMember.isPending}
                    style={{
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      gap: 8,
                      width: "100%",
                      padding: "7px 10px",
                      border: "none",
                      background: "transparent",
                      cursor: addMember.isPending ? "wait" : "pointer",
                      fontSize: 12,
                      color: t.text,
                      textAlign: "left",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = `${t.accent}10`; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <Bot size={12} color={t.textDim} />
                    {b.name}
                  </button>
                ))}
                <button
                  onClick={() => setShowPicker(false)}
                  style={{
                    width: "100%",
                    padding: "5px 10px",
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
            ) : (
              <button
                onClick={() => setShowPicker(true)}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  width: "100%",
                  padding: "6px 0",
                  border: "none",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 12,
                  color: t.textDim,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = t.accent; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = t.textDim; }}
              >
                <Plus size={12} />
                Add bot
              </button>
            )}
          </div>
        )}
      </div>

      {/* Confirm remove dialog */}
      <ConfirmDialog
        open={confirmRemove !== null}
        title="Remove member bot"
        message={`Remove ${confirmRemove?.bot_name || confirmRemove?.bot_id || ""} from this channel?`}
        confirmLabel="Remove"
        variant="danger"
        onConfirm={() => {
          if (confirmRemove) removeMember.mutate(confirmRemove.bot_id);
          setConfirmRemove(null);
        }}
        onCancel={() => setConfirmRemove(null)}
      />
    </div>
  );

  if (mobile) {
    return (
      <div style={{
        position: "absolute",
        inset: 0,
        zIndex: 20,
        display: "flex",
        flexDirection: "column",
        backgroundColor: t.surfaceRaised,
      }}>
        {panel}
      </div>
    );
  }

  return panel;
}

// ---------------------------------------------------------------------------
// Member row with config badges + hover-reveal remove
// ---------------------------------------------------------------------------
function MemberRow({
  member,
  onRemove,
  isRemoving,
}: {
  member: ChannelBotMember;
  onRemove: () => void;
  isRemoving: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const cfg = member.config || {};

  // Build config summary (matches ParticipantsTab badges)
  const hints: string[] = [];
  if (cfg.auto_respond) hints.push("auto-respond");
  if (cfg.response_style) hints.push(cfg.response_style);
  if (cfg.priority && cfg.priority !== 0) hints.push(`pri ${cfg.priority}`);
  if (cfg.max_rounds) hints.push(`${cfg.max_rounds}r`);

  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 8,
        padding: "7px 12px",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Bot size={14} color={t.textDim} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 13, color: t.text, display: "block" }}>
          {member.bot_name || member.bot_id}
        </span>
        {hints.length > 0 && (
          <span style={{ fontSize: 10, color: t.textDim }}>
            {hints.join(", ")}
          </span>
        )}
      </div>
      <button
        onClick={onRemove}
        disabled={isRemoving}
        title="Remove from channel"
        style={{
          border: "none",
          background: "transparent",
          cursor: "pointer",
          padding: 2,
          display: "flex", flexDirection: "row",
          alignItems: "center",
          opacity: hovered ? 0.8 : 0,
          transition: "opacity 0.15s",
          flexShrink: 0,
        }}
      >
        <X size={12} color={t.textDim} />
      </button>
    </div>
  );
}
