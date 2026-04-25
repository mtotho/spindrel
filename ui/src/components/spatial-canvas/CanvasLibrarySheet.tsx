import { useEffect } from "react";
import { X } from "lucide-react";
import {
  WidgetLibrary,
  type LibraryPinPayload,
} from "@/app/(app)/widgets/WidgetLibrary";
import { usePinWidgetToCanvas } from "@/src/api/hooks/useWorkspaceSpatial";

interface CanvasLibrarySheetProps {
  open: boolean;
  onClose: () => void;
  /** World-coordinate target for newly-pinned widgets (camera center). */
  worldCenter: { x: number; y: number } | null;
}

const PIN_W = 320;
const PIN_H = 220;

/**
 * Side-sheet wrapper around the existing `WidgetLibrary` in pin mode. Pinning
 * any library entry creates a workspace-canvas spatial node + dashboard pin
 * (on `workspace:spatial`) at the camera center. Reuses the same library
 * surface as `/(app)/widgets/` — no duplicated pin paths.
 */
export function CanvasLibrarySheet({ open, onClose, worldCenter }: CanvasLibrarySheetProps) {
  const pin = usePinWidgetToCanvas();

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function handlePin(payload: LibraryPinPayload) {
    const { entry, envelope, botId } = payload;
    const x = (worldCenter?.x ?? 0) - PIN_W / 2;
    const y = (worldCenter?.y ?? 0) - PIN_H / 2;

    if (entry.widget_kind === "native_app" && entry.widget_ref) {
      // Native widgets are widget_ref-bound; we use the ref itself as the
      // pin's tool_name so the row reads usefully in admin views.
      await pin.mutateAsync({
        source_kind: "adhoc",
        tool_name: entry.widget_ref,
        envelope: envelope as unknown as Record<string, unknown>,
        source_bot_id: botId ?? null,
        display_label: envelope.display_label ?? undefined,
        world_x: x,
        world_y: y,
        world_w: PIN_W,
        world_h: PIN_H,
      });
      onClose();
      return;
    }

    // HTML library / scanner entries — same shape as the channel-dashboard
    // library uses, just routed at workspace canvas coords.
    let toolArgs: Record<string, unknown>;
    let sourceKind: "adhoc" | "channel" = "adhoc";
    let pinChannelId: string | null = null;
    if (entry.scope === "integration") {
      toolArgs = {
        source: "integration",
        integration_id: entry.integration_id,
        path: entry.path,
      };
    } else if (entry.scope === "channel") {
      const cid = entry.channel_id ?? null;
      toolArgs = cid && entry.path
        ? { path: `/workspace/channels/${cid}/${entry.path}` }
        : { path: entry.path };
      sourceKind = cid ? "channel" : "adhoc";
      pinChannelId = cid;
    } else {
      toolArgs = { library_ref: `${entry.scope}/${entry.name}` };
    }
    await pin.mutateAsync({
      source_kind: sourceKind,
      tool_name: "emit_html_widget",
      tool_args: toolArgs,
      envelope: envelope as unknown as Record<string, unknown>,
      source_bot_id: botId ?? null,
      source_channel_id: pinChannelId ?? undefined,
      display_label: entry.display_label ?? entry.name,
      world_x: x,
      world_y: y,
      world_w: PIN_W,
      world_h: PIN_H,
    });
    onClose();
  }

  return (
    <>
      <div
        className="absolute inset-0 z-[5] bg-bg/30 backdrop-blur-[2px]"
        onClick={onClose}
        onPointerDown={(e) => e.stopPropagation()}
      />
      <div
        className="absolute top-0 right-0 bottom-0 z-[6] w-[420px] max-w-[92%] bg-surface-raised border-l border-surface-border shadow-2xl flex flex-col overflow-hidden"
        onPointerDown={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
      >
        <div className="flex flex-row items-center gap-2 px-4 py-3 border-b border-surface-border">
          <span className="text-sm font-semibold text-text">Add to canvas</span>
          <span className="text-[11px] text-text-dim">drops at camera center</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            className="text-text-dim hover:text-text"
            title="Close (Esc)"
            aria-label="Close library"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <WidgetLibrary
            mode="pin"
            botEnumeration="all-bots"
            pinScope={{ kind: "user" }}
            libraryBotId={null}
            scopeChannelId={null}
            onPin={handlePin}
          />
        </div>
        {pin.isPending && (
          <div className="px-4 py-2 text-[11px] text-text-dim border-t border-surface-border">
            pinning…
          </div>
        )}
      </div>
    </>
  );
}
