/**
 * Rich detail modal for kanban cards — view/edit title, description,
 * priority, status (column), and metadata. Opens on card click.
 */
import { useState, useEffect } from "react";
import { View, Text, Pressable, TextInput } from "react-native";
import { X, Tag, User, Calendar, ArrowRight, Pencil, Check, Clock, Link2 } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import { useMCCardHistory } from "@/src/api/hooks/useMissionControl";
import type { MCKanbanCard, MCKanbanColumn } from "@/src/api/hooks/useMissionControl";

const PRIORITY_COLORS: Record<string, { bg: string; fg: string }> = {
  critical: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  high: { bg: "rgba(249,115,22,0.15)", fg: "#f97316" },
  medium: { bg: "rgba(99,102,241,0.12)", fg: "#6366f1" },
  low: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af" },
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
          width: 520,
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
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "flex-start",
            padding: 20,
            paddingBottom: 0,
          }}
        >
          <View style={{ flex: 1, gap: 6 }}>
            {editingTitle ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <TextInput
                  value={titleDraft}
                  onChangeText={setTitleDraft}
                  onBlur={handleSaveTitle}
                  onSubmitEditing={handleSaveTitle}
                  autoFocus
                  style={{
                    fontSize: 17,
                    fontWeight: "700",
                    color: t.text,
                    flex: 1,
                    borderBottomWidth: 2,
                    borderBottomColor: t.accent,
                    paddingVertical: 2,
                    backgroundColor: "transparent",
                    outlineStyle: "none",
                  } as any}
                />
                <Pressable onPress={handleSaveTitle}>
                  <Check size={16} color={t.accent} />
                </Pressable>
              </View>
            ) : (
              <Pressable onPress={() => onUpdate && setEditingTitle(true)}>
                <Text
                  style={{
                    fontSize: 17,
                    fontWeight: "700",
                    color: t.text,
                    lineHeight: 22,
                  }}
                >
                  {card.title}
                </Text>
              </Pressable>
            )}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <View
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 3.5,
                  backgroundColor: cc,
                }}
              />
              <Text style={{ fontSize: 12, color: t.textDim }}>
                {card.channel_name}
              </Text>
              {card.meta.id && (
                <Text
                  style={{
                    fontSize: 11,
                    color: t.textDim,
                    fontFamily: "monospace",
                    opacity: 0.7,
                  }}
                >
                  {card.meta.id}
                </Text>
              )}
            </View>
          </View>
          <Pressable
            onPress={onClose}
            hitSlop={8}
            style={{ padding: 4, marginLeft: 8 }}
          >
            <X size={18} color={t.textDim} />
          </Pressable>
        </View>

        {/* Body */}
        <View style={{ padding: 20, gap: 16 }}>
          {/* Status + Priority row */}
          <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
            {/* Current column badge */}
            <View style={{ gap: 4 }}>
              <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Status
              </Text>
              <View
                style={{
                  paddingHorizontal: 10,
                  paddingVertical: 4,
                  borderRadius: 6,
                  backgroundColor: t.accent + "18",
                  borderWidth: 1,
                  borderColor: t.accent + "40",
                }}
              >
                <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>
                  {currentColumn}
                </Text>
              </View>
            </View>

            {/* Priority badge — clickable to cycle */}
            <View style={{ gap: 4 }}>
              <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Priority
              </Text>
              <Pressable onPress={handleCyclePriority} disabled={!onUpdate}>
                <View
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 4,
                    borderRadius: 6,
                    backgroundColor: pc.bg,
                    borderWidth: 1,
                    borderColor: pc.fg + "40",
                    cursor: onUpdate ? "pointer" : "default",
                  } as any}
                >
                  <Text style={{ fontSize: 12, fontWeight: "600", color: pc.fg, textTransform: "capitalize" }}>
                    {priority}
                  </Text>
                </View>
              </Pressable>
            </View>

            {/* Assigned */}
            {card.meta.assigned && (
              <View style={{ gap: 4 }}>
                <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Assigned
                </Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 }}>
                  <User size={12} color={t.textMuted} />
                  <Text style={{ fontSize: 12, color: t.text }}>{card.meta.assigned}</Text>
                </View>
              </View>
            )}
          </View>

          {/* Metadata grid */}
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 12,
            }}
          >
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
          </View>

          {/* Description — inline edit */}
          <View style={{ gap: 6 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Description
              </Text>
              {!editingDesc && onUpdate && (
                <Pressable
                  onPress={() => setEditingDesc(true)}
                  className="flex-row items-center gap-1"
                >
                  <Pencil size={10} color={t.textDim} />
                  <Text style={{ fontSize: 10, color: t.textDim }}>Edit</Text>
                </Pressable>
              )}
            </View>
            {editingDesc ? (
              <View style={{ gap: 8 }}>
                <TextInput
                  value={descDraft}
                  onChangeText={setDescDraft}
                  multiline
                  autoFocus
                  style={{
                    fontSize: 13,
                    color: t.text,
                    lineHeight: 20,
                    backgroundColor: t.surfaceOverlay,
                    borderRadius: 8,
                    padding: 12,
                    borderWidth: 1,
                    borderColor: t.accent,
                    minHeight: 80,
                    outlineStyle: "none",
                  } as any}
                />
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Pressable
                    onPress={handleSaveDesc}
                    style={{
                      paddingHorizontal: 12,
                      paddingVertical: 6,
                      borderRadius: 6,
                      backgroundColor: t.accent + "18",
                    }}
                  >
                    <Text style={{ fontSize: 12, fontWeight: "600", color: t.accent }}>Save</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => {
                      setEditingDesc(false);
                      setDescDraft(card.description || "");
                    }}
                    style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6 }}
                  >
                    <Text style={{ fontSize: 12, color: t.textDim }}>Cancel</Text>
                  </Pressable>
                </View>
              </View>
            ) : card.description ? (
              <View
                style={{
                  backgroundColor: t.surfaceOverlay,
                  borderRadius: 8,
                  padding: 12,
                  borderWidth: 1,
                  borderColor: t.surfaceBorder,
                }}
              >
                <Text style={{ fontSize: 13, color: t.text, lineHeight: 20 }}>
                  {card.description}
                </Text>
              </View>
            ) : (
              <Text style={{ fontSize: 12, color: t.textDim, fontStyle: "italic" }}>
                No description
              </Text>
            )}
          </View>

          {/* Plan link */}
          {card.plan_id && (
            <View style={{ gap: 4 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Link2 size={10} color={t.textDim} />
                <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Linked Plan
                </Text>
              </View>
              <Text style={{ fontSize: 12, color: t.accent, fontFamily: "monospace" }}>
                {card.plan_id}{card.plan_step_position ? ` (step ${card.plan_step_position})` : ""}
              </Text>
            </View>
          )}

          {/* History */}
          <CardHistorySection cardId={card.meta.id} channelId={card.channel_id} t={t} />

          {/* Move actions */}
          {otherColumns.length > 0 && (
            <View style={{ gap: 6 }}>
              <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Move to
              </Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                {otherColumns.map((col) => (
                  <Pressable
                    key={col.name}
                    onPress={() => {
                      onMove(card.meta.id, card.channel_id, currentColumn, col.name);
                      onClose();
                    }}
                    disabled={moveDisabled}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 6,
                      paddingHorizontal: 12,
                      paddingVertical: 7,
                      borderRadius: 8,
                      borderWidth: 1,
                      borderColor: t.surfaceBorder,
                      opacity: moveDisabled ? 0.5 : 1,
                    }}
                  >
                    <ArrowRight size={12} color={t.textMuted} />
                    <Text style={{ fontSize: 12, fontWeight: "500", color: t.text }}>
                      {col.name}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          )}
        </View>
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
    <View style={{ gap: 2 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <Icon size={10} color={t.textDim} />
        <Text style={{ fontSize: 10, color: t.textDim, fontWeight: "500" }}>{label}</Text>
      </View>
      <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace" }}>{value}</Text>
    </View>
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
    <View style={{ gap: 6 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <Clock size={10} color={t.textDim} />
        <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
          History
        </Text>
      </View>
      <View
        style={{
          backgroundColor: t.surfaceOverlay,
          borderRadius: 8,
          padding: 10,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          gap: 6,
        }}
      >
        {events.slice(0, 5).map((ev, i) => (
          <View key={i} style={{ flexDirection: "row", gap: 8, alignItems: "flex-start" }}>
            <Text style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace", minWidth: 36, flexShrink: 0 }}>
              {ev.time}
            </Text>
            <Text style={{ fontSize: 11, color: t.text, lineHeight: 16, flex: 1 }}>
              {ev.event}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}
