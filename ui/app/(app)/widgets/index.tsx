import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useUIStore } from "@/src/stores/ui";
import { useKioskMode } from "@/src/hooks/useKioskMode";
import { Check, ChevronDown, Info, LayoutDashboard, Maximize2, MessageSquare, Minimize2, Move, Plus, Settings, Sparkles, Wrench } from "lucide-react";
// Using the v1-compat legacy entry — flat props (cols, rowHeight, draggableHandle)
// match the API older examples/docs use and keep this file readable.
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useCheckDashboardWidgetHealth } from "@/src/api/hooks/useWidgetHealth";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useChannel } from "@/src/api/hooks/useChannels";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import AddFromChannelSheet from "./AddFromChannelSheet";
import { EditPinDrawer } from "./EditPinDrawer";
import { DashboardTabs } from "./DashboardTabs";
import { CreateDashboardSheet } from "./CreateDashboardSheet";
import { EditDashboardDrawer } from "./EditDashboardDrawer";
import { ChannelDashboardBreadcrumb } from "./ChannelDashboardBreadcrumb";
import { EditModeGridGuides } from "./EditModeGridGuides";
import { ChannelDashboardMultiCanvas } from "./ChannelDashboardMultiCanvas";
import { KioskExitChip } from "./KioskExitChip";
import { WidgetUsefulnessToolbarButton } from "./WidgetUsefulnessReview";
import {
  channelIdFromSlug,
  channelSlug,
  isChannelSlug,
  isWorkspaceSpatialSlug,
  useDashboards,
} from "@/src/stores/dashboards";
import { resolveChrome, resolvePreset, type DashboardChrome, type GridPreset } from "@/src/lib/dashboardGrid";
import { getWidgetLayoutBounds } from "@/src/lib/widgetLayoutHints";
import { applyBuilderPinSuccessParams } from "@/src/lib/widgetDashboardBuilderState";
import { ChatSession, type ChatSource } from "@/src/components/chat/ChatSession";
import { useScratchReturnStore } from "@/src/stores/scratchReturn";
import { useWidgetStreamBroker } from "@/src/api/hooks/useWidgetStreamBroker";
import { buildRecentHref } from "@/src/lib/recentPages";

/** True when a pin currently lives on the chat sidebar rail canvas. Zone
 *  is stored explicitly on the pin; this is a convenience predicate so the
 *  dashboard breadcrumb can count rail pins without re-implementing the
 *  filter. */
export function isRailPin(pin: WidgetDashboardPin): boolean {
  return pin.zone === "rail";
}

const ResponsiveGridLayout = WidthProvider(Responsive);

/** Screen-width breakpoints. `lg` = the canonical multi-column layout the
 *  user designs at. We keep the threshold aligned with the mobile cutoff
 *  (768px) so that typical desktop viewports — including ones with sidebars
 *  and DevTools open — stay on the lg layout instead of falling back to the
 *  narrow single-column stack. Narrower breakpoints only kick in for truly
 *  mobile-sized content areas, which are also blocked from editing. */
const BREAKPOINTS = { lg: 768, md: 480, sm: 320, xs: 200, xxs: 0 } as const;
const GRID_MARGIN: [number, number] = [12, 12];

/** Adapt a WidgetDashboardPin row to the PinnedWidget shape the PinnedToolWidget
 *  renderer expects. Dashboard-scope calls use `widget_config` while channel-
 *  scope calls use `config`; the scope prop is what routes the store writes. */
function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    widget_contract: pin.widget_contract ?? null,
    config: pin.widget_config ?? {},
    widget_health: pin.widget_health ?? null,
  };
}

/** Default tile size for a pin with no saved grid_layout. Auto-packs into
 *  the first free slot via react-grid-layout's compactType, sized from the
 *  active preset's default tile dimensions. */
function defaultLayoutForIndex(index: number, preset: GridPreset): GridLayoutItem {
  const { w, h } = preset.defaultTile;
  return { x: (index % 2) * w, y: Math.floor(index / 2) * h, w, h };
}

function hasLayout(pin: WidgetDashboardPin): pin is WidgetDashboardPin & {
  grid_layout: GridLayoutItem;
} {
  const gl = pin.grid_layout;
  return !!gl && typeof gl === "object" && "w" in gl && "h" in gl;
}

