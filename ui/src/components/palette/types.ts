import type { ComponentType } from "react";

export interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  href?: string;
  icon: ComponentType<{ size: number; color: string }>;
  category: string;
  /** ISO timestamp; only populated for channel items. */
  lastMessageAt?: string | null;
  onSelect?: () => void;
  routeKind?: string;
}

export interface ScoredItem {
  item: PaletteItem;
  score: number;
  matchIndices: number[];
}
