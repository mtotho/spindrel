/**
 * Rich detail modal for kanban cards — view/edit title, description,
 * priority, status (column), and metadata. Opens on card click.
 */
import { useState, useEffect } from "react";
import { View, Text, Pressable, TextInput } from "react-native";
import { useRouter } from "expo-router";
import {
  X,
  Tag,
  User,
  Calendar,
  ArrowRight,
  Pencil,
  Check,
  Clock,
  Link2,
  ExternalLink,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import { useMCCardHistory } from "@/src/api/hooks/useMissionControl";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

const PRIORITY_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  critical: { bg: "rgba(239,68,68,0.10)", fg: "#ef4444", border: "rgba(239,68,68,0.25)" },
  high: { bg: "rgba(249,115,22,0.10)", fg: "#f97316", border: "rgba(249,115,22,0.25)" },
  medium: { bg: "rgba(99,102,241,0.08)", fg: "#6366f1", border: "rgba(99,102,241,0.2)" },
  low: { bg: "rgba(107,114,128,0.06)", fg: "#9ca3af", border: "rgba(107,114,128,0.15)" },
};

const PRIORITY_CYCLE = ["low", "medium", "high", "critical"];

interface Props {
  card: MCKanbanCard;
  currentColumn: string;
  columns: MCKanbanColumn[];
  onMove: (cardId: string, channelId: string, fromColumn: string, toColumn: string) => void;
  onUpdate?: (cardId: string, channelId: string, fields: Record<string, string>) => void;
  onClose: () => void;
  moveDisabled?: boolean;
}

