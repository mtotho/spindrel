import { createContext, useContext } from "react";

/**
 * Bundle of dnd-kit primitives that a tile content can attach to a
 * specific element (typically a small drag-handle / grip), instead of
 * the entire tile body, so empty/transparent areas of the tile don't
 * activate dnd-kit drag — they fall through to the canvas pan.
 *
 * `DraggableNode` provides this context. Tiles that want a scoped
 * activator (e.g. frameless game widgets where empty space around the
 * floating asteroid should be canvas-pannable) opt in via `useDragActivator`
 * and apply the returned `setRef`/`listeners`/`attributes` to their grip.
 */
export interface DragActivatorBundle {
  setRef: (el: HTMLElement | null) => void;
  listeners: Record<string, (event: unknown) => void> | undefined;
  attributes: Record<string, unknown> | undefined;
}

export const DragActivatorContext = createContext<DragActivatorBundle | null>(null);

export function useDragActivator(): DragActivatorBundle | null {
  return useContext(DragActivatorContext);
}
