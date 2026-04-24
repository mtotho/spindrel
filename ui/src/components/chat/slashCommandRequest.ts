import type { SlashCommandId, SlashCommandSurface } from "@/src/types/api";

interface BuildSlashCommandExecuteBodyOptions {
  commandId: SlashCommandId;
  surface: SlashCommandSurface;
  channelId?: string;
  sessionId?: string;
  args?: string[];
}

export function buildSlashCommandExecuteBody({
  commandId,
  surface,
  channelId,
  sessionId,
  args = [],
}: BuildSlashCommandExecuteBodyOptions) {
  if (surface === "channel") {
    if (!channelId) return null;
    return {
      command_id: commandId,
      channel_id: channelId,
      session_id: null,
      surface: "web" as const,
      args,
    };
  }

  if (!sessionId) return null;
  return {
    command_id: commandId,
    channel_id: null,
    session_id: sessionId,
    surface: "web" as const,
    args,
  };
}