export default function WidgetsDashboardPage() {
  // Two parameterized routes feed this page:
  //   /widgets/:slug                  — user dashboards (`default`, `home`, …)
  //   /widgets/channel/:channelId     — friendly alias for `channel:<uuid>`
  const { slug: slugParam, channelId: channelIdParam } = useParams<{
    slug: string;
    channelId: string;
  }>();
  const navigate = useNavigate();
  const slug = channelIdParam
    ? channelSlug(channelIdParam)
    : slugParam || "default";
  const channelScopedId = channelIdParam ?? channelIdFromSlug(slug);
  const isChannelScoped = isChannelSlug(slug);
  useEffect(() => {
    if (isWorkspaceSpatialSlug(slug)) navigate("/canvas", { replace: true });
  }, [navigate, slug]);
  // Host-side broker. On user dashboards (no channel) the broker is dormant —
  // streaming widgets there fall through to the direct /widget-actions/stream
  // path. Channel-scoped dashboards multiplex onto the ChannelChatSession's
  // existing SSE.
  useWidgetStreamBroker(channelScopedId ?? undefined);

  const { pins, isLoading, error, refetch: refetchPins } = useDashboardPins(slug);
  const checkDashboardHealth = useCheckDashboardWidgetHealth();
  const unpinWidget = useDashboardPinsStore((s) => s.unpinWidget);
  const updateEnvelope = useDashboardPinsStore((s) => s.updateEnvelope);
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  // `allDashboards` rather than `list` — channel dashboards are filtered out
  // of the tab-bar-friendly `list` slice, but we still need to read their
  // `grid_config` (preset + chrome flags) when rendering `/widgets/channel/<id>`.
  const { allDashboards } = useDashboards();
  const currentDashboard = allDashboards.find((d) => d.slug === slug);
  const preset = useMemo(
    () => resolvePreset(currentDashboard?.grid_config ?? null),
    [currentDashboard?.grid_config],
  );
  const chrome = useMemo(
    () => resolveChrome(currentDashboard?.grid_config ?? null),
    [currentDashboard?.grid_config],
  );
  // Only fetched when we're on a channel dashboard — gives the breadcrumb the
  // channel's real `name` without colliding with the main channel-chat route.
  const { data: channelRow } = useChannel(channelScopedId ?? undefined);
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    const name = isChannelScoped ? channelRow?.name : currentDashboard?.name;
    if (name) enrichRecentPage(buildRecentHref(loc.pathname, loc.search, loc.hash), name);
  }, [currentDashboard?.name, channelRow?.name, isChannelScoped, loc.pathname, loc.search, loc.hash, enrichRecentPage]);
  const railCount = useMemo(
    () => pins.filter((p) => isRailPin(p)).length,
    [pins],
  );
  const healthCounts = useMemo(() => {
    const counts = { healthy: 0, warning: 0, failing: 0, unknown: 0, unchecked: 0 };
    for (const pin of pins) {
      const status = pin.widget_health?.status;
      if (status === "healthy" || status === "warning" || status === "failing" || status === "unknown") counts[status] += 1;
      else counts.unchecked += 1;
    }
    return counts;
  }, [pins]);
  const dashboardHealthLabel = useMemo(() => {
    if (healthCounts.failing) return `${healthCounts.failing} failing`;
    if (healthCounts.warning) return `${healthCounts.warning} warning`;
    if (healthCounts.unknown) return `${healthCounts.unknown} unknown`;
    if (healthCounts.unchecked) return `${healthCounts.unchecked} unchecked`;
    return "all healthy";
  }, [healthCounts]);
  /** Panel-mode short-circuit: when the dashboard's `grid_config.layout_mode`
   *  is `'panel'` AND a panel pin exists, the right side becomes the panel
   *  pin and the left becomes a narrow RGL strip with rail-zone pins only.
   *  When the mode is set but no pin carries `is_main_panel` (e.g. the panel
   *  pin was just unpinned), we fall back to grid mode rather than render
   *  an empty main area — the server's delete cascade also flips the mode
   *  back, but the UI guards in case a stale dashboards.list is in flight. */
  const layoutMode = currentDashboard?.grid_config?.layout_mode ?? "grid";
  const panelPin = useMemo(
    () => pins.find((p) => p.is_main_panel) ?? null,
    [pins],
  );
  const inPanelMode = layoutMode === "panel" && panelPin !== null;
  /** While a widget is being dragged in edit mode, this tracks that a
   *  drag is in progress so `EditModeGridGuides` can show its column-index
   *  tick row. The channel dashboard now uses the multi-canvas editor, so
   *  chat-zone bands are gone — guide state is dragging/not-dragging. */
  const [dragging, setDragging] = useState(false);
  const gridRowCount = useMemo(() => {
    let max = 0;
    for (const p of pins) {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      if (!gl) continue;
      const bottom = (gl.y ?? 0) + (gl.h ?? 0);
      if (bottom > max) max = bottom;
    }
    return max;
  }, [pins]);

  const { kiosk, enterKiosk, exitKiosk, idle: kioskIdle } = useKioskMode();

  // `?dock=expanded` — the channel screen's Minimize button navigates here
  // with this flag so the dock opens already expanded (landing continuity).
  // Read once, scrub from the URL on mount so a later refresh doesn't re-open.
  const [searchParams, setSearchParams] = useSearchParams();
  const builderOpen = searchParams.get("builder") === "1";
  const builderTab = (searchParams.get("builder_tab") ?? "presets") as
    "presets" | "channel" | "recent" | "library" | "suites" | "build";
  const builderQuery = searchParams.get("builder_q") ?? "";
  const builderPresetId = searchParams.get("builder_preset") ?? "";
  const builderStep = (searchParams.get("builder_step") ?? "catalog") as
    "catalog" | "configure" | "preview";
  const requestedEditPinId = searchParams.get("edit_pin");
  const [initialDockExpanded] = useState(() => searchParams.get("dock") === "expanded");
  const scratchSessionIdFromQuery = searchParams.get("scratch_session_id");
  const scratchReturnSessionId = useScratchReturnStore(
    (s) => (channelScopedId ? s.byChannel[channelScopedId] ?? null : null),
  );
  const setScratchReturn = useScratchReturnStore((s) => s.setScratchReturn);
  const activeScratchSessionId = scratchSessionIdFromQuery ?? scratchReturnSessionId;
  const scratchChatHref = useMemo(() => {
    if (!channelScopedId || !activeScratchSessionId) return null;
    return `/channels/${channelScopedId}/session/${activeScratchSessionId}?scratch=true`;
  }, [activeScratchSessionId, channelScopedId]);
  useEffect(() => {
    if (channelScopedId && scratchSessionIdFromQuery) {
      setScratchReturn(channelScopedId, scratchSessionIdFromQuery);
    }
  }, [channelScopedId, scratchSessionIdFromQuery, setScratchReturn]);

  /** Edit mode is URL-driven via `?edit=true` so deep-links from the chat
   *  screen's "Add to dashboard" button (and page refreshes) land the user
   *  in edit mode without a separate client-state bootstrap. Toggling the
   *  "Edit layout" button rewrites the URL param. */
  const editMode = searchParams.get("edit") === "true";
  const setEditMode = useCallback(
    (next: boolean) => {
      setSearchParams(
        (prev) => {
          const patch = new URLSearchParams(prev);
          if (next) patch.set("edit", "true");
          else patch.delete("edit");
          return patch;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /** Current RGL breakpoint. We only persist layout edits at `lg` — smaller
   *  breakpoints are auto-reflowed by RGL and their coordinates should not
   *  become the canonical `grid_layout` (otherwise narrowing the window in
   *  edit mode corrupts the saved layout for everyone). */
  const [breakpoint, setBreakpoint] = useState<string>("lg");
  const [editingPinId, setEditingPinId] = useState<string | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [manageSlug, setManageSlug] = useState<string | null>(null);
  /** Last-added pin id — drives scroll-into-view + accent flash on the matching
   *  grid tile, cleared after ~1.4s. Set via `highlightPin` from Add sheet. */
  const [highlightPinId, setHighlightPinId] = useState<string | null>(null);
  // Track viewport width for mobile-only behavior — drag/resize on touch is
  // unusable, so the grid is read-only below the `sm` breakpoint even when
  // edit mode is toggled on (e.g. user hopped from desktop to phone).
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < 768 : false,
  );
  useEffect(() => {
    if (!requestedEditPinId) return;
    if (pins.some((p) => p.id === requestedEditPinId)) {
      setEditingPinId(requestedEditPinId);
    }
  }, [pins, requestedEditPinId]);
  const openEditPinDrawer = useCallback((pinId: string) => {
    setEditingPinId(pinId);
    setSearchParams(
      (prev) => {
        const patch = new URLSearchParams(prev);
        patch.set("edit_pin", pinId);
        return patch;
      },
      { replace: true },
    );
  }, [setSearchParams]);
  const closeEditPinDrawer = useCallback(() => {
    setEditingPinId(null);
    setSearchParams(
      (prev) => {
        const patch = new URLSearchParams(prev);
        patch.delete("edit_pin");
        return patch;
      },
      { replace: true },
    );
  }, [setSearchParams]);
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  // Edit gestures allowed at any non-mobile width. The grid guides and layout
  // commits are separately gated to `lg` (see render + onLayoutChange) so that
  // dragging at a narrower breakpoint doesn't corrupt the canonical layout.
  const layoutEditable = editMode && !isMobile;

  const highlightPin = useCallback((pinId: string) => {
    setHighlightPinId(pinId);
    // Scroll next frame so the new tile is in the DOM before we query for it.
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-pin-id="${pinId}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    window.setTimeout(() => setHighlightPinId((cur) => (cur === pinId ? null : cur)), 1400);
  }, []);

  const focusPin = useCallback((pinId: string) => {
    setHighlightPinId(pinId);
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-pin-id="${pinId}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    window.setTimeout(() => setHighlightPinId((cur) => (cur === pinId ? null : cur)), 1600);
  }, []);

  /** ChatSession dock — channel mode on channel-scoped widget dashboards.
   *  Mirrors the channel's main chat (same session, same store slot, same SSE).
   *  The dock's Maximize button navigates to `/channels/:channelId`. Not
   *  mounted on global dashboards yet — ephemeral mode there is still blocked
   *  by the streaming / React #185 bugs on the ephemeral path (Track §4.0a/c). */
  const chatDockNoop = useCallback(() => {}, []);

  useEffect(() => {
    const patch = new URLSearchParams(searchParams);
    let changed = false;
    if (patch.get("dock") === "expanded") {
      patch.delete("dock");
      changed = true;
    }
    // `?kiosk=true` — presentation-mode deep link. No visible button in the
    // top bar (removed to keep the toggle affordance unambiguous); kiosk is
    // now a URL-level opt-in the user or automations can hit directly.
    if (patch.get("kiosk") === "true") {
      patch.delete("kiosk");
      changed = true;
      enterKiosk();
    }
    // `?highlight=<pinId>` — chat "Add to dashboard" flow deep-links here
    // with this param so the newly pinned tile scrolls into view and flashes.
    // Consume once and strip; `highlightPin` does the pulse + scroll.
    const highlightId = patch.get("highlight");
    if (highlightId) {
      patch.delete("highlight");
      changed = true;
      highlightPin(highlightId);
    }
    if (changed) setSearchParams(patch, { replace: true });
    // Mount-only: subsequent ?dock / ?kiosk / ?highlight changes are ignored
    // unless the user manually edits the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const layouts = useMemo(() => {
    const lg: LayoutItem[] = pins.map((p, idx) => {
      const base = hasLayout(p) ? p.grid_layout : defaultLayoutForIndex(idx, preset);
      const bounds = getWidgetLayoutBounds(
        p.widget_presentation,
        p.zone ?? "grid",
        preset.cols.lg,
      );
      return {
        i: p.id,
        x: base.x,
        y: base.y,
        w: base.w,
        h: base.h,
        minW: Math.max(preset.minTile.w, bounds.minW),
        minH: Math.max(preset.minTile.h, bounds.minH),
        maxW: Math.min(preset.cols.lg, bounds.maxW),
        ...(bounds.maxH != null ? { maxH: bounds.maxH } : {}),
      };
    });

    // For narrower breakpoints, stack widgets single-column full-width
    // sorted by their lg (y, x) position. Prevents RGL from deriving weird
    // half-width/gapped arrangements when widget widths don't divide evenly
    // into the breakpoint's col count.
    const sortedForStack = [...pins]
      .map((p, idx) => ({
        p,
        base: hasLayout(p) ? p.grid_layout : defaultLayoutForIndex(idx, preset),
      }))
      .sort((a, b) => a.base.y - b.base.y || a.base.x - b.base.x);

    const stackFor = (cols: number): LayoutItem[] => {
      let y = 0;
      return sortedForStack.map(({ p, base }) => {
        const bounds = getWidgetLayoutBounds(
          p.widget_presentation,
          p.zone ?? "grid",
          cols,
        );
        const item: LayoutItem = {
          i: p.id,
          x: 0,
          y,
          w: cols,
          h: base.h,
          minH: Math.max(preset.minTile.h, bounds.minH),
          ...(bounds.maxH != null ? { maxH: bounds.maxH } : {}),
        };
        y += base.h;
        return item;
      });
    };

    return {
      lg,
      md: stackFor(preset.cols.md),
      sm: stackFor(preset.cols.sm),
      xs: stackFor(preset.cols.xs),
      xxs: stackFor(preset.cols.xxs),
    };
  }, [pins, preset]);

  // Debounce layout commits — drag/resize fires many `onLayoutChange` events.
  const pendingTimer = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    };
  }, []);

  const handleResetLayout = () => {
    // Pack every pin via defaultLayoutForIndex — same helper used for pins
    // with no grid_layout, so "Reset" is identical to "pretend every pin
    // was freshly pinned".
    const items = pins.map((p, idx) => ({
      id: p.id,
      ...defaultLayoutForIndex(idx, preset),
    }));
    void applyLayout(items)
      .then(() => setLayoutError(null))
      .catch((err) => {
        console.error("Failed to reset layout:", err);
        setLayoutError(err instanceof Error ? err.message : "Failed to reset layout");
      });
  };

  const scheduleCommit = (items: Layout) => {
    if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    pendingTimer.current = window.setTimeout(() => {
      void applyLayout(
        items.map((it) => ({ id: it.i, x: it.x, y: it.y, w: it.w, h: it.h })),
      )
        .then(() => setLayoutError(null))
        .catch((err) => {
          console.error("Failed to persist dashboard layout:", err);
          setLayoutError(
            err instanceof Error ? err.message : "Failed to save layout",
          );
        });
    }, 400);
  };

  const patchBuilderSearch = useCallback(
    (mutate: (params: URLSearchParams) => void, replace = false) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        mutate(next);
        return next;
      }, { replace });
    },
    [setSearchParams],
  );

  const openBuilder = useCallback(() => {
    patchBuilderSearch((params) => {
      params.set("builder", "1");
      if (!params.get("builder_tab")) params.set("builder_tab", "presets");
      if (!params.get("builder_step")) params.set("builder_step", "catalog");
    });
  }, [patchBuilderSearch]);

  const closeBuilder = useCallback(() => {
    patchBuilderSearch((params) => {
      params.delete("builder");
      params.delete("builder_tab");
      params.delete("builder_q");
      params.delete("builder_preset");
      params.delete("builder_step");
    });
  }, [patchBuilderSearch]);

  const handleBuilderPinCreated = useCallback((pinId: string) => {
    highlightPin(pinId);
    setSearchParams((prev) => applyBuilderPinSuccessParams(prev), { replace: true });
  }, [highlightPin, setSearchParams]);

  const actions = (
    <>
      {/* Edit layout — hidden on mobile where the grid is read-only anyway
          (the in-page banner explains why). */}
      {pins.length > 0 && !isMobile && (
        <button
          type="button"
          onClick={() => setEditMode(!editMode)}
          className={
            "inline-flex items-center gap-1.5 h-8 rounded-md border px-2.5 text-[12px] font-medium transition-colors " +
            (editMode
              ? "border-accent/60 bg-accent/10 text-accent"
              : "border-surface-border text-text-muted hover:bg-surface-overlay")
          }
          aria-pressed={editMode}
          aria-label={editMode ? "Finish editing layout" : "Rearrange widgets"}
          title={editMode ? "Finish editing" : "Rearrange widgets"}
        >
          {editMode ? <Check size={13} /> : <Move size={13} />}
          <span className="hidden md:inline">
            {editMode ? "Done" : "Edit layout"}
          </span>
        </button>
      )}
      {pins.length > 0 && isChannelScoped && channelScopedId && !isMobile && (
        <WidgetUsefulnessToolbarButton
          channelId={channelScopedId}
          checkingHealth={checkDashboardHealth.isPending}
          onCheckHealth={() => {
            checkDashboardHealth.mutate(
              { dashboardKey: slug, limit: Math.min(pins.length, 50), includeBrowser: true },
              { onSuccess: () => { void refetchPins(); } },
            );
          }}
          onFocusPin={focusPin}
          onEditPin={openEditPinDrawer}
          onEditLayout={() => setEditMode(true)}
          onOpenSettings={() => navigate(`/channels/${channelScopedId}/settings#dashboard`)}
        />
      )}
      {/* Kiosk button intentionally removed from the top bar. Kiosk mode is
          auto-entered via `?kiosk=true` in the URL — see the mount-time
          handler that consumes the flag. Removed because the button clutters
          the cross-view toggle affordance the user navigates with. */}
      {/* Split-button: primary "Add widget" on the left, caret on the right
          opening a small menu with secondary actions (currently Developer
          tools). The caret carries the `?from=<slug>` param so the dev panel
          back-button + Pin target picker seed to this dashboard — works the
          same on channel-scoped and global dashboards. */}
      <AddWidgetSplitButton
        onOpenSheet={openBuilder}
        devPanelHref={`/widgets/dev?from=${encodeURIComponent(slug)}`}
      />
      {isChannelScoped && channelScopedId && !isMobile && (
        <button
          type="button"
          onClick={() => navigate(`/widgets/channel/${channelScopedId}/settings`)}
          className="inline-flex items-center justify-center h-8 w-8 rounded-md border border-surface-border text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
          aria-label="Open channel settings"
          title="Open channel settings"
        >
          <Settings size={14} />
        </button>
      )}
      {/* Beam to spatial canvas — "warp out" of the channel and land on the
          workspace-scope canvas. Sits to the LEFT of the chat-switch button
          so the rightmost slot stays the chat-mirror affordance. Sparkles
          glyph leans into the transport vibe. Desktop-only for now (mobile
          canvas is P11). */}
      {!isMobile && (
        <button
          type="button"
          onClick={() => {
            if (channelScopedId) {
              try {
                sessionStorage.setItem(
                  "spatial.beamFromChannel",
                  JSON.stringify({ channelId: channelScopedId, ts: Date.now() }),
                );
              } catch {
                /* storage disabled — plain navigation still works */
              }
            }
            navigate("/");
          }}
          className="inline-flex items-center justify-center h-8 w-8 rounded-md border border-surface-border text-text-muted hover:bg-surface-overlay hover:text-accent transition-colors"
          aria-label="Beam to spatial canvas"
          title="Beam to spatial canvas"
        >
          <Sparkles size={14} />
        </button>
      )}
      {/* Open chat — ALWAYS rendered as the rightmost button so it occupies
          the mirror-image slot of the "Open dashboard" button in the channel
          header. Clicking either lands you back at the same screen x/y
          without the cursor moving. Icon is `MessageSquare` for direct
          "chat view" affordance. `?from=dock` cues the chat screen to play
          the reverse-of-collapse entrance animation. Sized to match the
          other dashboard-bar buttons (h-8) so the row reads as one set. */}
      {isChannelScoped && channelScopedId && !isMobile && (
        <button
          type="button"
          onClick={() => {
            // If the user got here from a scratch full-page, bring them
            // back to the same scratch context instead of the main chat.
            if (scratchChatHref) {
              navigate(`${scratchChatHref}${scratchChatHref.includes("?") ? "&" : "?"}from=dock${editMode ? "&edit=true" : ""}`);
            } else {
              navigate(`/channels/${channelScopedId}?from=dock${editMode ? "&edit=true" : ""}`);
            }
          }}
          className="inline-flex items-center justify-center h-8 w-8 rounded-md border border-surface-border text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
          aria-label="Switch to chat view"
          title="Switch to chat view"
        >
          <MessageSquare size={14} />
        </button>
      )}
    </>
  );

  return (
    <div
      className={
        "flex-1 flex flex-col bg-surface overflow-hidden "
        + (kiosk && kioskIdle ? "cursor-none" : "")
      }
    >
      {/* Chrome-bars suppressed in kiosk — the page should feel like a
          presentation surface, not a configurable admin tool. */}
      {!kiosk && (isChannelScoped && channelScopedId ? (
        <ChannelDashboardBreadcrumb
          channelId={channelScopedId}
          channelName={channelRow?.name}
          railCount={railCount}
          pinCount={pins.length}
          scratchSessionId={activeScratchSessionId}
          scratchHref={scratchChatHref}
          right={actions}
        />
      ) : (
        <DashboardTabs
          activeSlug={slug}
          onOpenCreate={() => setCreateOpen(true)}
          onOpenManage={() => setManageSlug(slug)}
          right={actions}
        />
      ))}

      {/* Floating exit chip only visible in kiosk. Consumers outside the
          dashboard route will never see this — the hook's `kiosk` flag is
          URL-scoped. */}
      {kiosk && <KioskExitChip idle={kioskIdle} onExit={exitKiosk} />}

      <div
        className={
          "relative flex-1 p-2 sm:p-4 md:p-3 "
          // Panel mode should keep overflow on the dashboard surface so
          // tall rail columns page-scroll with the rest of the view.
          + "overflow-auto "
          + (layoutEditable && !inPanelMode ? "pb-[40vh]" : "")
        }
      >
        {layoutError && (
          <div
            className="mx-auto mb-3 flex max-w-2xl items-center justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
            role="alert"
          >
            <span>Couldn't save layout — your changes reverted. {layoutError}</span>
            <button
              type="button"
              onClick={() => setLayoutError(null)}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-danger hover:bg-danger/20"
            >
              Dismiss
            </button>
          </div>
        )}
        {editMode && isMobile && pins.length > 0 && (
          <div
            className="mx-auto mb-3 flex max-w-2xl items-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-4 py-2 text-[12px] text-text-muted"
            role="status"
          >
            <Info size={13} className="shrink-0 text-text-dim" />
            <span>Layout editing is desktop-only. View pins as configured.</span>
          </div>
        )}
        {isLoading && <DashboardSkeleton />}
        {!isLoading && error && (
          <div className="mx-auto max-w-2xl rounded-lg border border-danger/40 bg-danger/10 p-4 text-center text-[13px] text-danger">
            Failed to load dashboard: {error}
          </div>
        )}
        {!isLoading && !error && pins.length === 0 && (
          <EmptyState onAddClick={openBuilder} />
        )}
        {!isLoading && !error && pins.length > 0 && inPanelMode && panelPin && (
          <PanelModeView
            pins={pins}
            panelPin={panelPin}
            preset={preset}
            chrome={chrome}
            highlightPinId={highlightPinId}
            layoutEditable={layoutEditable}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
            onEditPin={openEditPinDrawer}
          />
        )}
        {!isLoading && !error && pins.length > 0 && !inPanelMode && isChannelScoped && channelScopedId && !isMobile && (
          <ChannelDashboardMultiCanvas
            pins={pins}
            preset={preset}
            chrome={chrome}
            editMode={layoutEditable}
            onUnpin={handleUnpin}
            onEnvelopeUpdate={handleEnvelopeUpdate}
            onEditPin={openEditPinDrawer}
            channelId={channelScopedId}
          />
        )}
        {!isLoading && !error && pins.length > 0 && !inPanelMode && (isMobile || !isChannelScoped) && (
          <div className="relative">
            {layoutEditable && breakpoint === "lg" && (
              <EditModeGridGuides
                cols={preset.cols.lg}
                rowHeight={preset.rowHeight}
                rowGap={GRID_MARGIN[1]}
              />
            )}
            <ResponsiveGridLayout
              className={layoutEditable ? "rgl-edit-mode" : ""}
              layouts={layouts}
              breakpoints={BREAKPOINTS}
              cols={preset.cols}
              rowHeight={preset.rowHeight}
              margin={GRID_MARGIN}
              isDraggable={layoutEditable}
              isResizable={layoutEditable}
              draggableHandle=".widget-drag-handle"
              compactType="vertical"
              preventCollision={false}
              onDragStart={() => setDragging(true)}
              onDragStop={() => setDragging(false)}
              onBreakpointChange={(bp) => setBreakpoint(bp)}
              onLayoutChange={(current) => {
                if (layoutEditable && breakpoint === "lg") scheduleCommit(current);
              }}
            >
              {pins.map((p) => (
                <div
                  key={p.id}
                  data-pin-id={p.id}
                  className={"min-w-0 " + (highlightPinId === p.id ? "pin-flash" : "")}
                >
                  <PinnedToolWidget
                    widget={asPinnedWidget(p)}
                    scope={{ kind: "dashboard", channelId: channelScopedId ?? undefined }}
                    onUnpin={handleUnpin}
                    onEnvelopeUpdate={handleEnvelopeUpdate}
                    editMode={layoutEditable}
                    onEdit={() => openEditPinDrawer(p.id)}
                    borderless={chrome.borderless}
                    hoverScrollbars={chrome.hoverScrollbars}
                    hideTitles={chrome.hideTitles}
                  />
                </div>
              ))}
            </ResponsiveGridLayout>
          </div>
        )}
      </div>

      <AddFromChannelSheet
        open={builderOpen}
        onClose={closeBuilder}
        tab={builderTab}
        onTabChange={(tab) => {
          patchBuilderSearch((params) => {
            params.set("builder", "1");
            params.set("builder_tab", tab);
          });
        }}
        query={builderQuery}
        onQueryChange={(query) => {
          patchBuilderSearch((params) => {
            params.set("builder", "1");
            if (query.trim()) params.set("builder_q", query);
            else params.delete("builder_q");
          }, true);
        }}
        dashboardName={currentDashboard?.name ?? "dashboard"}
        onPinned={handleBuilderPinCreated}
        scopeChannelId={channelScopedId}
        selectedPresetId={builderPresetId}
        onSelectedPresetIdChange={(presetId) => {
          patchBuilderSearch((params) => {
            params.set("builder", "1");
            if (presetId) params.set("builder_preset", presetId);
            else params.delete("builder_preset");
          }, true);
        }}
        presetStep={builderStep}
        onPresetStepChange={(step) => {
          patchBuilderSearch((params) => {
            params.set("builder", "1");
            params.set("builder_step", step);
          }, true);
        }}
      />
      <EditPinDrawer
        pinId={editingPinId}
        onClose={closeEditPinDrawer}
        preset={preset}
      />
      <CreateDashboardSheet
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
      <EditDashboardDrawer
        slug={manageSlug}
        onClose={() => setManageSlug(null)}
        onResetLayout={pins.length > 0 && !isMobile ? handleResetLayout : undefined}
      />

      {/* ChatSession dock — channel-scoped dashboards only. Streams the same
          chat as the channel's full screen; maximize navigates there. Kiosk +
          mobile omit the dock to keep the presentation / small-screen layouts
          unchanged.
          When the user arrived here from a scratch full-page (scratchReturn
          store has an entry for this channel), the dock mounts against the
          scratch session instead so "back to chat" + the dock content stay
          consistent with the scratch context the user left. */}
      {isChannelScoped && channelScopedId && !kiosk && !isMobile && (
        <DashboardChatDock
          channelId={channelScopedId}
          botId={channelRow?.bot_id}
          channelName={channelRow?.name}
          chatMode={(channelRow?.config?.chat_mode ?? "default") as "default" | "terminal"}
          scratchSessionId={activeScratchSessionId}
          initiallyExpanded={initialDockExpanded}
        />
      )}
    </div>
  );
}

