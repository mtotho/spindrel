import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Check, ChevronDown, ChevronUp, GripVertical, Plus, Trash2, X } from "lucide-react";
import {
  PreviewCard,
  type NativeAppRendererProps,
  type NativeTodoItem,
  useNativeEnvelopeState,
} from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";

function IconButton({
  label,
  onClick,
  t,
  disabled = false,
  children,
}: {
  label: string;
  onClick: () => void;
  t: NativeAppRendererProps["t"];
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

function TodoToggleButton({
  checked,
  label,
  disabled = false,
  onClick,
  t,
}: {
  checked: boolean;
  label: string;
  disabled?: boolean;
  onClick: () => void;
  t: NativeAppRendererProps["t"];
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={checked}
      disabled={disabled}
      onClick={onClick}
      title={label}
      style={{
        width: 16,
        height: 16,
        borderRadius: 3,
        border: `1px solid ${checked ? t.accentBorder : t.surfaceBorder}`,
        background: checked ? t.accent : "transparent",
        color: checked ? "#fff" : t.textDim,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 0,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
        boxShadow: checked ? `0 0 0 1px ${t.accentBorder} inset` : "none",
      }}
    >
      {checked ? <Check size={12} strokeWidth={2.5} /> : null}
    </button>
  );
}

function CompactViewButton({
  active,
  label,
  onClick,
  t,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  t: NativeAppRendererProps["t"];
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: "none",
        background: "transparent",
        color: active ? t.textMuted : t.textDim,
        padding: 0,
        fontSize: 11,
        textDecoration: active ? "underline" : "none",
        textUnderlineOffset: 2,
        textDecorationColor: active ? t.textMuted : "transparent",
        cursor: "pointer",
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
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 420,
    compactMaxHeight: 260,
    wideMinWidth: 720,
    wideMinHeight: 220,
    tallMinHeight: 320,
  });
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
  const [compactSelectedId, setCompactSelectedId] = useState<string | null>(null);
  const [compactView, setCompactView] = useState<"open" | "done">("open");

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
  const actionAlwaysVisible = profile.wide || profile.tall;
  const compactDense = layout === "chip" || layout === "header" || profile.height < 170;
  const stripMode = (layout === "header" || layout === "chip") && profile.height > 0 && profile.height <= 96;

  useEffect(() => {
    if (!compactSelectedId) return;
    const visibleCompactItems = compactView === "done" ? completedItems : openItems;
    if (!visibleCompactItems.some((item) => item.id === compactSelectedId)) {
      setCompactSelectedId(null);
    }
  }, [compactSelectedId, compactView, completedItems, openItems]);

  useEffect(() => {
    if (compactView === "done" && completedItems.length === 0) {
      setCompactView("open");
    }
  }, [compactView, completedItems.length]);

  if (profile.compact) {
    if (stripMode) {
      const visibleCompactItems = compactView === "done" ? completedItems : openItems;
      const focusedItem = visibleCompactItems.find((item) => item.id === compactSelectedId) ?? visibleCompactItems[0] ?? null;
      const itemSelected = Boolean(focusedItem && compactSelectedId === focusedItem.id);
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            height: "100%",
            minHeight: 0,
            overflow: "hidden",
            color: t.text,
          }}
        >
          <form
            onSubmit={submitNewItem}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) 24px",
              alignItems: "center",
              gap: 8,
              minHeight: 34,
              borderBottom: rowBorder,
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
                padding: 0,
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
                color: busy === "add" || !newTitle.trim() ? t.textDim : t.textMuted,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: busy === "add" || !newTitle.trim() ? "default" : "pointer",
                padding: 0,
              }}
            >
              <Plus size={15} />
            </button>
          </form>

          <div
            style={{
              minHeight: 24,
              display: "grid",
              gridTemplateColumns: focusedItem ? "16px minmax(0, 1fr) auto" : "minmax(0, 1fr) auto",
              alignItems: "center",
              gap: 8,
              color: t.textDim,
              fontSize: 11,
              lineHeight: 1.1,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {focusedItem ? (
              <>
                <TodoToggleButton
                  checked={itemSelected}
                  label={itemSelected ? "Hide task actions" : "Show task actions"}
                  onClick={() => setCompactSelectedId(itemSelected ? null : focusedItem.id)}
                  t={t}
                />
                <div
                  style={{
                    minWidth: 0,
                    color: itemSelected ? t.text : t.textDim,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontSize: 12,
                    lineHeight: 1.1,
                    cursor: "pointer",
                  }}
                  title={focusedItem.title}
                  onClick={() => setCompactSelectedId(itemSelected ? null : focusedItem.id)}
                >
                  {focusedItem.title}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, justifySelf: "end" }}>
                  {itemSelected ? (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          void runAction(
                            "toggle_item",
                            { id: focusedItem.id, done: compactView === "open" },
                            `toggle:${focusedItem.id}`,
                          );
                          setCompactSelectedId(null);
                        }}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: t.text,
                          padding: 0,
                          fontSize: 11,
                          cursor: "pointer",
                        }}
                      >
                        {compactView === "done" ? "Mark open" : "Mark done"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void runAction("delete_item", { id: focusedItem.id }, `delete:${focusedItem.id}`);
                          setCompactSelectedId(null);
                        }}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: t.textDim,
                          padding: 0,
                          fontSize: 11,
                          cursor: "pointer",
                        }}
                      >
                        Delete
                      </button>
                    </>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <CompactViewButton
                        active={compactView === "open"}
                        label={`${openItems.length} open`}
                        onClick={() => setCompactView("open")}
                        t={t}
                      />
                      {completedItems.length ? (
                        <CompactViewButton
                          active={compactView === "done"}
                          label={`${completedItems.length} done`}
                          onClick={() => setCompactView("done")}
                          t={t}
                        />
                      ) : null}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {compactView === "done"
                    ? "No completed tasks"
                    : completedItems.length
                      ? `${completedItems.length} done`
                      : "No tasks yet"}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, justifySelf: "end" }}>
                  <CompactViewButton
                    active={compactView === "open"}
                    label={`${openItems.length} open`}
                    onClick={() => setCompactView("open")}
                    t={t}
                  />
                  {completedItems.length ? (
                    <CompactViewButton
                      active={compactView === "done"}
                      label={`${completedItems.length} done`}
                      onClick={() => setCompactView("done")}
                      t={t}
                    />
                  ) : null}
                </div>
              </>
            )}
          </div>
        </div>
      );
    }

    const visibleCompactItems = compactView === "done" ? completedItems : openItems;
    const visibleOpen = visibleCompactItems.slice(0, compactDense ? 1 : 2);
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: compactDense ? 8 : 10, minHeight: "100%", color: t.text }}>
        <form
          onSubmit={submitNewItem}
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 32px",
            gap: 6,
            borderBottom: rowBorder,
            paddingBottom: 4,
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
              padding: "6px 0",
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
              color: busy === "add" || !newTitle.trim() ? t.textDim : t.textMuted,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: busy === "add" || !newTitle.trim() ? "default" : "pointer",
            }}
          >
            <Plus size={16} />
          </button>
        </form>

        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
            <CompactViewButton
              active={compactView === "open"}
              label={`${openItems.length} open`}
              onClick={() => setCompactView("open")}
              t={t}
            />
            {completedItems.length ? (
              <CompactViewButton
                active={compactView === "done"}
                label={`${completedItems.length} done`}
                onClick={() => setCompactView("done")}
                t={t}
              />
            ) : null}
          </div>
          {completedItems.length && compactView === "done" && !compactDense ? (
            <button
              type="button"
              disabled={busy === "clear_completed"}
              onClick={() => void runAction("clear_completed", {}, "clear_completed")}
              style={{
                border: "none",
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

        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minHeight: 0 }}>
          {!items.length ? (
            <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.5 }}>
              No tasks yet.
            </div>
          ) : null}
          {items.length && !visibleOpen.length ? (
            <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.5 }}>
              {compactView === "done" ? "No completed tasks." : "No open tasks."}
            </div>
          ) : null}
          {visibleOpen.map((item) => (
            <div
              key={item.id}
              onClick={() => setCompactSelectedId(compactSelectedId === item.id ? null : item.id)}
              style={{
                display: "grid",
                gridTemplateColumns: "16px minmax(0, 1fr) auto",
                gap: compactDense ? 6 : 8,
                alignItems: "center",
                minHeight: compactDense ? 30 : 34,
                borderTop: rowBorder,
                padding: compactDense ? "5px 0" : "6px 0",
                cursor: "pointer",
              }}
            >
              <TodoToggleButton
                checked={compactSelectedId === item.id}
                label={compactSelectedId === item.id ? "Hide task actions" : "Show task actions"}
                onClick={() => setCompactSelectedId(compactSelectedId === item.id ? null : item.id)}
                t={t}
              />
              <div
                style={{
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontSize: compactDense ? 11.5 : 12,
                  lineHeight: 1.3,
                }}
                title={item.title}
              >
                {item.title}
              </div>
              {compactSelectedId === item.id ? (
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{ display: "flex", alignItems: "center", gap: 10 }}
                >
                  <button
                    type="button"
                    onClick={() => {
                      void runAction(
                        "toggle_item",
                        { id: item.id, done: compactView === "open" },
                        `toggle:${item.id}`,
                      );
                      setCompactSelectedId(null);
                    }}
                    style={{
                      border: "none",
                      background: "transparent",
                      color: t.text,
                      padding: 0,
                      fontSize: 11,
                      cursor: "pointer",
                    }}
                  >
                    {compactView === "done" ? "Mark open" : "Mark done"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void runAction("delete_item", { id: item.id }, `delete:${item.id}`);
                      setCompactSelectedId(null);
                    }}
                    style={{
                      border: "none",
                      background: "transparent",
                      color: t.textDim,
                      padding: 0,
                      fontSize: 11,
                      cursor: "pointer",
                    }}
                  >
                    Delete
                  </button>
                </div>
              ) : null}
            </div>
          ))}
          {openItems.length > visibleOpen.length ? (
            <div style={{ fontSize: 11, color: t.textDim }}>
              {visibleCompactItems.length - visibleOpen.length} more {compactView} task{visibleCompactItems.length - visibleOpen.length === 1 ? "" : "s"}.
            </div>
          ) : null}
        </div>

        <div
          style={{
            marginTop: "auto",
            paddingTop: 4,
            fontSize: 11,
            color: error ? t.danger : t.textDim,
            display: "flex",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          {status}
          {completedItems.length && compactDense ? (
            <button
              type="button"
              disabled={busy === "clear_completed"}
              onClick={() => void runAction("clear_completed", {}, "clear_completed")}
              style={{
                border: "none",
                background: "transparent",
                color: t.textMuted,
                padding: 0,
                fontSize: 11,
                cursor: busy === "clear_completed" ? "default" : "pointer",
              }}
            >
              Clear done
            </button>
          ) : compactView === "done" && !completedItems.length ? (
            <button
              type="button"
              onClick={() => setCompactView("open")}
              style={{
                border: "none",
                background: "transparent",
                color: t.textMuted,
                padding: 0,
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              Back to open
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  const openList = (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
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
          <TodoToggleButton
            checked={item.done}
            label={item.done ? "Mark task open" : "Mark task done"}
            onClick={() => void runAction("toggle_item", { id: item.id, done: !item.done }, `toggle:${item.id}`)}
            t={t}
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
          <div
            className={actionAlwaysVisible ? undefined : "opacity-0 group-hover/todo:opacity-100 focus-within:opacity-100 transition-opacity"}
            style={{ display: "flex", alignItems: "center", opacity: actionAlwaysVisible ? 1 : undefined }}
          >
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
    </div>
  );

  const completedList = completedItems.length ? (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
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
          <TodoToggleButton
            checked={item.done}
            label="Mark task open"
            onClick={() => void runAction("toggle_item", { id: item.id, done: false }, `toggle:${item.id}`)}
            t={t}
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
  ) : null;

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

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: profile.wide && completedList ? "grid" : "flex",
          gridTemplateColumns: profile.wide && completedList ? "minmax(0, 1.7fr) minmax(0, 1fr)" : undefined,
          gap: profile.wide && completedList ? 16 : undefined,
          flexDirection: profile.wide && completedList ? undefined : "column",
        }}
      >
        {openList}
        {!profile.wide && completedList ? <div style={{ marginTop: 10 }}>{completedList}</div> : null}
        {profile.wide && completedList ? completedList : null}
      </div>

      <div style={{ borderTop: rowBorder, paddingTop: 6, marginTop: 8, fontSize: 11, color: error ? t.danger : t.textDim, display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>{status}</span>
        <span style={{ color: t.textDim }}>{profile.compact ? "Quick list" : "Drag rows"}</span>
      </div>
    </div>
  );
}
