import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type { StepDef, TaskLayout } from "@/src/api/hooks/useTasks";
import {
  type Camera,
  DEFAULT_CAMERA,
  MAX_SCALE,
  MIN_SCALE,
  clampCamera,
} from "../../../spatial-canvas/spatialGeometry";
import { StepNode } from "./StepNode";
import { EdgeLayer, edgeKey } from "./EdgeLayer";
import { buildEdges, staleWhenStepRefs, type EdgeDescriptor } from "./edges";
import { NODE_W, NODE_H, setNodePosition, ensurePositions } from "./layout";

interface CanvasProps {
  steps: StepDef[];
  layout: TaskLayout;
  selectedStepId: string | null;
  selectedEdgeKey: string | null;
  onLayoutChange: (next: TaskLayout) => void;
  onSelectStep: (id: string | null) => void;
  onSelectEdge: (e: EdgeDescriptor | null) => void;
}

interface DragState {
  nodeId: string;
  pointerId: number;
  grabDx: number;
  grabDy: number;
  currentX: number;
  currentY: number;
}

interface PanState {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startCameraX: number;
  startCameraY: number;
}

export function Canvas({
  steps,
  layout,
  selectedStepId,
  selectedEdgeKey,
  onLayoutChange,
  onSelectStep,
  onSelectEdge,
}: CanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [camera, setCamera] = useState<Camera>(layout.camera ?? DEFAULT_CAMERA);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;

  const [drag, setDrag] = useState<DragState | null>(null);
  const [pan, setPan] = useState<PanState | null>(null);

  // Auto-place steps that don't have positions yet, and prune stale ones.
  // This reconciles into form state on first render and after step edits.
  useEffect(() => {
    const ensured = ensurePositions(steps, layout);
    if (ensured !== layout) onLayoutChange(ensured);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps, layout]);

  // Sync camera back into form layout (debounced via effect).
  useEffect(() => {
    if (
      layout.camera?.x === camera.x
      && layout.camera?.y === camera.y
      && layout.camera?.scale === camera.scale
    ) return;
    onLayoutChange({ ...layout, camera });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera]);

  const positions = useMemo(() => layout.nodes ?? {}, [layout.nodes]);
  const edges = useMemo(() => buildEdges(steps), [steps]);
  const staleIds = useMemo(() => staleWhenStepRefs(steps), [steps]);

  const bounds = useMemo(() => {
    let minX = 0, minY = 0, maxX = NODE_W, maxY = NODE_H;
    for (const id of Object.keys(positions)) {
      const p = positions[id];
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + NODE_H);
    }
    return { minX, minY, maxX, maxY };
  }, [positions]);

  // ---------------------------------------------------------------------------
  // Pointer-to-world conversion (manual pattern from SpatialCanvas Bot drag).
  // ---------------------------------------------------------------------------
  const pointerToWorld = useCallback((clientX: number, clientY: number) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const cam = cameraRef.current;
    return {
      x: (clientX - rect.left) / cam.scale + cam.x,
      y: (clientY - rect.top) / cam.scale + cam.y,
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Node drag — manual pointer-to-world (no zoom drift).
  // ---------------------------------------------------------------------------
  const handleNodePointerDown = useCallback(
    (nodeId: string, e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      const pos = positions[nodeId];
      if (!pos) return;
      const world = pointerToWorld(e.clientX, e.clientY);
      if (!world) return;
      e.preventDefault();
      e.stopPropagation();
      setDrag({
        nodeId,
        pointerId: e.pointerId,
        grabDx: world.x - pos.x,
        grabDy: world.y - pos.y,
        currentX: pos.x,
        currentY: pos.y,
      });
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [positions, pointerToWorld],
  );

  const handleNodePointerMove = useCallback(
    (nodeId: string, e: ReactPointerEvent<HTMLDivElement>) => {
      if (!drag || drag.nodeId !== nodeId || drag.pointerId !== e.pointerId) return;
      const world = pointerToWorld(e.clientX, e.clientY);
      if (!world) return;
      e.preventDefault();
      e.stopPropagation();
      setDrag((d) =>
        d && d.nodeId === nodeId
          ? { ...d, currentX: world.x - d.grabDx, currentY: world.y - d.grabDy }
          : d,
      );
    },
    [drag, pointerToWorld],
  );

  const handleNodePointerUp = useCallback(
    (nodeId: string, e: ReactPointerEvent<HTMLDivElement>) => {
      if (!drag || drag.nodeId !== nodeId || drag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch { /* already released */ }
      const final = { x: drag.currentX, y: drag.currentY };
      setDrag(null);
      if (final.x !== positions[nodeId]?.x || final.y !== positions[nodeId]?.y) {
        onLayoutChange(setNodePosition(layout, nodeId, final));
      }
    },
    [drag, positions, layout, onLayoutChange],
  );

  // ---------------------------------------------------------------------------
  // Background pan + wheel zoom.
  // ---------------------------------------------------------------------------
  const handleBgPointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    if (e.target !== e.currentTarget) return;
    e.preventDefault();
    onSelectStep(null);
    onSelectEdge(null);
    setPan({
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startCameraX: cameraRef.current.x,
      startCameraY: cameraRef.current.y,
    });
    e.currentTarget.setPointerCapture(e.pointerId);
  }, [onSelectStep, onSelectEdge]);

  const handleBgPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pan || pan.pointerId !== e.pointerId) return;
    const cam = cameraRef.current;
    const dx = (e.clientX - pan.startClientX) / cam.scale;
    const dy = (e.clientY - pan.startClientY) / cam.scale;
    setCamera({ ...cam, x: pan.startCameraX - dx, y: pan.startCameraY - dy });
  }, [pan]);

  const handleBgPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pan || pan.pointerId !== e.pointerId) return;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* ok */ }
    setPan(null);
  }, [pan]);

  const handleWheel = useCallback((e: ReactWheelEvent<HTMLDivElement>) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const cam = cameraRef.current;
    const nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, cam.scale * factor));
    if (nextScale === cam.scale) return;
    // Zoom around the cursor so the world point under the cursor stays put.
    const worldX = (e.clientX - rect.left) / cam.scale + cam.x;
    const worldY = (e.clientY - rect.top) / cam.scale + cam.y;
    const nextX = worldX - (e.clientX - rect.left) / nextScale;
    const nextY = worldY - (e.clientY - rect.top) / nextScale;
    setCamera(clampCamera({ x: nextX, y: nextY, scale: nextScale }));
  }, []);

  return (
    <div
      ref={canvasRef}
      data-testid="pipeline-canvas-surface"
      onPointerDown={handleBgPointerDown}
      onPointerMove={handleBgPointerMove}
      onPointerUp={handleBgPointerUp}
      onPointerCancel={handleBgPointerUp}
      onWheel={handleWheel}
      className="relative flex-1 min-w-0 min-h-0 overflow-hidden bg-surface-raised/15 cursor-grab active:cursor-grabbing"
      style={{ touchAction: "none" }}
    >
      <div
        className="absolute origin-top-left"
        style={{
          transform: `translate(${-camera.x * camera.scale}px, ${-camera.y * camera.scale}px) scale(${camera.scale})`,
          transformOrigin: "0 0",
          width: 0,
          height: 0,
          pointerEvents: "none",
        }}
      >
        <div style={{ pointerEvents: "auto" }}>
          <EdgeLayer
            edges={edges}
            positions={positions}
            selectedEdgeKey={selectedEdgeKey}
            onSelectEdge={onSelectEdge}
            bounds={bounds}
          />
        </div>
        {steps.map((step) => {
          const pos = positions[step.id];
          if (!pos) return null;
          const dragging = drag?.nodeId === step.id;
          const x = dragging ? drag!.currentX : pos.x;
          const y = dragging ? drag!.currentY : pos.y;
          return (
            <div key={step.id} style={{ pointerEvents: "auto" }}>
              <StepNode
                step={step}
                x={x}
                y={y}
                selected={selectedStepId === step.id}
                stale={staleIds.has(step.id)}
                onPointerDown={(e) => handleNodePointerDown(step.id, e)}
                onPointerMove={(e) => handleNodePointerMove(step.id, e)}
                onPointerUp={(e) => handleNodePointerUp(step.id, e)}
                onSelect={() => {
                  onSelectStep(step.id);
                  onSelectEdge(null);
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { edgeKey };