export function KanbanCardModal({
  card,
  currentColumn,
  columns,
  onMove,
  onUpdate,
  onClose,
  moveDisabled,
}: Props) {
  const t = useThemeTokens();
  const router = useRouter();
  const priority = card.meta.priority || "medium";
  const pc = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;
  const cc = channelColor(card.channel_id);

  // Inline editing state
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(card.title);
  const [editingDesc, setEditingDesc] = useState(false);
  const [descDraft, setDescDraft] = useState(card.description || "");

  // Escape key to close
  useEffect(() => {
    if (typeof document === "undefined") return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (editingTitle) {
          setEditingTitle(false);
          setTitleDraft(card.title);
        } else if (editingDesc) {
          setEditingDesc(false);
          setDescDraft(card.description || "");
        } else {
          onClose();
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, editingTitle, editingDesc, card.title, card.description]);

  if (typeof document === "undefined") return null;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");

  const otherColumns = columns.filter((col) => col.name !== currentColumn);

  const handleSaveTitle = () => {
    if (titleDraft.trim() && titleDraft !== card.title && onUpdate) {
      onUpdate(card.meta.id, card.channel_id, { title: titleDraft.trim() });
    }
    setEditingTitle(false);
  };

  const handleSaveDesc = () => {
    if (descDraft !== (card.description || "") && onUpdate) {
      onUpdate(card.meta.id, card.channel_id, { description: descDraft });
    }
    setEditingDesc(false);
  };

  const handleCyclePriority = () => {
    if (!onUpdate) return;
    const idx = PRIORITY_CYCLE.indexOf(priority);
    const next = PRIORITY_CYCLE[(idx + 1) % PRIORITY_CYCLE.length];
    onUpdate(card.meta.id, card.channel_id, { priority: next });
  };

  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      {/* Modal */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 540,
          maxWidth: "92vw",
          maxHeight: "85vh",
          overflowY: "auto",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 14,
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            padding: 20,
            paddingBottom: 0,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            {editingTitle ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="text"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={handleSaveTitle}
                  onKeyDown={(e) => e.key === "Enter" && handleSaveTitle()}
                  autoFocus
                  style={{
                    fontSize: 17,
                    fontWeight: 700,
                    color: t.text,
                    flex: 1,
                    background: "transparent",
                    border: "none",
                    borderBottom: `2px solid ${t.accent}`,
                    padding: "2px 0",
                    outline: "none",
                    fontFamily: "inherit",
                  }}
                />
                <button
                  onClick={handleSaveTitle}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: 2,
                  }}
                >
                  <Check size={16} color={t.accent} />
                </button>
              </div>
            ) : (
              <div
                onClick={() => onUpdate && setEditingTitle(true)}
                style={{
                  fontSize: 17,
                  fontWeight: 700,
                  color: t.text,
                  lineHeight: 1.3,
                  cursor: onUpdate ? "pointer" : "default",
                }}
              >
                {card.title}
              </div>
            )}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginTop: 6,
              }}
            >
              <div
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 3.5,
                  backgroundColor: cc,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 12, color: t.textDim }}>
                {card.channel_name}
              </span>
              {card.meta.id && (
                <span
                  style={{
                    fontSize: 10,
                    color: t.textDim,
                    fontFamily: "monospace",
                    opacity: 0.7,
                  }}
                >
                  {card.meta.id}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              marginLeft: 8,
            }}
          >
            <X size={18} color={t.textDim} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Status + Priority + Meta in codeBg panel */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 16,
              padding: 14,
              borderRadius: 8,
              background: t.codeBg,
              border: `1px solid ${t.surfaceBorder}`,
            }}
          >
            {/* Current column badge */}
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: t.textMuted,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Status
              </span>
              <span
                style={{
                  display: "inline-flex",
                  padding: "3px 8px",
                  borderRadius: 5,
                  fontSize: 12,
                  fontWeight: 600,
                  background: `${t.accent}18`,
                  border: `1px solid ${t.accent}40`,
                  color: t.accent,
                }}
              >
                {currentColumn}
              </span>
            </div>

            {/* Priority — clickable to cycle */}
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: t.textMuted,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Priority
              </span>
              <span
                onClick={handleCyclePriority}
                style={{
                  display: "inline-flex",
                  padding: "3px 8px",
                  borderRadius: 5,
                  fontSize: 12,
                  fontWeight: 600,
                  background: pc.bg,
                  border: `1px solid ${pc.border}`,
                  color: pc.fg,
                  textTransform: "capitalize",
                  cursor: onUpdate ? "pointer" : "default",
                }}
              >
                {priority}
              </span>
            </div>

            {/* Assigned */}
            {card.meta.assigned && (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: t.textMuted,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}
                >
                  Assigned
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: t.text,
                  }}
                >
                  <User size={11} color={t.textMuted} />
                  {card.meta.assigned}
                </span>
              </div>
            )}

            {/* Date fields */}
            {card.meta.created && (
              <MetaField icon={Calendar} label="Created" value={card.meta.created} t={t} />
            )}
            {card.meta.started && (
              <MetaField icon={Calendar} label="Started" value={card.meta.started} t={t} />
            )}
            {card.meta.completed && (
              <MetaField icon={Calendar} label="Completed" value={card.meta.completed} t={t} />
            )}
            {card.meta.due && (
              <MetaField icon={Calendar} label="Due" value={card.meta.due} t={t} />
            )}
            {card.meta.tags && (
              <MetaField icon={Tag} label="Tags" value={card.meta.tags} t={t} />
            )}
          </div>

          {/* Description — inline edit */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: t.textMuted,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Description
              </span>
              {!editingDesc && onUpdate && (
                <button
                  onClick={() => setEditingDesc(true)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 3,
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: 0,
                    fontSize: 10,
                    color: t.textDim,
                  }}
                >
                  <Pencil size={10} />
                  Edit
                </button>
              )}
            </div>
            {editingDesc ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <textarea
                  value={descDraft}
                  onChange={(e) => setDescDraft(e.target.value)}
                  autoFocus
                  rows={4}
                  style={{
                    fontSize: 13,
                    color: t.text,
                    lineHeight: 1.5,
                    backgroundColor: t.codeBg,
                    borderRadius: 8,
                    padding: 12,
                    border: `1px solid ${t.accent}`,
                    minHeight: 80,
                    outline: "none",
                    fontFamily: "inherit",
                    resize: "vertical",
                  }}
                />
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={handleSaveDesc}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      background: `${t.accent}18`,
                      border: "none",
                      color: t.accent,
                      cursor: "pointer",
                    }}
                  >
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setEditingDesc(false);
                      setDescDraft(card.description || "");
                    }}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 6,
                      fontSize: 12,
                      background: "none",
                      border: "none",
                      color: t.textDim,
                      cursor: "pointer",
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : card.description ? (
              <div
                style={{
                  backgroundColor: t.codeBg,
                  borderRadius: 8,
                  padding: 12,
                  border: `1px solid ${t.surfaceBorder}`,
                }}
              >
                <span style={{ fontSize: 13, color: t.text, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                  {card.description}
                </span>
              </div>
            ) : (
              <span style={{ fontSize: 12, color: t.textDim, fontStyle: "italic" }}>
                No description
              </span>
            )}
          </div>

          {/* Linked plan */}
          {card.plan_id && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <Link2 size={10} color={t.textDim} />
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: t.textMuted,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}
                >
                  Linked Plan
                </span>
              </div>
              <button
                onClick={() => {
                  onClose();
                  router.push(
                    `/mission-control/plans/${card.channel_id}/${card.plan_id}` as any
                  );
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 10px",
                  borderRadius: 6,
                  background: t.accentSubtle,
                  border: `1px solid ${t.accentBorder}`,
                  color: t.accent,
                  fontSize: 12,
                  fontWeight: 600,
                  fontFamily: "monospace",
                  cursor: "pointer",
                  alignSelf: "flex-start",
                }}
              >
                <ExternalLink size={11} />
                {card.plan_id.slice(0, 12)}
                {card.plan_step_position ? ` — Step ${card.plan_step_position}` : ""}
              </button>
            </div>
          )}

          {/* History */}
          <CardHistorySection cardId={card.meta.id} channelId={card.channel_id} t={t} />

          {/* Move actions */}
          {otherColumns.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: t.textMuted,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Move to
              </span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {otherColumns.map((col) => (
                  <button
                    key={col.name}
                    onClick={() => {
                      onMove(card.meta.id, card.channel_id, currentColumn, col.name);
                      onClose();
                    }}
                    disabled={moveDisabled}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 12px",
                      borderRadius: 6,
                      border: `1px solid ${t.surfaceBorder}`,
                      background: "transparent",
                      color: t.text,
                      fontSize: 12,
                      fontWeight: 500,
                      cursor: moveDisabled ? "default" : "pointer",
                      opacity: moveDisabled ? 0.5 : 1,
                      transition: "border-color 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor = t.textDim;
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor = t.surfaceBorder;
                    }}
                  >
                    <ArrowRight size={12} color={t.textMuted} />
                    {col.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>,
    document.body
  );
}

function MetaField({
  icon: Icon,
  label,
  value,
  t,
}: {
  icon: React.ComponentType<{ size: number; color: string }>;
  label: string;
  value: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 3,
          fontSize: 10,
          fontWeight: 600,
          color: t.textMuted,
          textTransform: "uppercase",
          letterSpacing: 0.5,
        }}
      >
        <Icon size={9} color={t.textDim} />
        {label}
      </span>
      <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace" }}>
        {value}
      </span>
    </div>
  );
}

function CardHistorySection({
  cardId,
  channelId,
  t,
}: {
  cardId: string;
  channelId: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const { data } = useMCCardHistory(cardId, channelId);
  const events = data?.events;

  if (!events || events.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <Clock size={10} color={t.textDim} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: t.textMuted,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          History
        </span>
      </div>
      <div
        style={{
          backgroundColor: t.codeBg,
          borderRadius: 8,
          padding: 10,
          border: `1px solid ${t.surfaceBorder}`,
          display: "flex",
          flexDirection: "column",
          gap: 5,
        }}
      >
        {events.slice(0, 5).map((ev, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <span
              style={{
                fontSize: 10,
                color: t.textDim,
                fontFamily: "monospace",
                minWidth: 36,
                flexShrink: 0,
              }}
            >
              {ev.time}
            </span>
            <span style={{ fontSize: 11, color: t.text, lineHeight: 1.4, flex: 1 }}>
              {ev.event}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
