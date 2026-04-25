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
  /** Keep searchable and recent-eligible, but omit from the empty-query browse list. */
  hideFromBrowse?: boolean;
  /** Keep browse/recent eligible, but omit from typed search results. */
  hideFromSearch?: boolean;
  /** Extra searchable terms that should not be rendered as the visible label. */
  searchText?: string;
  onSelect?: () => void;
  routeKind?: string;
}

export interface ScoredItem {
  item: PaletteItem;
  score: number;
  matchIndices: number[];
}
