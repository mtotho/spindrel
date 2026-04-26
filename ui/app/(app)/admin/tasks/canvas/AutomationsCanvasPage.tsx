/**
 * AutomationsCanvasPage — canvas-mode of /admin/automations.
 *
 * Activated by `?canvas=1`. Sidebar lists task definitions; main area is a
 * dot-grid plane that hosts floating cards. `?new=1` overlays the new-task
 * flow (mode picker → editor); `?edit=<taskId>` overlays an editor card for
 * an existing task.
 *
 * Initial scope: definitions live in the sidebar (positioning on the plane
 * is parked). One card on the plane at a time.
 */
import { useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { List, Plus } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type { TasksResponse } from "@/src/components/shared/TaskConstants";
import { DefinitionsSidebar } from "./DefinitionsSidebar";
import { ModePickerCard } from "./ModePickerCard";
import { CanvasEditor } from "./CanvasEditor";

export function AutomationsCanvasPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const isNew = searchParams.get("new") === "1";
  const editTaskId = searchParams.get("edit") || null;
  const pickedMode = searchParams.get("mode") as "prompt" | "pipeline" | null;

  const setParams = useCallback(
    (updates: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(updates)) {
            if (v === null || v === "") next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks-canvas-definitions"],
    queryFn: () => apiFetch<TasksResponse>("/api/v1/admin/tasks?limit=200&definitions_only=true"),
  });

  const definitions = (data?.tasks ?? []).filter((t) => t.source !== "system");

  const closeCard = () => setParams({ new: null, edit: null, mode: null });
  const openNew = () => setParams({ new: "1", edit: null, mode: null });
  const openEdit = (taskId: string) => setParams({ edit: taskId, new: null, mode: null });
  const exitCanvas = () => setParams({ canvas: null, new: null, edit: null, mode: null });

  return (
    <div className="flex flex-row flex-1 min-h-0 bg-surface overflow-hidden">
      <DefinitionsSidebar
        definitions={definitions}
        loading={isLoading}
        selectedTaskId={editTaskId}
        onSelect={openEdit}
        onNew={openNew}
      />

      {/* Canvas plane */}
      <div className="relative flex-1 min-w-0 overflow-hidden bg-surface">
        {/* Dot-grid background */}
        <div
          aria-hidden
          className="absolute inset-0 pointer-events-none opacity-50"
          style={{
            backgroundImage:
              "radial-gradient(circle, rgb(var(--color-text-dim) / 0.18) 1px, transparent 1px)",
            backgroundSize: "24px 24px",
          }}
        />

        {/* Top-right floating controls */}
        <div className="absolute top-3 right-3 z-10 flex flex-row items-center gap-2">
          <button
            onClick={exitCanvas}
            title="Switch to list mode"
            className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-surface-raised/70 text-text-dim hover:text-text hover:bg-surface-raised transition-colors backdrop-blur"
          >
            <List size={14} />
            List
          </button>
          {!isNew && !editTaskId && (
            <button
              onClick={openNew}
              title="New Task"
              className="flex flex-row items-center gap-1.5 px-3 py-[5px] text-xs font-semibold border-none cursor-pointer rounded-md bg-accent/10 text-accent hover:bg-accent/20 transition-colors backdrop-blur"
            >
              <Plus size={14} />
              New Task
            </button>
          )}
        </div>

        {/* Mode picker — centered floating card before a mode is chosen */}
        {isNew && !pickedMode && !editTaskId && (
          <div className="absolute inset-0 z-[1] flex items-center justify-center p-6 overflow-y-auto pointer-events-none">
            <div className="pointer-events-auto">
              <ModePickerCard
                onPick={(mode) => setParams({ mode })}
                onClose={closeCard}
              />
            </div>
          </div>
        )}

        {/* Tile-based editor — covers the canvas plane with floating tiles */}
        {isNew && pickedMode && (
          <CanvasEditor
            key={`new-${pickedMode}`}
            mode="create"
            initialMode={pickedMode}
            onClose={closeCard}
            onSaved={(createdId) => {
              if (createdId) openEdit(createdId);
              else closeCard();
            }}
          />
        )}
        {editTaskId && (
          <CanvasEditor
            key={`edit-${editTaskId}`}
            mode="edit"
            taskId={editTaskId}
            onClose={closeCard}
            onSaved={() => {
              /* stay on the canvas after save so user can keep iterating */
            }}
            onDeleted={closeCard}
          />
        )}
      </div>
    </div>
  );
}
