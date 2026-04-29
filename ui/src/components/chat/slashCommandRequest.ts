import type { SlashCommandId, SlashCommandSurface } from "@/src/types/api";

interface BuildSlashCommandExecuteBodyOptions {
  commandId: SlashCommandId;
  surface: SlashCommandSurface;
  channelId?: string;
  sessionId?: string;
  args?: string[];
  argsText?: string;
}

export function buildSlashCommandExecuteBody({
  commandId,
  surface,
  channelId,
  sessionId,
  args = [],
  argsText,
}: BuildSlashCommandExecuteBodyOptions) {
  const rawArgs = argsText ?? args.join(" ");
  if (surface === "channel") {
    if (!channelId) return null;
    return {
      command_id: commandId,
      channel_id: channelId,
      session_id: null,
      current_session_id: sessionId ?? null,
      surface: "web" as const,
      args,
      args_text: rawArgs,
    };
  }

  if (!sessionId) return null;
  return {
    command_id: commandId,
    channel_id: null,
    session_id: sessionId,
    current_session_id: null,
    surface: "web" as const,
    args,
    args_text: rawArgs,
  };
}
