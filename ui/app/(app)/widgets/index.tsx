import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { LayoutDashboard, Plus, Wrench } from "lucide-react";
import { DndContext, closestCenter } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type { PinnedWidget, ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";
import AddFromChannelSheet from "./AddFromChannelSheet";

/** Adapt a WidgetDashboardPin row to the PinnedWidget shape the PinnedToolWidget
 *  renderer expects. Dashboard-scope calls use `widget_config` while channel-
 *  scope calls use `config`; the scope prop is what routes the store writes. */
function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    config: pin.widget_config ?? {},
  };
}

export default function WidgetsDashboardPage() {
  const { pins, isLoading, error } = useDashboardPins();
  const unpinWidget = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const [sheetOpen, setSheetOpen] = useState(false);

  const handleUnpin = async (pinId: string) => {
    try {
      await unpinWidget(pinId);
    } catch (err) {
      console.error("Failed to unpin dashboard widget:", err);
    }
  };

  const handleEnvelopeUpdate = (pinId: string, envelope: ToolResultEnvelope) => {
    updateEnvelope(pinId, envelope);
  };

  const widgetIds = useMemo(() => pins.map((p) => p.id), [pins]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="list"
        title="Widgets"
        subtitle="Pinned tool results, live"
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSheetOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-[12px] font-medium text-white hover:opacity-90 transition-opacity"
            >
              <Plus size={13} />
              Add widget
            </button>
            <Link
              to="/widgets/dev"
              className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
            >
              <Wrench size={13} />
              Developer panel
            </Link>
          </div>
        }
      />

      <div className="flex-1 overflow-auto p-6">
        {isLoading && <DashboardSkeleton />}
        {!isLoading && error && (
          <div className="mx-auto max-w-2xl rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-center text-[13px] text-red-400">
            Failed to load dashboard: {error}
          </div>
        )}
        {!isLoading && !error && pins.length === 0 && (
          <EmptyState onAddClick={() => setSheetOpen(true)} />
        )}
        {!isLoading && !error && pins.length > 0 && (
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
          >
            {/* DnD wrapper lets the nested PinnedToolWidget's `useSortable`
                hook resolve without exploding; actual reorder is P5. */}
            <DndContext collisionDetection={closestCenter}>
              <SortableContext items={widgetIds} strategy={verticalListSortingStrategy}>
                {pins.map((p) => (
                  <PinnedToolWidget
                    key={p.id}
                    widget={asPinnedWidget(p)}
                    scope={{ kind: "dashboard" }}
                    onUnpin={handleUnpin}
                    onEnvelopeUpdate={handleEnvelopeUpdate}
                  />
                ))}
              </SortableContext>
            </DndContext>
          </div>
        )}
      </div>

      <AddFromChannelSheet open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </div>
  );
}

function EmptyState({ onAddClick }: { onAddClick: () => void }) {
  return (
    <div className="mx-auto max-w-2xl rounded-lg border border-dashed border-surface-border bg-surface-raised p-10 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent/10">
        <LayoutDashboard size={22} className="text-accent" />
      </div>
      <h2 className="mb-2 text-[16px] font-semibold text-text">No widgets yet</h2>
      <p className="mb-6 text-[13px] text-text-muted">
        Pin widgets here from a channel, or build them from scratch in the developer panel.
      </p>
      <div className="flex justify-center gap-2">
        <button
          type="button"
          onClick={onAddClick}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 transition-opacity"
        >
          <Plus size={13} />
          Add from channel
        </button>
        <Link
          to="/widgets/dev#tools"
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay transition-colors"
        >
          <Wrench size={13} />
          Open developer panel
        </Link>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div
      className="grid gap-3"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-lg border border-surface-border bg-surface-raised"
        />
      ))}
    </div>
  );
}
