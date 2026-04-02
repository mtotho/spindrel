/**
 * Interactive column header for the kanban board.
 * Displays name + card count, supports inline rename and "..." menu.
 */
import { useState, useRef, useEffect } from "react";
import { View, Text, Pressable, TextInput } from "react-native";
import { MoreHorizontal, Pencil, Trash2, Check, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { columnColor } from "./kanbanTypes";

interface Props {
  columnName: string;
  columnId?: string;
  cardCount: number;
  channelId?: string;
  onRename?: (columnId: string, newName: string) => void;
  onDelete?: (columnId: string) => void;
}

export function KanbanColumnHeader({
  columnName,
  columnId,
  cardCount,
  onRename,
  onDelete,
}: Props) {
  const t = useThemeTokens();
  const cc = columnColor(columnName);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(columnName);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen || typeof document === "undefined") return;
    const handle = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [menuOpen]);

  const handleSave = () => {
    if (draft.trim() && draft !== columnName && columnId && onRename) {
      onRename(columnId, draft.trim());
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flex: 1 }}>
        <TextInput
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={handleSave}
          autoFocus
          style={{
            fontSize: 12,
            fontWeight: "600",
            color: t.text,
            flex: 1,
            borderBottomWidth: 2,
            borderBottomColor: t.accent,
            paddingVertical: 1,
            backgroundColor: "transparent",
            outlineStyle: "none",
          } as any}
        />
        <Pressable onPress={handleSave} hitSlop={4}>
          <Check size={14} color={t.accent} />
        </Pressable>
        <Pressable
          onPress={() => {
            setEditing(false);
            setDraft(columnName);
          }}
          hitSlop={4}
        >
          <X size={14} color={t.textDim} />
        </Pressable>
      </View>
    );
  }

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flex: 1 }}>
      <div
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          backgroundColor: cc,
          flexShrink: 0,
        }}
      />
      <Pressable
        onPress={() => {
          if (columnId && onRename) {
            setDraft(columnName);
            setEditing(true);
          }
        }}
        style={{ flex: 1 }}
      >
        <Text style={{ fontSize: 12, fontWeight: "600", color: t.text }}>
          {columnName}
        </Text>
      </Pressable>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          backgroundColor: "rgba(107,114,128,0.1)",
          borderRadius: 10,
          padding: "1px 7px",
        }}
      >
        {cardCount}
      </span>
      {columnId && (onRename || onDelete) && (
        <div ref={menuRef} style={{ position: "relative" }}>
          <Pressable onPress={() => setMenuOpen((v) => !v)} hitSlop={4}>
            <MoreHorizontal size={14} color={t.textDim} />
          </Pressable>
          {menuOpen && (
            <div
              style={{
                position: "absolute",
                top: 20,
                right: 0,
                zIndex: 100,
                background: t.surfaceRaised,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8,
                boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
                minWidth: 120,
                overflow: "hidden",
              }}
            >
              {onRename && (
                <Pressable
                  onPress={() => {
                    setMenuOpen(false);
                    setDraft(columnName);
                    setEditing(true);
                  }}
                  style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 10 }}
                >
                  <Pencil size={12} color={t.textMuted} />
                  <Text style={{ fontSize: 12, color: t.text }}>Rename</Text>
                </Pressable>
              )}
              {onDelete && cardCount === 0 && (
                <Pressable
                  onPress={() => {
                    setMenuOpen(false);
                    onDelete(columnId);
                  }}
                  style={{ flexDirection: "row", alignItems: "center", gap: 8, padding: 10 }}
                >
                  <Trash2 size={12} color="#ef4444" />
                  <Text style={{ fontSize: 12, color: "#ef4444" }}>Delete</Text>
                </Pressable>
              )}
            </div>
          )}
        </div>
      )}
    </View>
  );
}
