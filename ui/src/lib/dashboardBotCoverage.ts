import type { WidgetDashboardPin } from "../types/api";

export interface BotCoverageUser {
  id: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
}

export interface BotGrantLookup {
  /** Map: `bot_id -> set of user_ids with a view+ grant on that bot`. */
  grants: Record<string, Set<string>>;
  /** Map: `bot_id -> owner user_id (or null)`. */
  owners: Record<string, string | null>;
}

export interface BotCoverageGap {
  bot_id: string;
  missing_user_ids: string[];
}

/** Return the bots a dashboard would use (one entry per unique non-null
 *  `source_bot_id`). Pins with no bot id (static widgets, already-broken
 *  rows) are skipped. */
export function dashboardBotIds(pins: WidgetDashboardPin[]): string[] {
  const ids = new Set<string>();
  for (const p of pins) {
    if (p.source_bot_id) ids.add(p.source_bot_id);
  }
  return Array.from(ids);
}

/** For a dashboard shared with `everyone`, return the bots for which at least
 *  one active non-admin user lacks access.
 *
 *  A user has access to a bot iff they are the owner OR have a grant row.
 *  Admins always have access and are excluded from the "missing" set. */
export function computeCoverageGaps(
  pins: WidgetDashboardPin[],
  users: BotCoverageUser[],
  lookup: BotGrantLookup,
): BotCoverageGap[] {
  const nonAdminActive = users.filter((u) => !u.is_admin && u.is_active);
  if (nonAdminActive.length === 0) return [];

  const gaps: BotCoverageGap[] = [];
  for (const bot_id of dashboardBotIds(pins)) {
    const grants = lookup.grants[bot_id] ?? new Set<string>();
    const owner = lookup.owners[bot_id] ?? null;
    const missing: string[] = [];
    for (const u of nonAdminActive) {
      if (u.id === owner) continue;
      if (grants.has(u.id)) continue;
      missing.push(u.id);
    }
    if (missing.length > 0) {
      gaps.push({ bot_id, missing_user_ids: missing });
    }
  }
  return gaps;
}

/** Summarise gaps as plain text for a warning line.
 *  `botLabel` resolves a bot id to a human label; defaults to the id. */
export function summarizeCoverageGaps(
  gaps: BotCoverageGap[],
  users: BotCoverageUser[],
  botLabel: (botId: string) => string = (id) => id,
): string {
  if (gaps.length === 0) return "";
  const missingUsers = new Set<string>();
  for (const g of gaps) for (const uid of g.missing_user_ids) missingUsers.add(uid);
  const userCount = missingUsers.size;
  const botNames = gaps.map((g) => botLabel(g.bot_id));
  const botList = botNames.length <= 3
    ? botNames.join(", ")
    : `${botNames.slice(0, 2).join(", ")} and ${botNames.length - 2} more`;
  const who = userCount === 1
    ? "1 viewer"
    : `${userCount} viewers`;
  return `${who} can't use ${botList}`;
}
