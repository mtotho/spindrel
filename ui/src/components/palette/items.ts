import { useMemo } from "react";
import { Bot, Hash, Home, Plug, Plus } from "lucide-react";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useSidebarSections, useIntegrations } from "../../api/hooks/useIntegrations";
import type { PaletteItem } from "./types";
import { ADMIN_ITEMS } from "./admin-items";

/**
 * Build the flat list of palette items from live data + static admin catalogs.
 * Consumed by both the Ctrl+K command palette overlay and the home-page grid.
 */
export function usePaletteItems(): PaletteItem[] {
  const { data: channels } = useChannels();
  const { data: bots } = useBots();
  const { data: sidebarData } = useSidebarSections();
  const { data: integrationsData } = useIntegrations();

  return useMemo<PaletteItem[]>(() => {
    const items: PaletteItem[] = [];

    // Channel-management entry points. Listed first so they appear at the
    // top of the Channels section — the mobile palette is the only way to
    // reach the home screen / add-channel flow now that the drawer is gone.
    items.push({
      id: "nav-home",
      label: "Home",
      hint: "All channels",
      href: "/",
      icon: Home,
      category: "Channels",
    });
    items.push({
      id: "nav-new-channel",
      label: "New channel",
      hint: "Create a channel",
      href: "/channels/new",
      icon: Plus,
      category: "Channels",
    });

    if (channels) {
      for (const ch of channels) {
        items.push({
          id: `ch-${ch.id}`,
          label: ch.name,
          hint: ch.integration ? `${ch.integration}` : undefined,
          href: `/channels/${ch.id}`,
          icon: Hash,
          category: "Channels",
          lastMessageAt: ch.last_message_at ?? null,
        });
      }
    }

    if (bots) {
      for (const bot of bots) {
        items.push({
          id: `bot-${bot.id}`,
          label: bot.name,
          hint: "Edit bot",
          href: `/admin/bots/${bot.id}`,
          icon: Bot,
          category: "Bots",
        });
      }
    }

    items.push(...ADMIN_ITEMS);

    if (integrationsData?.integrations) {
      for (const int of integrationsData.integrations) {
        // Only surface integrations the user has adopted. Library (available)
        // integrations are discoverable via /admin/integrations → Library tab.
        if (int.lifecycle_status === "available") continue;
        items.push({
          id: `integration-${int.id}`,
          label: int.name,
          hint: "Integration",
          href: `/admin/integrations/${int.id}`,
          icon: Plug,
          category: "Integrations",
        });
      }
    }

    if (sidebarData?.sections) {
      for (const section of sidebarData.sections) {
        for (const item of section.items) {
          items.push({
            id: `int-${section.id}-${item.href}`,
            label: item.label,
            hint: section.title,
            href: item.href,
            icon: Plug,
            category: section.title,
          });
        }
      }
    }

    return items;
  }, [channels, bots, sidebarData, integrationsData]);
}
