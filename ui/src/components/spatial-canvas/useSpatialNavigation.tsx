import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Footprints,
  Home,
  LayoutDashboard,
  Link2,
  Locate,
  Map as MapIcon,
  Maximize2,
  Move,
  Radar,
  Sparkles,
  Target,
  Users as UsersIcon,
} from "lucide-react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { usePaletteActions } from "../../stores/paletteActions";
import { usePaletteOverrides } from "../../stores/paletteOverrides";
import { useUIStore } from "../../stores/ui";
import { buildChannelSurfaceRoute, getChannelLastSurface } from "../../stores/channelLastSurface";
import type { UnreadStateResponse } from "../../api/hooks/useUnread";
import { resolveChannelEntryHref } from "../../lib/channelNavigation";
import { SPATIAL_HANDOFF_KEY } from "../../lib/spatialHandoff";
import { definitionOrbit } from "./spatialDefinitionsOrbit";
import {
  DEFAULT_CAMERA,
  DIVE_DWELL_MS,
  DIVE_SCALE_THRESHOLD,
  DIVE_VIEWPORT_MARGIN,
  MAX_SCALE,
  WELL_R_MAX,
  WELL_Y_SQUASH,
} from "./spatialGeometry";
import { CHANNEL_CLUSTER_EXIT_SCALE } from "./spatialClustering";

const DIVE_MS = 300;
const CLUSTER_FOCUS_MS = 520;
const OBJECT_REVEAL_MS = 460;

type UseSpatialNavigationArgs = Record<string, any>;

const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

export function spatialVisibleCenterX(viewportWidth: number, starboardPanelLeft?: number | null, viewportLeft = 0): number {
  if (
    typeof starboardPanelLeft === "number"
    && Number.isFinite(starboardPanelLeft)
    && starboardPanelLeft > viewportLeft
    && starboardPanelLeft < viewportLeft + viewportWidth
  ) {
    return Math.max(140, (starboardPanelLeft - viewportLeft) / 2);
  }
  return viewportWidth / 2;
}

