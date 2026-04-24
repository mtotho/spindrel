import type {
  CompletionItem,
  Message,
  SlashCommandId,
  SlashCommandResult,
  SlashCommandSurface,
} from "../../types/api";

export interface SlashCommandItem {
  id: SlashCommandId;
  label: string;
  description: string;
  surfaces: SlashCommandSurface[];
  /** If true, the UI handles this command locally and does not POST to the backend. */
  localOnly?: boolean;
  /** If true, `/command arg` is parsed and arg is forwarded to the backend. */
  acceptsArgs?: boolean;
  /** Allowed arg values, for UX hints and client-side validation. */
  argEnum?: string[];
}

export const SLASH_COMMANDS: SlashCommandItem[] = [
  { id: "stop", label: "/stop", description: "Stop the current response", surfaces: ["channel", "session"] },
  { id: "context", label: "/context", description: "View current context", surfaces: ["channel", "session"] },
  { id: "scratch", label: "/scratch", description: "Open the scratch pad", surfaces: ["channel"], localOnly: true },
  { id: "clear", label: "/clear", description: "Start fresh", surfaces: ["channel"], localOnly: true },
  { id: "compact", label: "/compact", description: "Compress conversation", surfaces: ["channel"] },
  { id: "plan", label: "/plan", description: "Toggle plan mode", surfaces: ["channel", "session"] },
  {
    id: "effort",
    label: "/effort",
    description: "Set reasoning effort (off / low / medium / high)",
    surfaces: ["channel"],
    acceptsArgs: true,
    argEnum: ["off", "low", "medium", "high"],
  },
];

export interface ResolvedSlashCommand {
  id: SlashCommandId;
  args: string[];
}

/** Filter slash commands by query string and return as CompletionItems. */
export function filterSlashCommands(
  query: string,
  surface: SlashCommandSurface,
  availableIds?: SlashCommandId[],
): CompletionItem[] {
  const q = query.toLowerCase();
  const allow = availableIds ? new Set<SlashCommandId>(availableIds) : null;
  return SLASH_COMMANDS
    .filter((cmd) => cmd.surfaces.includes(surface))
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
  availableIds?: SlashCommandId[],
): ResolvedSlashCommand | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  // Split on whitespace — first token is the command id, rest are args.
  // Commands without `acceptsArgs` still accept no-arg input; if extra tokens
  // appear for such commands we return null so submit falls through to normal
  // message send (no accidental silent discard).
  const tokens = trimmed.slice(1).split(/\s+/).filter((t) => t.length > 0);
  if (tokens.length === 0) return null;
  const query = tokens[0].toLowerCase();
  const args = tokens.slice(1);
  const allow = availableIds ? new Set<SlashCommandId>(availableIds) : null;
  const match = SLASH_COMMANDS.find(
    (cmd) =>
      cmd.surfaces.includes(surface) &&
      (!allow || allow.has(cmd.id)) &&
      cmd.id === query,
  );
  if (!match) return null;
  if (args.length > 0 && !match.acceptsArgs) return null;
  return { id: match.id, args };
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
