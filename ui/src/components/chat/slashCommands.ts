import type {
  CompletionItem,
  Message,
  SlashCommandId,
  SlashCommandResult,
  SlashCommandSpec,
  SlashCommandSurface,
} from "../../types/api";

export interface ResolvedSlashCommand {
  id: SlashCommandId;
  args: string[];
}

/** Filter slash commands by query string and return as CompletionItems.
 *
 * `catalog` is the server-owned list fetched via `useSlashCommandCatalog`.
 * `availableIds` optionally restricts the surfaced set (channel sources may
 * pass the active channel's permitted subset).
 */
/** Tolerant field access — older cached catalog entries (from before the
 *  registry refactor) can lack `surfaces` or `args`. Treat missing fields as
 *  empty so we never crash the composer on stale data. */
function cmdSurfaces(cmd: SlashCommandSpec): SlashCommandSurface[] {
  return Array.isArray(cmd.surfaces) ? cmd.surfaces : [];
}

function cmdArgs(cmd: SlashCommandSpec): SlashCommandSpec["args"] {
  return Array.isArray(cmd.args) ? cmd.args : [];
}

export function filterSlashCommands(
  query: string,
  surface: SlashCommandSurface,
  catalog: SlashCommandSpec[],
  availableIds?: SlashCommandId[],
): CompletionItem[] {
  const q = query.toLowerCase();
  const allow = availableIds ? new Set<SlashCommandId>(availableIds) : null;
  return catalog
    .filter((cmd) => cmdSurfaces(cmd).includes(surface))
    .filter((cmd) => !allow || allow.has(cmd.id))
    .filter((cmd) => cmd.id.startsWith(q) || cmd.label.includes(q))
    .map((cmd): CompletionItem => ({
      value: cmd.id,
      label: cmd.label,
      description: cmd.description,
    }));
}

export function resolveSlashCommand(
  raw: string,
  surface: SlashCommandSurface,
  catalog: SlashCommandSpec[],
  availableIds?: SlashCommandId[],
): ResolvedSlashCommand | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  const tokens = trimmed.slice(1).split(/\s+/).filter((t) => t.length > 0);
  if (tokens.length === 0) return null;
  const query = tokens[0].toLowerCase();
  const args = tokens.slice(1);
  const allow = availableIds ? new Set<SlashCommandId>(availableIds) : null;
  const match = catalog.find(
    (cmd) =>
      cmdSurfaces(cmd).includes(surface) &&
      (!allow || allow.has(cmd.id)) &&
      cmd.id === query,
  );
  if (!match) return null;
  // Commands without any arg schema reject extra tokens (no accidental silent
  // discard — submit falls through to a normal message send instead).
  const schema = cmdArgs(match);
  const requiredArgs = schema.filter((a) => a.required).length;
  const acceptsArgs = schema.length > 0;
  if (args.length > 0 && !acceptsArgs) return null;
  if (args.length < requiredArgs) return null;
  return { id: match.id, args };
}

/** Look up a single command spec by id, or `null` if not present. */
export function findSpec(
  catalog: SlashCommandSpec[],
  id: SlashCommandId,
): SlashCommandSpec | null {
  return catalog.find((c) => c.id === id) ?? null;
}

export function buildSlashCommandResultMessage(
  result: SlashCommandResult,
  sessionId: string,
  channelId?: string,
): Message {
  const now = new Date().toISOString();
  return {
    id: `msg-slash-${result.command_id}-${Date.now()}`,
    session_id: sessionId,
    role: "assistant",
    content: `${result.command_id} snapshot`,
    created_at: now,
    metadata: {
      kind: "slash_command_result",
      slash_command: result.command_id,
      result_type: result.result_type,
      payload: result.payload,
      fallback_text: result.fallback_text,
      ui_only: true,
      source: "slash_command",
      channel_id: channelId,
    },
  };
}
