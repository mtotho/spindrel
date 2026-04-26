/**
 * AutomationsCanvasPage — fullscreen host for the canvas-mode editor.
 *
 * Activated by `?canvas=1`. The workspace spatial canvas is the index
 * surface (definitions live there as an outer-ring orbit); this route
 * is dedicated to editing or creating one definition. The page mounts
 * the mode picker (when `?new=1` without `&mode=`) or the xyflow
 * editor (when `&mode=` is set, or `?edit=<id>` is set). Empty
 * `?canvas=1` redirects back to the spatial canvas.
 */
import { useCallback, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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

  // Empty `?canvas=1` (no new/edit) → redirect to the spatial canvas.
  useEffect(() => {
    if (!isNew && !editTaskId) {
      navigate("/canvas", { replace: true });
    }
  }, [isNew, editTaskId, navigate]);

  const closeCard = () => navigate("/canvas");
  const openEdit = (taskId: string) => setParams({ edit: taskId, new: null, mode: null });

  return (
    <div className="relative flex-1 min-h-0 bg-surface overflow-hidden">
      {/* Mode picker — centered floating card before a mode is chosen */}
      {isNew && !pickedMode && !editTaskId && (
        <>
          <div
            aria-hidden
            className="absolute inset-0 pointer-events-none opacity-50"
            style={{
              backgroundImage:
                "radial-gradient(circle, rgb(var(--color-text-dim) / 0.18) 1px, transparent 1px)",
              backgroundSize: "24px 24px",
            }}
          />
          <div className="absolute inset-0 z-[1] flex items-center justify-center p-6 overflow-y-auto pointer-events-none">
            <div className="pointer-events-auto">
              <ModePickerCard
                onPick={(mode) => setParams({ mode })}
                onClose={closeCard}
              />
            </div>
          </div>
        </>
      )}

      {/* xyflow editor — fullscreen */}
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
  );
}
