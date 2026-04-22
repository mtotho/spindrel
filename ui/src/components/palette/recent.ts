import type { ComponentType } from "react";
import type { RecentPage } from "../../stores/ui";
import { resolvePaletteRoute } from "../../lib/paletteRoutes.js";

type IconComponent = ComponentType<{ size: number; color: string }>;

export interface RecentPaletteItemCandidate {
  id: string;
  label: string;
  href: string;
  hint?: string;
  icon: IconComponent;
  category: string;
}

export interface ResolvedRecentPaletteItem {
  id: string;
  label: string;
  href: string;
  hint?: string;
  icon: IconComponent;
  category: string;
}

interface ResolveRecentPaletteItemOptions {
  channelNameById?: ReadonlyMap<string, string>;
}

export function resolveRecentPaletteItem(
  recentPage: RecentPage,
  allItems: readonly RecentPaletteItemCandidate[],
  { channelNameById }: ResolveRecentPaletteItemOptions = {},
): ResolvedRecentPaletteItem | null {
  const exact = allItems.find((item) => item.href === recentPage.href);
  const route = resolvePaletteRoute(recentPage.href, {
    channelNameById,
    recentLabel: recentPage.label ?? exact?.label,
    itemHint: exact?.hint ?? recentPage.hint,
  });
  if (!route) return null;

  return {
    id: `recent-${route.canonicalHref}`,
    label: route.label,
    href: route.canonicalHref,
    hint: exact?.hint ?? recentPage.hint ?? route.hint,
    icon: route.icon,
    category: "Recent",
  };
}