/** Chat dock mounted on channel-scoped widget dashboards. Normally mirrors
 *  the channel's main chat. When the user arrived from a scratch full-page
 *  (scratchReturn store has the channel's scratch session id), the dock
 *  swaps to render against the scratch session so "back to chat" flows and
 *  the dock content stay consistent with the scratch context. */
function DashboardChatDock({
  channelId,
  botId,
  channelName,
  chatMode,
  scratchSessionId,
  initiallyExpanded,
}: {
  channelId: string;
  botId: string | undefined;
  channelName: string | undefined;
  chatMode: "default" | "terminal";
  scratchSessionId: string | null;
  initiallyExpanded: boolean;
}) {
  const source: ChatSource = scratchSessionId
    ? {
        kind: "ephemeral",
        sessionStorageKey: `channel:${channelId}:scratch`,
        parentChannelId: channelId,
        defaultBotId: botId,
        context: {
          page_name: "channel_scratch",
          payload: { channel_id: channelId },
        },
        scratchBoundChannelId: channelId,
        pinnedSessionId: scratchSessionId,
      }
    : { kind: "channel", channelId };
  const title = scratchSessionId
    ? channelName
      ? `Session · #${channelName}`
      : "Session"
    : channelName
      ? `#${channelName}`
      : "Channel chat";
  return (
    <ChatSession
      source={source}
      shape="dock"
      open
      onClose={() => {}}
      title={title}
      initiallyExpanded={initiallyExpanded}
      dismissMode="collapse"
      chatMode={chatMode}
    />
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
          Open widget builder
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

interface PanelModeViewProps {
  pins: WidgetDashboardPin[];
  panelPin: WidgetDashboardPin;
  preset: GridPreset;
  chrome: DashboardChrome;
  highlightPinId: string | null;
  layoutEditable: boolean;
  onUnpin: (pinId: string) => void;
  onEnvelopeUpdate: (pinId: string, envelope: ToolResultEnvelope) => void;
  onEditPin: (pinId: string) => void;
}

/** Two-column layout used when `grid_config.layout_mode === 'panel'`.
 *
 *  - Left: rail-zone pins stacked vertically (no RGL — simple flex column;
 *    drag/resize is meaningful only against a multi-column grid, which we no
 *    longer have here. Reordering moves to the EditPinDrawer if needed
 *    later.)
 *  - Right: the single panel pin, filling the remaining area.
 *
 *  Mobile collapses to a single column with the panel above the rail strip
 *  so the headline content stays first-paint visible. */
function PanelModeView({
  pins,
  panelPin,
  chrome,
  highlightPinId,
  layoutEditable,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
}: PanelModeViewProps) {
  const railPins = useMemo(
    () => pins.filter((p) => p.id !== panelPin.id),
    [pins, panelPin.id],
  );
  return (
    <div className="flex flex-col-reverse gap-3 lg:flex-row">
      {railPins.length > 0 && (
        <div className="flex flex-col gap-3 lg:w-[320px] lg:shrink-0">
          {railPins.map((p) => (
            <div
              key={p.id}
              data-pin-id={p.id}
              className={
                "min-w-0 " + (highlightPinId === p.id ? "pin-flash" : "")
              }
            >
              <PinnedToolWidget
                widget={asPinnedWidget(p)}
                scope={{ kind: "dashboard" }}
                onUnpin={onUnpin}
                onEnvelopeUpdate={onEnvelopeUpdate}
                editMode={layoutEditable}
                onEdit={onEditPin}
                borderless={chrome.borderless}
                hoverScrollbars={chrome.hoverScrollbars}
                hideTitles={chrome.hideTitles}
                panelSurface
              />
            </div>
          ))}
        </div>
      )}
      <div
        key={panelPin.id}
        data-pin-id={panelPin.id}
        className={
          "flex min-h-[60vh] min-w-0 flex-1 flex-col "
          + (highlightPinId === panelPin.id ? "pin-flash" : "")
        }
      >
        <PinnedToolWidget
          widget={asPinnedWidget(panelPin)}
          scope={{ kind: "dashboard" }}
          onUnpin={onUnpin}
          onEnvelopeUpdate={onEnvelopeUpdate}
          editMode={layoutEditable}
          onEdit={onEditPin}
          borderless={chrome.borderless}
          hoverScrollbars={chrome.hoverScrollbars}
          hideTitles={chrome.hideTitles}
          panelSurface
        />
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-lg border border-surface-border bg-surface-raised"
        />
      ))}
    </div>
  );
}

