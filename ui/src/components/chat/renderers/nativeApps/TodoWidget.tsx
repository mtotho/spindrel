import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ChevronDown, ChevronUp, GripVertical, Plus, Trash2, X } from "lucide-react";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, type NativeTodoItem, useNativeEnvelopeState } from "./shared";

function IconButton({
  label,
  onClick,
  t,
  disabled = false,
  children,
}: {
  label: string;
  onClick: () => void;
  t: ThemeTokens;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      title={label}
      style={{
        width: 24,
        height: 24,
        border: "none",
        borderRadius: 0,
        background: "transparent",
        color: disabled ? t.textDim : t.textMuted,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.35 : 1,
      }}
    >
      {children}
    </button>
  );
}

export function TodoWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: {
  envelope: ToolResultEnvelope;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/todo_native",
    channelId,
    dashboardPinId,
  );
  const widgetInstanceId = currentPayload.widget_instance_id;
  const items = Array.isArray(currentPayload.state?.items)
    ? (currentPayload.state?.items as NativeTodoItem[])
    : [];
  const openItems = items.filter((item) => !item.done);
  const completedItems = items.filter((item) => item.done);
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [draggingId, setDraggingId] = useState<string | null>(null);

  if (!widgetInstanceId) {
    return <PreviewCard title="Todo" description="Persistent task list with inline actions for planning, triage, and cleanup." t={t} />;
  }

  async function runAction(action: string, args: Record<string, unknown>, busyKey = action) {
    setBusy(busyKey);
    setError(null);
    try {
      await dispatchNativeAction(action, args);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function submitNewItem(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const title = newTitle.trim();
    if (!title) return;
    await runAction("add_item", { title }, "add");
    setNewTitle("");
  }

  function beginRename(item: NativeTodoItem) {
    setEditingId(item.id);
    setEditingTitle(item.title);
  }

  async function saveRename(itemId: string) {
    const title = editingTitle.trim();
    if (!title) return;
    await runAction("rename_item", { id: itemId, title }, `rename:${itemId}`);
    setEditingId(null);
    setEditingTitle("");
  }

  async function reorder(openOrdered: NativeTodoItem[]) {
    await runAction(
      "reorder_items",
      { ordered_ids: openOrdered.map((item) => item.id) },
      "reorder",
    );
  }

  function moveOpenItem(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= openItems.length) return;
    const reordered = [...openItems];
    [reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]];
    void reorder(reordered);
  }

  const updatedAt = String(currentPayload.state?.updated_at ?? "");
  const status = error
    ? error
    : busy
      ? "Updating"
      : updatedAt
        ? `Updated ${new Date(updatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : "Saved with this widget";

  const rowBorder = `1px solid ${t.surfaceBorder}`;

  return (
    <div className="group/todo" style={{ display: "flex", flexDirection: "column", minHeight: "100%", color: t.text }}>
      <form
        onSubmit={submitNewItem}
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 34px",
          borderBottom: rowBorder,
          marginBottom: 4,
        }}
      >
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Add a task"
          maxLength={500}
          style={{
            minWidth: 0,
            border: "none",
            borderRadius: 0,
            background: "transparent",
            color: t.text,
            padding: "8px 0",
            fontSize: 13,
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={busy === "add" || !newTitle.trim()}
          aria-label="Add task"
          title="Add task"
          style={{
            border: "none",
            borderRadius: 0,
            background: "transparent",
            color: busy === "add" || !newTitle.trim() ? t.textDim : t.accent,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: busy === "add" || !newTitle.trim() ? "default" : "pointer",
          }}
        >
          <Plus size={16} />
        </button>
      </form>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", minHeight: 24, gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
          {openItems.length} open{completedItems.length ? ` / ${completedItems.length} done` : ""}
        </div>
        {completedItems.length ? (
          <button
            type="button"
            disabled={busy === "clear_completed"}
            onClick={() => void runAction("clear_completed", {}, "clear_completed")}
            style={{
              border: "none",
              borderRadius: 0,
              background: "transparent",
              color: t.textMuted,
              padding: 0,
              fontSize: 11,
              cursor: busy === "clear_completed" ? "default" : "pointer",
            }}
          >
            Clear done
          </button>
        ) : null}
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        {!items.length ? (
          <div style={{ padding: "24px 0", color: t.textMuted, fontSize: 13, lineHeight: 1.5 }}>
            No tasks yet. Add one here, or let a bot drop tasks into this list.
          </div>
        ) : null}

        {openItems.map((item, index) => (
          <div
            key={item.id}
            draggable={busy !== "reorder"}
            onDragStart={() => setDraggingId(item.id)}
            onDragOver={(e) => {
              if (!draggingId || draggingId === item.id) return;
              e.preventDefault();
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (!draggingId || draggingId === item.id) return;
              const reordered = [...openItems];
              const from = reordered.findIndex((entry) => entry.id === draggingId);
              const to = reordered.findIndex((entry) => entry.id === item.id);
              if (from < 0 || to < 0) return;
              const [moved] = reordered.splice(from, 1);
              reordered.splice(to, 0, moved);
              setDraggingId(null);
              void reorder(reordered);
            }}
            onDragEnd={() => setDraggingId(null)}
            style={{
              display: "grid",
              gridTemplateColumns: "14px 18px minmax(0, 1fr) auto",
              alignItems: "center",
              gap: 8,
              minHeight: 36,
              borderTop: rowBorder,
              borderColor: draggingId === item.id ? t.accentBorder : t.surfaceBorder,
              background: draggingId === item.id ? t.accentSubtle : "transparent",
            }}
          >
            <GripVertical size={12} style={{ color: t.textDim }} />
            <input
              type="checkbox"
              checked={item.done}
              onChange={() => void runAction("toggle_item", { id: item.id, done: !item.done }, `toggle:${item.id}`)}
              style={{ width: 13, height: 13, margin: 0 }}
            />
            <div style={{ minWidth: 0 }}>
              {editingId === item.id ? (
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={() => void saveRename(item.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void saveRename(item.id);
                    }
                    if (e.key === "Escape") {
                      setEditingId(null);
                      setEditingTitle("");
                    }
                  }}
                  style={{
                    width: "100%",
                    border: "none",
                    borderRadius: 0,
                    outline: "none",
                    background: "transparent",
                    color: t.text,
                    fontSize: 13,
                    padding: 0,
                  }}
                />
              ) : (
                <button
                  type="button"
                  onClick={() => beginRename(item)}
                  style={{
                    border: "none",
                    borderRadius: 0,
                    background: "transparent",
                    color: t.text,
                    fontSize: 13,
                    padding: 0,
                    textAlign: "left",
                    width: "100%",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    cursor: "text",
                  }}
                >
                  {item.title}
                </button>
              )}
            </div>
            <div className="opacity-0 group-hover/todo:opacity-100 focus-within:opacity-100 transition-opacity" style={{ display: "flex", alignItems: "center" }}>
              <IconButton label="Move up" onClick={() => moveOpenItem(index, -1)} t={t} disabled={index === 0 || busy === "reorder"}>
                <ChevronUp size={14} />
              </IconButton>
              <IconButton label="Move down" onClick={() => moveOpenItem(index, 1)} t={t} disabled={index === openItems.length - 1 || busy === "reorder"}>
                <ChevronDown size={14} />
              </IconButton>
              <IconButton label="Delete task" onClick={() => void runAction("delete_item", { id: item.id }, `delete:${item.id}`)} t={t}>
                <Trash2 size={13} />
              </IconButton>
            </div>
          </div>
        ))}

        {completedItems.length ? (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: t.textDim, marginBottom: 2 }}>
              Completed
            </div>
            {completedItems.map((item) => (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "18px minmax(0, 1fr) auto",
                  alignItems: "center",
                  gap: 8,
                  minHeight: 34,
                  borderTop: rowBorder,
                  opacity: 0.72,
                }}
              >
                <input
                  type="checkbox"
                  checked={item.done}
                  onChange={() => void runAction("toggle_item", { id: item.id, done: false }, `toggle:${item.id}`)}
                  style={{ width: 13, height: 13, margin: 0 }}
                />
                <div style={{ color: t.textDim, textDecoration: "line-through", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.title}
                </div>
                <IconButton label="Delete completed task" onClick={() => void runAction("delete_item", { id: item.id }, `delete:${item.id}`)} t={t}>
                  <X size={13} />
                </IconButton>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div style={{ borderTop: rowBorder, paddingTop: 6, marginTop: 8, fontSize: 11, color: error ? t.danger : t.textDim, display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>{status}</span>
        <span style={{ color: t.textDim }}>Drag rows</span>
      </div>
    </div>
  );
}
