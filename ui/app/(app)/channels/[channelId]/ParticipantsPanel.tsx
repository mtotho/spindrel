import { useState } from "react";
import { ChevronLeft, ChevronRight, X, Plus, Bot } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannelBotMembers, useAddBotMember, useRemoveBotMember } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";

interface ParticipantsPanelProps {
  channelId: string;
  primaryBotId: string;
  primaryBotName?: string;
}

export function ParticipantsPanel({ channelId, primaryBotId, primaryBotName }: ParticipantsPanelProps) {
  const t = useThemeTokens();
  const [collapsed, setCollapsed] = useState(true);
  const [showPicker, setShowPicker] = useState(false);
  const { data: members = [] } = useChannelBotMembers(channelId);
  const addMember = useAddBotMember(channelId);
  const removeMember = useRemoveBotMember(channelId);
  const { data: allBots = [] } = useBots();

  const memberBotIds = new Set(members.map((m) => m.bot_id));
  const availableBots = allBots.filter(
    (b) => b.id !== primaryBotId && !memberBotIds.has(b.id)
  );

  const totalCount = 1 + members.length;

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        title={`${totalCount} participant${totalCount > 1 ? "s" : ""}`}
        style={{
          width: 28,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          border: "none",
          borderLeft: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
          cursor: "pointer",
          padding: "8px 0",
        }}
      >
        <ChevronLeft size={14} color={t.textDim} />
        <Bot size={14} color={t.textDim} />
        {totalCount > 1 && (
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            color: t.accent,
            background: `${t.accent}20`,
            borderRadius: 8,
            padding: "1px 5px",
            minWidth: 16,
            textAlign: "center",
          }}>
            {totalCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <div style={{
      width: 240,
      borderLeft: `1px solid ${t.surfaceBorder}`,
      background: t.surfaceRaised,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
          Participants ({totalCount})
        </span>
        <button
          onClick={() => setCollapsed(true)}
          style={{
            border: "none",
            background: "transparent",
            cursor: "pointer",
            padding: 2,
            display: "flex",
            alignItems: "center",
          }}
        >
          <ChevronRight size={14} color={t.textDim} />
        </button>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {/* Primary bot */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
        }}>
          <Bot size={14} color={t.accent} />
          <span style={{ fontSize: 13, color: t.text, flex: 1 }}>
            {primaryBotName || primaryBotId}
          </span>
          <span style={{
            fontSize: 10,
            color: t.textDim,
            background: `${t.accent}15`,
            borderRadius: 4,
            padding: "1px 6px",
          }}>
            primary
          </span>
        </div>

        {/* Member bots */}
        {members.map((m) => (
          <div key={m.id} style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 12px",
          }}>
            <Bot size={14} color={t.textDim} />
            <span style={{ fontSize: 13, color: t.text, flex: 1 }}>
              {m.bot_name || m.bot_id}
            </span>
            <button
              onClick={() => removeMember.mutate(m.bot_id)}
              disabled={removeMember.isPending}
              title="Remove from channel"
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                padding: 2,
                display: "flex",
                alignItems: "center",
                opacity: removeMember.isPending ? 0.5 : 0.6,
              }}
            >
              <X size={12} color={t.textDim} />
            </button>
          </div>
        ))}

        {/* Empty state hint */}
        {members.length === 0 && availableBots.length > 0 && !showPicker && (
          <div style={{ padding: "8px 12px" }}>
            <span style={{ fontSize: 11, color: t.textDim, lineHeight: "16px" }}>
              Add bots to this channel. Members respond when @-mentioned.
            </span>
          </div>
        )}

        {/* Add button */}
        {availableBots.length > 0 && (
          <div style={{ padding: "4px 12px" }}>
            {showPicker ? (
              <div style={{
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                background: t.surface,
                overflow: "hidden",
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
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      width: "100%",
                      padding: "6px 10px",
                      border: "none",
                      background: "transparent",
                      cursor: "pointer",
                      fontSize: 12,
                      color: t.text,
                      textAlign: "left",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = `${t.accent}10`;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <Bot size={12} color={t.textDim} />
                    {b.name}
                  </button>
                ))}
                <button
                  onClick={() => setShowPicker(false)}
                  style={{
                    width: "100%",
                    padding: "4px 10px",
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
                  display: "flex",
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
              >
                <Plus size={12} color={t.textDim} />
                Add bot
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
