import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  WidgetLibrary,
  type LibraryPinPayload,
} from "@/app/(app)/widgets/WidgetLibrary";
import {
  WidgetPresetsPane,
  type PresetPinContext,
} from "@/app/(app)/widgets/WidgetPresetsPane";
import {
  usePinWidgetToCanvas,
  usePinPresetToCanvas,
} from "@/src/api/hooks/useWorkspaceSpatial";

interface CanvasLibrarySheetProps {
  open: boolean;
  onClose: () => void;
  /** World-coordinate target for newly-pinned widgets (camera center). */
  worldCenter: { x: number; y: number } | null;
}

interface CanvasLibraryContentProps {
  onClose: () => void;
  /** World-coordinate target for newly-pinned widgets (camera center). */
  worldCenter: { x: number; y: number } | null;
  embedded?: boolean;
}

const PIN_W = 320;
const PIN_H = 220;

type Tab = "presets" | "library";

/**
 * Side-sheet wrapper around the existing widget library + preset pickers,
 * routed at the workspace canvas. Two tabs:
 *
 * - **Presets** (default) — `widget_presets` from every enabled integration.
 *   This matches the dashboard's preset DX: pick → bind → preview → pin. The
 *   pin lands on the canvas via `usePinPresetToCanvas` instead of the
 *   default dashboard target.
 * - **Library** — standalone HTML bundles (core / bot / workspace scopes)
 *   that don't need tool args. Tool widgets attached to integration
 *   `tool_widgets` blocks are intentionally **not** here — those are
 *   instantiated through their preset wrapper instead.
 */
export function CanvasLibrarySheet({ open, onClose, worldCenter }: CanvasLibrarySheetProps) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

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
        <CanvasLibraryContent onClose={onClose} worldCenter={worldCenter} />
      </div>
    </>
  );
}

export function CanvasLibraryContent({ onClose, worldCenter, embedded = false }: CanvasLibraryContentProps) {
  const pin = usePinWidgetToCanvas();
  const pinPreset = usePinPresetToCanvas();
  const [tab, setTab] = useState<Tab>("presets");

  const x = (worldCenter?.x ?? 0) - PIN_W / 2;
  const y = (worldCenter?.y ?? 0) - PIN_H / 2;

  async function handleLibraryPin(payload: LibraryPinPayload) {
    const { entry, envelope, botId } = payload;

    if (entry.widget_kind === "native_app" && entry.widget_ref) {
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

  async function handlePresetPin(ctx: PresetPinContext): Promise<{ id: string }> {
    const created = await pinPreset.mutateAsync({
      preset_id: ctx.presetId,
      config: ctx.config,
      source_bot_id: ctx.sourceBotId,
      source_channel_id: ctx.sourceChannelId,
      display_label: ctx.displayLabel,
      world_x: x,
      world_y: y,
      world_w: PIN_W,
      world_h: PIN_H,
    });
    onClose();
    return { id: created.pin.id };
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${embedded ? "" : "bg-surface-raised"}`}>
        {!embedded && (
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
        )}
        {embedded && (
          <div className="px-2 pb-2 text-xs text-text-muted">
            Drops at the current camera center unless opened from a map position.
          </div>
        )}
        <div className="flex flex-row items-center gap-1 px-2 pb-2">
          <CanvasTab label="Presets" active={tab === "presets"} onClick={() => setTab("presets")} />
          <CanvasTab label="Library" active={tab === "library"} onClick={() => setTab("library")} />
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          {tab === "presets" ? (
            <WidgetPresetsPane
              mode="pin"
              scopeChannelId={null}
              onPin={handlePresetPin}
              layout="narrow"
            />
          ) : (
            <WidgetLibrary
              mode="pin"
              botEnumeration="all-bots"
              pinScope={{ kind: "user" }}
              libraryBotId={null}
              scopeChannelId={null}
              onPin={handleLibraryPin}
              hideToolRenderers
            />
          )}
        </div>
        {(pin.isPending || pinPreset.isPending) && (
          <div className="px-4 py-2 text-[11px] text-text-dim">
            pinning...
          </div>
        )}
      </div>
  );
}

function CanvasTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-md px-3 py-1.5 text-[12px] transition-colors",
        active ? "bg-accent/15 text-accent font-semibold" : "text-text-muted hover:bg-surface-overlay/60",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