export function useSpatialNavigation(args: UseSpatialNavigationArgs) {
  const {
    viewportRectRef,
    nodes,
    lensEngaged,
    setLensEngaged,
    triggerLensSettle,
    scheduleCamera,
    navigate,
    onAfterDive,
    taskDefinitions,
    wellPos,
    cameraRef,
    nodesRef,
    initialFlyToChannelId,
    initialFlyToNodeId,
    setSelectedSpatialObject,
    setContextMenu,
    interactionMode,
    setInteractionMode,
    cycleDensityIntensity,
    cycleTrailsMode,
    densityIntensity,
    trailsMode,
    connectionsEnabled,
    setConnectionsEnabled,
    minimapVisible,
    setMinimapVisible,
    landmarkBeaconsVisible,
    setLandmarkBeaconsVisible,
    attentionSignalsVisible,
    setAttentionSignalsVisible,
    botsVisible,
    setBotsVisible,
    camera,
    channelsById,
    diving,
    draggingNodeId,
    mountedAtRef,
    memoryObsPos,
    setDiving,
    fitAllNodes,
    openStarboardAttention,
    setStarboardOpen,
    setStarboardStation,
  } = args;
  const recentPages = useUIStore((s) => s.recentPages);
  const queryClient = useQueryClient();
  const cameraTweenRaf = useRef(0);
  const cancelCameraTween = useCallback(() => {
    if (cameraTweenRaf.current) {
      window.cancelAnimationFrame(cameraTweenRaf.current);
      cameraTweenRaf.current = 0;
    }
  }, []);
  const animateCameraTo = useCallback(
    (target: { x: number; y: number; scale: number }, durationMs = CLUSTER_FOCUS_MS) => {
      cancelCameraTween();
      const start = { ...cameraRef.current };
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - t0) / Math.max(16, durationMs));
        const k = easeInOut(t);
        const next = {
          x: start.x + (target.x - start.x) * k,
          y: start.y + (target.y - start.y) * k,
          scale: start.scale + (target.scale - start.scale) * k,
        };
        scheduleCamera(next, t === 1 ? "immediate" : "idle");
        if (t < 1) cameraTweenRaf.current = window.requestAnimationFrame(tick);
        else cameraTweenRaf.current = 0;
      };
      cameraTweenRaf.current = window.requestAnimationFrame(tick);
    },
    [cameraRef, cancelCameraTween, scheduleCamera],
  );
  useEffect(() => cancelCameraTween, [cancelCameraTween]);
  const diveToChannel = useCallback(
    (channelId: string, world: { x: number; y: number; w: number; h: number }) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = Math.max(rect.width / world.w, rect.height / world.h);
      const targetX = rect.width / 2 - (world.x + world.w / 2) * targetScale;
      const targetY = rect.height / 2 - (world.y + world.h / 2) * targetScale;
      // Drop the lens before diving so the per-tile fisheye transform doesn't
      // fight the dive animation on the target tile.
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      setDiving(true);
      requestAnimationFrame(() => {
        scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      });
      // Animate-THEN-navigate: route change happens after the transition
      // completes. onAfterDive (overlay close) runs a tick later so the new
      // route paints before the overlay disappears.
      // Surface routing: dive to whichever surface the user last opened for
      // this channel (chat OR `/widgets/channel/:id` dashboard). First-ever
      // dive falls back to chat. The tracker in AppShell records the
      // surface on every channel-route visit.
      const surface = getChannelLastSurface(channelId) ?? "chat";
      const unreadState = queryClient.getQueryData<UnreadStateResponse>(["unread-state"]);
      const target = surface === "chat"
        ? resolveChannelEntryHref({
            channelId,
            recentPages,
            unreadStates: unreadState?.states,
          })
        : buildChannelSurfaceRoute(channelId, surface);
      window.setTimeout(() => {
        navigate(target);
        if (onAfterDive) window.setTimeout(onAfterDive, 16);
      }, DIVE_MS);
    },
    [navigate, onAfterDive, lensEngaged, triggerLensSettle, scheduleCamera, queryClient, recentPages],
  );

  /**
   * diveToTaskDefinition — mirrors `diveToChannel` for an outer-ring
   * task definition tile. Camera flies toward the orbit point; route
   * swaps to the canvas editor for that task with a sidebar-collapsed
   * layout.
   */
  const diveToTaskDefinition = useCallback(
    (taskId: string) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const def = taskDefinitions.find((t: any) => t.id === taskId);
      if (!def) return;
      const idx = taskDefinitions.findIndex((t: any) => t.id === taskId);
      const orbit = definitionOrbit(taskId, taskDefinitions.length, idx, wellPos);
      // Aim the camera so the orbit point sits in the viewport center
      // at near-max zoom; the editor pop-in covers the rest visually.
      const targetScale = MAX_SCALE * 0.95;
      const targetX = rect.width / 2 - orbit.x * targetScale;
      const targetY = rect.height / 2 - orbit.y * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      setDiving(true);
      requestAnimationFrame(() => {
        scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
      });
      window.setTimeout(() => {
        navigate(`/admin/automations?canvas=1&edit=${encodeURIComponent(taskId)}`);
        if (onAfterDive) window.setTimeout(onAfterDive, 16);
      }, DIVE_MS);
    },
    [taskDefinitions, navigate, onAfterDive, lensEngaged, triggerLensSettle, scheduleCamera],
  );

  // Push-through dive — sustained zoom into a channel tile triggers the same
  // dive flow as double-click. Trigger condition (re-evaluated on every
  // camera commit): scale >= DIVE_SCALE_THRESHOLD AND viewport center in
  // the bounding box of exactly one channel tile (with margin). Dwell timer
  // gives the user 450ms to back off — vignette + crosshair tighten as the
  // timer progresses.
  const [diveCandidate, setDiveCandidate] = useState<{
    nodeId: string;
    channelId: string;
    label: string;
    world: { x: number; y: number; w: number; h: number };
  } | null>(null);

  useEffect(() => {
    // Mount-time cooldown — defends against any flow that lands the canvas
    // at high zoom over a tile right after mount (most often: beam-me-up
    // back from a channel route, where the camera state loaded from
    // localStorage might re-trigger a dive into the channel we just left).
    if (Date.now() - mountedAtRef.current < 1500) {
      setDiveCandidate(null);
      return;
    }
    if (diving || draggingNodeId) {
      setDiveCandidate(null);
      return;
    }
    if (camera.scale < DIVE_SCALE_THRESHOLD) {
      setDiveCandidate(null);
      return;
    }
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    // Viewport center → world coords.
    const cx = (rect.width / 2 - camera.x) / camera.scale;
    const cy = (rect.height / 2 - camera.y) / camera.scale;
    let found: typeof diveCandidate = null;
    for (const n of nodes ?? []) {
      if (!n.channel_id) continue;
      const padX = n.world_w * DIVE_VIEWPORT_MARGIN;
      const padY = n.world_h * DIVE_VIEWPORT_MARGIN;
      if (
        cx >= n.world_x - padX
        && cx <= n.world_x + n.world_w + padX
        && cy >= n.world_y - padY
        && cy <= n.world_y + n.world_h + padY
      ) {
        const channel = channelsById.get(n.channel_id);
        const label = channel ? channel.display_name || channel.name : "channel";
        found = {
          nodeId: n.id,
          channelId: n.channel_id,
          label,
          world: { x: n.world_x, y: n.world_y, w: n.world_w, h: n.world_h },
        };
        break;
      }
    }
    setDiveCandidate((curr) => {
      if (!found) return null;
      if (curr && curr.nodeId === found.nodeId) return curr;
      return found;
    });
  }, [camera, nodes, channelsById, diving, draggingNodeId]);

  // Dwell timer + smooth progress tween. Restarts whenever the candidate
  // changes (or first appears). Cancels cleanly on candidate clear.
  useEffect(() => {
    if (!diveCandidate) return;
    const id = window.setTimeout(() => {
      diveToChannel(diveCandidate.channelId, diveCandidate.world);
    }, DIVE_DWELL_MS);
    return () => window.clearTimeout(id);
  }, [diveCandidate, diveToChannel]);

  // Pan + scale the camera to a single channel tile (Cmd+K override target).
  // Same scale-derivation pattern as `diveToChannel` but capped at scale 1.0
  // so the user lands at the channel's "preview" zoom — readable but not
  // fully zoomed-in (which would overshoot into a single-tile-fills-screen
  // state that's hard to navigate away from).
  const flyToChannel = useCallback(
    (channelId: string): boolean => {
      const node = (nodes ?? []).find((n: any) => n.channel_id === channelId);
      const rect = viewportRectRef.current;
      if (!node || !rect.width || !rect.height) return false;
      const targetScale = Math.min(
        1.0,
        Math.max(rect.width / (node.world_w * 4), rect.height / (node.world_h * 4)),
      );
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      const targetX = rect.width / 2 - cx * targetScale;
      const targetY = rect.height / 2 - cy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      animateCameraTo({ x: targetX, y: targetY, scale: targetScale }, OBJECT_REVEAL_MS);
      return true;
    },
    [animateCameraTo, nodes, lensEngaged, triggerLensSettle],
  );

  // Pan + scale the camera to a spatial node by id. Used for the widget-pick
  // palette override and the contributed widget items.
  const flyToNodeById = useCallback(
    (nodeId: string): boolean => {
      const node = (nodes ?? []).find((n: any) => n.id === nodeId);
      const rect = viewportRectRef.current;
      if (!node || !rect.width || !rect.height) return false;
      const targetScale = Math.min(
        1.0,
        Math.max(rect.width / (node.world_w * 4), rect.height / (node.world_h * 4)),
      );
      const cx = node.world_x + node.world_w / 2;
      const cy = node.world_y + node.world_h / 2;
      const targetX = rect.width / 2 - cx * targetScale;
      const targetY = rect.height / 2 - cy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      animateCameraTo({ x: targetX, y: targetY, scale: targetScale }, OBJECT_REVEAL_MS);
      return true;
    },
    [animateCameraTo, nodes, lensEngaged, triggerLensSettle],
  );

  // Register the channel-pick + widget-pick overrides + the active surface
  // on the palette. While the canvas is mounted, ⌘K renders in canvas mode
  // (Canvas + On the map groups at top); Enter opens routes while the
  // secondary action can fly the camera to mapped channels/widgets.
  useEffect(() => {
    const o = usePaletteOverrides.getState();
    o.setChannelPick(flyToChannel);
    o.setWidgetPick(flyToNodeById);
    o.setSurface("canvas");
    return () => {
      const c = usePaletteOverrides.getState();
      c.setChannelPick(null);
      c.setWidgetPick(null);
      c.setSurface(null);
    };
  }, [flyToChannel, flyToNodeById]);

  // Publish channel ids that have a spatial node so the palette can re-badge
  // them into the "On the map" group when the canvas is the active surface.
  // Membership changes infrequently, so we cheap-derive via .map + Set on
  // every nodes update.
  useEffect(() => {
    const ids = new Set<string>();
    for (const n of nodes ?? []) {
      if (n.channel_id) ids.add(n.channel_id);
    }
    usePaletteOverrides.getState().setOnMapChannelIds(ids);
    return () => {
      usePaletteOverrides.getState().setOnMapChannelIds(new Set());
    };
  }, [nodes]);

  // Contribute one palette item per pinned widget node so widgets are
  // searchable in ⌘K. Selecting a widget flies the camera to its tile
  // (handled by the widgetPick override). Items have no `href`, so the
  // secondary "Open page" affordance is naturally hidden — widgets have no
  // standalone route.
  useEffect(() => {
    const items = (nodes ?? [])
      .filter((n: any) => n.widget_pin_id && n.pin)
      .map((n: any) => ({
        id: `widget-${n.id}`,
        label: `Widget: ${n.pin?.panel_title || n.pin?.display_label || n.pin?.tool_name || "Untitled"}`,
        category: "On the map",
        icon: LayoutDashboard,
        routeKind: "spatial-widget",
        hint: n.pin?.tool_name || undefined,
      }));
    usePaletteOverrides.getState().setExtraItems(items);
    return () => {
      usePaletteOverrides.getState().setExtraItems([]);
    };
  }, [nodes]);

  // Contextual-camera-on-open. When the overlay mounts the canvas with a
  // target channel id (because the user opened it from /channels/:id), fly
  // there as soon as the node list arrives instead of restoring the
  // last-saved camera. One-shot per mount — toggling the overlay closed
  // and back open re-mounts the canvas, which re-runs this effect against
  // the new route.
  const firedInitialFlyRef = useRef(false);
  useEffect(() => {
    if (!initialFlyToChannelId) return;
    if (firedInitialFlyRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const found = nodes.find((n: any) => n.channel_id === initialFlyToChannelId);
    if (!found) return;
    if (flyToChannel(initialFlyToChannelId)) {
      firedInitialFlyRef.current = true;
    }
  }, [initialFlyToChannelId, nodes, flyToChannel]);

  const firedInitialNodeFlyRef = useRef(false);
  useEffect(() => {
    if (!initialFlyToNodeId) return;
    if (firedInitialNodeFlyRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const found = nodes.find((n: any) => n.id === initialFlyToNodeId);
    if (!found) return;
    if (flyToNodeById(initialFlyToNodeId)) {
      firedInitialNodeFlyRef.current = true;
      if (found.bot_id) {
        setSelectedSpatialObject({ kind: "bot", nodeId: found.id });
      } else if (found.channel_id) {
        setSelectedSpatialObject({ kind: "channel", nodeId: found.id });
      } else if (found.widget_pin_id) {
        setSelectedSpatialObject({ kind: "widget", nodeId: found.id });
      }
    }
  }, [initialFlyToNodeId, nodes, flyToNodeById]);

  // Pan + scale the camera so the Now Well fills the viewport with a small
  // padding margin. Uses the same scale-derivation trick as `diveToChannel`
  // but without the route change at the end.
  // Center the camera on an arbitrary world point. Used by the minimap
  // click-to-fly handler. Caps scale at 1.0 so a click on a distant region
  // doesn't slam the user into max-zoom over empty space; preserves any
  // scale below 1.0 the user has set so they don't lose context.
  const flyToWorldPoint = useCallback(
    (wx: number, wy: number) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = Math.min(1.0, cameraRef.current.scale);
      const targetX = rect.width / 2 - wx * targetScale;
      const targetY = rect.height / 2 - wy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      animateCameraTo({ x: targetX, y: targetY, scale: targetScale }, OBJECT_REVEAL_MS);
    },
    [animateCameraTo, lensEngaged, triggerLensSettle],
  );

  const flyToStarboardObject = useCallback(
    (wx: number, wy: number) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const currentScale = cameraRef.current.scale;
      const targetScale = Math.min(MAX_SCALE, Math.max(currentScale, 0.42));
      const panelRect = typeof document === "undefined" ? null : document.querySelector("[data-starboard-panel='true']")?.getBoundingClientRect() ?? null;
      const targetCenterX = spatialVisibleCenterX(rect.width, panelRect?.left ?? null, rect.left);
      const targetX = targetCenterX - wx * targetScale;
      const targetY = rect.height / 2 - wy * targetScale;
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      animateCameraTo({ x: targetX, y: targetY, scale: targetScale }, OBJECT_REVEAL_MS);
    },
    [animateCameraTo, lensEngaged, triggerLensSettle],
  );

  const focusNode = useCallback(
    (node: SpatialNode) => {
      flyToStarboardObject(node.world_x + node.world_w / 2, node.world_y + node.world_h / 2);
    },
    [flyToStarboardObject],
  );

  const selectNode = useCallback(
    (kind: "channel" | "bot" | "widget", node: SpatialNode, focus = false) => {
      setSelectedSpatialObject({ kind, nodeId: node.id });
      setContextMenu(null);
      setStarboardStation?.("objects");
      setStarboardOpen?.(true);
      if (focus) focusNode(node);
    },
    [focusNode, setStarboardOpen, setStarboardStation],
  );

  const selectLandmark = useCallback(
    (id: "now_well" | "memory_observatory" | "attention_hub" | "daily_health", x: number, y: number, focus = false) => {
      setSelectedSpatialObject({ kind: "landmark", id });
      setContextMenu(null);
      setStarboardStation?.("objects");
      setStarboardOpen?.(true);
      if (focus) flyToStarboardObject(x, y);
    },
    [flyToStarboardObject, setStarboardOpen, setStarboardStation],
  );

  const flyToWell = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const wellWidth = WELL_R_MAX * 2.4;
    const wellHeight = WELL_R_MAX * WELL_Y_SQUASH * 2.4;
    const targetScale = Math.min(
      rect.width / wellWidth,
      rect.height / wellHeight,
    );
    const targetX = rect.width / 2 - wellPos.x * targetScale;
    const targetY = rect.height / 2 - wellPos.y * targetScale;
    scheduleCamera({ x: targetX, y: targetY, scale: targetScale }, "immediate");
  }, [scheduleCamera, wellPos.x, wellPos.y]);

  const flyToMemoryObservatory = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const targetScale = Math.min(0.9, Math.max(0.55, cameraRef.current.scale));
    scheduleCamera({
      x: rect.width / 2 - memoryObsPos.x * targetScale,
      y: rect.height / 2 - memoryObsPos.y * targetScale,
      scale: targetScale,
    }, "immediate");
  }, [scheduleCamera, memoryObsPos.x, memoryObsPos.y]);


  // Register canvas commands as palette items. They appear under the
  // "Canvas" group at the top of ⌘K while the canvas is mounted, replacing
  // the previous SVG radial wheel. Handler bindings mirror the radial action
  // bundle the deleted menu used. Lives below `flyToWell` so the action
  // closure can reference it.
  useEffect(() => {
    return usePaletteActions.getState().register("spatial-canvas", [
      {
        id: "canvas-recenter",
        label: "Canvas: Recenter",
        category: "Canvas",
        icon: Home,
        onSelect: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
      },
      {
        id: "canvas-fit-all",
        label: "Canvas: Fit all",
        category: "Canvas",
        icon: Maximize2,
        onSelect: () => fitAllNodes(),
      },
      {
        id: "canvas-fly-to-now",
        label: "Canvas: Fly to Now",
        category: "Canvas",
        icon: Target,
        onSelect: () => flyToWell(),
      },
      {
        id: "canvas-fly-to-memory",
        label: "Canvas: Fly to Memory Observatory",
        category: "Canvas",
        icon: Brain,
        onSelect: () => flyToMemoryObservatory(),
      },
      {
        id: "canvas-open-attention-hub",
        label: "Canvas: Open Attention Hub",
        category: "Canvas",
        icon: Radar,
        onSelect: () => openStarboardAttention(),
      },
      {
        id: "canvas-toggle-arrange",
        label: interactionMode === "arrange" ? "Canvas: Browse mode" : "Canvas: Arrange mode",
        hint: interactionMode,
        category: "Canvas",
        icon: Move,
        onSelect: () => setInteractionMode((mode: any) => (mode === "arrange" ? "browse" : "arrange")),
      },
      {
        id: "canvas-cycle-activity",
        label: "Canvas: Cycle activity",
        hint: densityIntensity === "off" ? "off" : densityIntensity,
        category: "Canvas",
        icon: Sparkles,
        onSelect: () => cycleDensityIntensity(),
      },
      {
        id: "canvas-cycle-trails",
        label: "Canvas: Cycle trails",
        hint: trailsMode,
        category: "Canvas",
        icon: Footprints,
        onSelect: () => cycleTrailsMode(),
      },
      {
        id: "canvas-toggle-lines",
        label: connectionsEnabled ? "Canvas: Hide connection lines" : "Canvas: Show connection lines",
        category: "Canvas",
        icon: Link2,
        onSelect: () => setConnectionsEnabled((v: any) => !v),
      },
      {
        id: "canvas-toggle-map",
        label: minimapVisible ? "Canvas: Hide minimap" : "Canvas: Show minimap",
        category: "Canvas",
        icon: MapIcon,
        onSelect: () => setMinimapVisible((v: any) => !v),
      },
      {
        id: "canvas-toggle-landmark-beacons",
        label: landmarkBeaconsVisible ? "Canvas: Hide edge beacons" : "Canvas: Show edge beacons",
        category: "Canvas",
        icon: Locate,
        onSelect: () => setLandmarkBeaconsVisible((v: any) => !v),
      },
      {
        id: "canvas-toggle-attention-signals",
        label: attentionSignalsVisible ? "Canvas: Hide attention signals" : "Canvas: Show attention signals",
        category: "Canvas",
        icon: Radar,
        onSelect: () => setAttentionSignalsVisible((v: any) => !v),
      },
      {
        id: "canvas-toggle-bots",
        label: botsVisible ? "Canvas: Hide bots" : "Canvas: Show bots",
        category: "Canvas",
        icon: UsersIcon,
        onSelect: () => setBotsVisible((v: any) => !v),
      },
    ]);
  }, [
    scheduleCamera,
    fitAllNodes,
    flyToWell,
    flyToMemoryObservatory,
    openStarboardAttention,
    interactionMode,
    cycleDensityIntensity,
    cycleTrailsMode,
    densityIntensity,
    trailsMode,
    connectionsEnabled,
    minimapVisible,
    landmarkBeaconsVisible,
    attentionSignalsVisible,
    botsVisible,
  ]);

  // Expose canvas actions on window for screenshot/video recording. The
  // radial menu is the in-product surface; recordings need a stable hook
  // that doesn't depend on portal-mount timing or keyboard focus state.
  // `panTo` interpolates with requestAnimationFrame so video pans look
  // cinematic instead of jumpy — the inline-style world transform has no
  // CSS transition, so the tween has to live here.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const flyToWorldPanned = (wx: number, wy: number, scale?: number, durationMs = 1200) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const targetScale = typeof scale === "number" ? scale : cameraRef.current.scale;
      animateCameraTo({ x: rect.width / 2 - wx * targetScale, y: rect.height / 2 - wy * targetScale, scale: targetScale }, durationMs);
    };
    (window as unknown as { __spindrelSpatial?: object }).__spindrelSpatial = {
      recenter: () => scheduleCamera(DEFAULT_CAMERA, "immediate"),
      flyToNow: () => flyToWell(),
      flyToMemory: () => flyToMemoryObservatory(),
      fitAll: () => fitAllNodes(),
      flyToChannel: (channelId: string) => flyToChannel(channelId),
      setCamera: (next: { x: number; y: number; scale: number }) => scheduleCamera(next, "immediate"),
      panTo: animateCameraTo,
      flyToPoint: flyToWorldPanned,
      cancelPan: cancelCameraTween,
      getCamera: () => ({ ...cameraRef.current }),
      getNodes: () =>
        (nodesRef.current ?? []).map((n: any) => ({
          id: n.id,
          channel_id: n.channel_id,
          bot_id: n.bot_id,
          widget_pin_id: n.widget_pin_id,
          world_x: n.world_x,
          world_y: n.world_y,
          world_w: n.world_w,
          world_h: n.world_h,
        })),
    };
    return cancelCameraTween;
  }, [scheduleCamera, flyToWell, flyToMemoryObservatory, fitAllNodes, flyToChannel, animateCameraTo, cancelCameraTween]);

  const flyToWorldBounds = useCallback(
    (bounds: { x: number; y: number; w: number; h: number }, minScale = CHANNEL_CLUSTER_EXIT_SCALE + 0.06, maxScale = 0.62) => {
      let rect = viewportRectRef.current;
      if (!rect.width || !rect.height) {
        const el = document.querySelector('[data-spatial-canvas="true"]');
        const domRect = el?.getBoundingClientRect();
        if (domRect?.width && domRect.height) {
          rect = {
            left: domRect.left,
            top: domRect.top,
            width: domRect.width,
            height: domRect.height,
          };
          viewportRectRef.current = rect;
        }
      }
      if (!rect.width || !rect.height) return;
      const margin = 0.18;
      const targetScale = Math.max(
        minScale,
        Math.min(
          maxScale,
          Math.min(
            rect.width / Math.max(1, bounds.w * (1 + margin * 2)),
            rect.height / Math.max(1, bounds.h * (1 + margin * 2)),
          ),
        ),
      );
      const cx = bounds.x + bounds.w / 2;
      const cy = bounds.y + bounds.h / 2;
      animateCameraTo({
        scale: targetScale,
        x: rect.width / 2 - cx * targetScale,
        y: rect.height / 2 - cy * targetScale,
      });
    },
    [animateCameraTo],
  );



  return {
    diveToChannel,
    diveToTaskDefinition,
    diveCandidate,
    flyToChannel,
    flyToNodeById,
    flyToWorldPoint,
    flyToStarboardObject,
    focusNode,
    selectNode,
    selectLandmark,
    flyToWell,
    flyToMemoryObservatory,
    flyToWorldBounds,
  };
}
