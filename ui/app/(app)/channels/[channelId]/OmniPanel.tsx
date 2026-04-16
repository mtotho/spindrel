/**
 * OmniPanel — dual-section left side panel.
 *
 * Top: File explorer (collapsible, only when workspace exists)
 * Bottom: Pinned tool widgets (always available)
 *
 * Replaces the raw ChannelFileExplorer mount in ChatScreen.
 * The panel is always available — no longer gated on workspaceId.
 */
import { useCallback, useEffect, useRef, useMemo } from "react";
import { ChevronRight, Pin, Layers } from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useThemeTokens } from "@/src/theme/tokens";
import { ChannelFileExplorer } from "./ChannelFileExplorer";
import { PinnedToolWidget } from "./PinnedToolWidget";
import { usePinnedWidgetsStore } from "@/src/stores/pinnedWidgets";
import { useChannel } from "@/src/api/hooks/useChannels";
import type { PinnedWidget } from "@/src/types/api";

interface OmniPanelProps {
  channelId: string;
  botId: string | undefined;
  workspaceId: string | undefined;
  channelDisplayName?: string | null;
  channelWorkspaceEnabled: boolean;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
}

export function OmniPanel({
  channelId,
  botId,
  workspaceId,
  channelDisplayName,
  channelWorkspaceEnabled,
  activeFile,
  onSelectFile,
  onClose,
  width = 260,
  fullWidth = false,
}: OmniPanelProps) {
  const t = useThemeTokens();
  const filesSectionCollapsed = usePinnedWidgetsStore((s) => s.filesSectionCollapsed);
  const toggleFilesCollapsed = usePinnedWidgetsStore((s) => s.toggleFilesSectionCollapsed);

  const { data: channel } = useChannel(channelId);
  const pinnedWidgets = usePinnedWidgetsStore((s) => s.byChannel[channelId] ?? []);
  const unpinWidget = usePinnedWidgetsStore((s) => s.unpinWidget);
  const updateEnvelope = usePinnedWidgetsStore((s) => s.updateEnvelope);

  // Hydrate from server on channel data change (not every render, to preserve optimistic updates).
  // Track by channel updated_at timestamp to avoid JSON.stringify on every render.
  const serverWidgets = channel?.config?.pinned_widgets;
  const channelUpdatedAt = channel?.updated_at;
  const lastHydratedRef = useRef<string | null>(null);
  useEffect(() => {
    const key = `${channelId}:${channelUpdatedAt}`;
    if (key !== lastHydratedRef.current) {
      lastHydratedRef.current = key;
      usePinnedWidgetsStore.getState().hydrateFromChannel(channelId, serverWidgets ?? []);
    }
  }, [channelId, channelUpdatedAt, serverWidgets]);

  const hasWorkspace = !!workspaceId;
  const hasWidgets = pinnedWidgets.length > 0;
  const showFilesSection = hasWorkspace && !filesSectionCollapsed;

  const handleUnpin = useCallback(
    (widgetId: string) => unpinWidget(channelId, widgetId),
    [channelId, unpinWidget],
  );

  const handleEnvelopeUpdate = useCallback(
    (widgetId: string, envelope: PinnedWidget["envelope"]) =>
      updateEnvelope(channelId, widgetId, envelope),
    [channelId, updateEnvelope],
  );

  const reorderWidgets = usePinnedWidgetsStore((s) => s.reorderWidgets);
  const sortedWidgets = useMemo(
    () => [...pinnedWidgets].sort((a, b) => a.position - b.position),
    [pinnedWidgets],
  );
  const widgetIds = useMemo(() => sortedWidgets.map((w) => w.id), [sortedWidgets]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIdx = widgetIds.indexOf(active.id as string);
      const newIdx = widgetIds.indexOf(over.id as string);
      if (oldIdx === -1 || newIdx === -1) return;
      const newOrder = [...widgetIds];
      newOrder.splice(oldIdx, 1);
      newOrder.splice(newIdx, 0, active.id as string);
      reorderWidgets(channelId, newOrder);
    },
    [widgetIds, channelId, reorderWidgets],
  );

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
    >
      {/* ── Files Section ── */}
      {hasWorkspace && (
        <>
          {showFilesSection ? (
            <div className="flex-1 min-h-0 overflow-hidden">
              <ChannelFileExplorer
                channelId={channelId}
                botId={botId}
                workspaceId={workspaceId}
                channelDisplayName={channelDisplayName}
                channelWorkspaceEnabled={channelWorkspaceEnabled}
                activeFile={activeFile}
                onSelectFile={onSelectFile}
                onClose={onClose}
                onCollapseFiles={toggleFilesCollapsed}
                fullWidth
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={toggleFilesCollapsed}
              className="flex items-center gap-1 px-2.5 h-7 hover:bg-white/[0.04] transition-colors duration-150"
            >
              <ChevronRight size={12} color={t.textMuted} />
              <span
                className="flex-1 text-left uppercase tracking-wider"
                style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
              >
                Files
              </span>
            </button>
          )}
          {/* Subtle divider between sections */}
          <div className="h-px mx-2" style={{ backgroundColor: `${t.surfaceBorder}33` }} />
        </>
      )}

      {/* ── Pinned Widgets Section ── */}
      <div className="flex flex-col min-h-0" style={{ flex: hasWorkspace && showFilesSection ? "none" : 1 }}>
        <div className="flex items-center gap-1 px-2.5 h-7">
          <Pin size={11} color={t.textMuted} />
          <span
            className="flex-1 uppercase tracking-wider"
            style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
          >
            Pinned
          </span>
          {hasWidgets && (
            <span
              className="text-xs tabular-nums"
              style={{ color: t.textMuted, opacity: 0.6 }}
            >
              {pinnedWidgets.length}
            </span>
          )}
        </div>

        {hasWidgets ? (
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-1.5">
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={widgetIds} strategy={verticalListSortingStrategy}>
                {sortedWidgets.map((widget) => (
                  <PinnedToolWidget
                    key={widget.id}
                    widget={widget}
                    channelId={channelId}
                    onUnpin={handleUnpin}
                    onEnvelopeUpdate={handleEnvelopeUpdate}
                  />
                ))}
              </SortableContext>
            </DndContext>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center px-4 py-8 gap-2">
            <Layers size={24} style={{ color: t.textMuted, opacity: 0.3 }} />
            <span
              className="text-center text-xs leading-relaxed"
              style={{ color: t.textMuted, opacity: 0.5 }}
            >
              Pin tool widgets from chat for quick access
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
