export type SpatialInteractionMode = "browse" | "arrange";

export function canMoveSpatialNode(mode: SpatialInteractionMode, shiftKey: boolean): boolean {
  return mode === "arrange" || shiftKey;
}

export function activeAttentionStatus(status: string): boolean {
  return status !== "resolved" && status !== "acknowledged";
}
