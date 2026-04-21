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
}

export const SLASH_COMMANDS: SlashCommandItem[] = [
  { id: "stop", label: "/stop", description: "Stop the current response", surfaces: ["channel", "session"] },
  { id: "context", label: "/context", description: "View current context", surfaces: ["channel", "session"] },
  { id: "scratch", label: "/scratch", description: "Open the scratch pad", surfaces: ["channel"] },
  { id: "clear", label: "/clear", description: "Start fresh", surfaces: ["channel"] },
  { id: "compact", label: "/compact", description: "Compress conversation", surfaces: ["channel"] },
];

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
): SlashCommandId | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.includes(" ") || trimmed.includes("\n")) return null;
  const query = trimmed.slice(1).toLowerCase();
  const allow = availableIds ? new Set<SlashCommandId>(availableIds) : null;
  const match = SLASH_COMMANDS.find(
    (cmd) =>
      cmd.surfaces.includes(surface) &&
      (!allow || allow.has(cmd.id)) &&
      cmd.id === query,
  );
  return match?.id ?? null;
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