/** Primary "Add widget" button with an attached caret that reveals secondary
 *  dashboard actions (currently just "Developer tools"). Keeps the top bar
 *  focused while still surfacing the dev panel from every dashboard — the
 *  `?from=<slug>` query param already ties the dev panel's back nav + Pin
 *  target picker to whichever dashboard opened it. */
function AddWidgetSplitButton({
  onOpenSheet,
  devPanelHref,
}: {
  onOpenSheet: () => void;
  devPanelHref: string;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDocDown = (e: MouseEvent) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div ref={wrapRef} className="relative inline-flex items-stretch">
      <button
        type="button"
        onClick={onOpenSheet}
        className="inline-flex items-center gap-1.5 h-8 rounded-l-md bg-accent pl-2.5 pr-2 text-[12px] font-medium text-white hover:opacity-90 transition-opacity"
        aria-label="Add widget"
        title="Add widget"
      >
        <Plus size={13} />
        <span className="hidden md:inline">Add widget</span>
      </button>
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        className="inline-flex items-center justify-center h-8 w-7 rounded-r-md bg-accent pl-0 pr-1 text-white hover:opacity-90 transition-opacity border-l border-white/20"
        aria-label="More widget actions"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        title="More actions"
      >
        <ChevronDown size={13} />
      </button>
      {menuOpen && (
        <div
          role="menu"
          className="absolute right-0 top-full z-40 mt-1.5 min-w-[200px] overflow-hidden rounded-md bg-surface-raised shadow-xl"
        >
          <Link
            role="menuitem"
            to={devPanelHref}
            onClick={() => setMenuOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-[12px] text-text hover:bg-surface-overlay transition-colors"
          >
            <Wrench size={13} className="text-text-muted" />
            <div className="flex-1 min-w-0">
              <div className="font-medium">Developer tools</div>
              <div className="text-[11px] text-text-dim">
                Inspect library widgets, presets, and tool renderers for this dashboard
              </div>
            </div>
          </Link>
        </div>
      )}
    </div>
  );
}
