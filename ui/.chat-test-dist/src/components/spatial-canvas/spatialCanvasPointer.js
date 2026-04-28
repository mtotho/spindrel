export const EMPTY_SPACE_CLICK_DRIFT_PX = 4;
export function isEmptySpaceClickGesture(gesture, driftThresholdPx = EMPTY_SPACE_CLICK_DRIFT_PX) {
    const dx = gesture.endX - gesture.startX;
    const dy = gesture.endY - gesture.startY;
    return Math.hypot(dx, dy) <= driftThresholdPx;
}
