import { useState } from "react";
import type { FormEvent } from "react";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, type NativeTodoItem, useNativeEnvelopeState } from "./shared";

function TodoRowButton({
  label,
  onClick,
  t,
  disabled = false,
}: {
  label: string;
  onClick: () => void;
  t: ThemeTokens;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        background: disabled ? t.surface : "transparent",
        color: disabled ? t.textDim : t.textMuted,
        borderRadius: 999,
        padding: "3px 8px",
        fontSize: 11,
        cursor: disabled ? "default" : "pointer",
      }}
    >
      {label}
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "100%" }}>
      <form onSubmit={submitNewItem} style={{ display: "flex", gap: 8 }}>
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Add a task"
          maxLength={500}
          style={{
            flex: 1,
            borderRadius: 12,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surface,
            color: t.text,
            padding: "10px 12px",
            fontSize: 13,
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={busy === "add" || !newTitle.trim()}
          style={{
            border: "none",
            borderRadius: 12,
            background: t.accent,
            color: "#ffffff",
            padding: "0 14px",
            fontSize: 13,
            fontWeight: 600,
            cursor: busy === "add" || !newTitle.trim() ? "default" : "pointer",
            opacity: busy === "add" || !newTitle.trim() ? 0.6 : 1,
          }}
        >
          Add
        </button>
      </form>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12, color: t.textDim }}>
          {openItems.length} open
          {completedItems.length ? `, ${completedItems.length} done` : ""}
        </div>
        <button
          type="button"
          disabled={!completedItems.length || busy === "clear_completed"}
          onClick={() => void runAction("clear_completed", {}, "clear_completed")}
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 999,
            background: "transparent",
            color: completedItems.length ? t.textMuted : t.textDim,
            padding: "4px 10px",
            fontSize: 11,
            cursor: !completedItems.length || busy === "clear_completed" ? "default" : "pointer",
          }}
        >
          Clear completed
        </button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
        {!items.length ? (
          <div
            style={{
              border: `1px dashed ${t.surfaceBorder}`,
              borderRadius: 14,
              padding: 18,
              color: t.textMuted,
              fontSize: 13,
              background: t.surface,
            }}
          >
            No tasks yet. Add the first one above, or let a bot drop tasks into this list.
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
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 12px",
              borderRadius: 14,
              border: `1px solid ${draggingId === item.id ? t.accent : t.surfaceBorder}`,
              background: t.surface,
            }}
          >
            <input
              type="checkbox"
              checked={item.done}
              onChange={() => void runAction("toggle_item", { id: item.id, done: !item.done }, `toggle:${item.id}`)}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
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
                    background: "transparent",
                    color: t.text,
                    fontSize: 13,
                    padding: 0,
                    textAlign: "left",
                    width: "100%",
                    cursor: "text",
                  }}
                >
                  {item.title}
                </button>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <TodoRowButton label="Up" onClick={() => {
                if (index === 0) return;
                const reordered = [...openItems];
                [reordered[index - 1], reordered[index]] = [reordered[index], reordered[index - 1]];
                void reorder(reordered);
              }} t={t} disabled={index === 0 || busy === "reorder"} />
              <TodoRowButton label="Down" onClick={() => {
                if (index === openItems.length - 1) return;
                const reordered = [...openItems];
                [reordered[index], reordered[index + 1]] = [reordered[index + 1], reordered[index]];
                void reorder(reordered);
              }} t={t} disabled={index === openItems.length - 1 || busy === "reorder"} />
              <TodoRowButton label="Delete" onClick={() => void runAction("delete_item", { id: item.id }, `delete:${item.id}`)} t={t} />
            </div>
          </div>
        ))}

        {completedItems.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
            <div style={{ fontSize: 12, color: t.textDim }}>Completed</div>
            {completedItems.map((item) => (
              <div
                key={item.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: `1px solid ${t.surfaceBorder}`,
                  background: t.surface,
                  opacity: 0.78,
                }}
              >
                <input
                  type="checkbox"
                  checked={item.done}
                  onChange={() => void runAction("toggle_item", { id: item.id, done: false }, `toggle:${item.id}`)}
                />
                <div style={{ flex: 1, color: t.textDim, textDecoration: "line-through", fontSize: 13 }}>{item.title}</div>
                <TodoRowButton label="Delete" onClick={() => void runAction("delete_item", { id: item.id }, `delete:${item.id}`)} t={t} />
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12, color: error ? t.danger : t.textDim }}>
        <span>{error ? error : busy ? "Updating..." : "Click a task to rename. Drag or use Up/Down to reorder open items."}</span>
        <span>{items.length ? `Last change ${new Date(String(currentPayload.state?.updated_at ?? "")).toLocaleString()}` : "State persists with the widget instance."}</span>
      </div>
    </div>
  );
}
