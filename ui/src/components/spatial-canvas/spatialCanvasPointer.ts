export const EMPTY_SPACE_CLICK_DRIFT_PX = 4;

interface EmptySpacePointerGesture {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

export function isEmptySpaceClickGesture(
  gesture: EmptySpacePointerGesture,
  driftThresholdPx = EMPTY_SPACE_CLICK_DRIFT_PX,
): boolean {
  const dx = gesture.endX - gesture.startX;
  const dy = gesture.endY - gesture.startY;
  return Math.hypot(dx, dy) <= driftThresholdPx;
}
