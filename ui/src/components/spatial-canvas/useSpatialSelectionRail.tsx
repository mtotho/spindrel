type UseSpatialSelectionRailArgs = Record<string, any>;

export function useSpatialSelectionRail(_args: UseSpatialSelectionRailArgs) {
  // Starboard Map Brief owns single-object inspection. Zoomed-out clusters are
  // map navigation affordances, not another selected detail surface.
  return null;
}
