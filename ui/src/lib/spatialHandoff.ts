export const SPATIAL_HANDOFF_KEY = "spatial.beamFromChannel";

type SpatialHandoff =
  | { kind: "channel"; channelId: string; ts: number }
  | { kind: "widgetPin"; pinId: string; ts: number };

export function writeSpatialHandoff(handoff: SpatialHandoff): void {
  try {
    sessionStorage.setItem(SPATIAL_HANDOFF_KEY, JSON.stringify(handoff));
  } catch {
    /* storage disabled - plain navigation still works */
  }
}

