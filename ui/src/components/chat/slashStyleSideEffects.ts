import type { QueryClient } from "@tanstack/react-query";

import type { SlashCommandResult } from "@/src/types/api";

type ChatMode = "default" | "terminal";

export function resolveChatModeFromStyleResult(result: SlashCommandResult): ChatMode | null {
  if (result.command_id !== "style") return null;
  const payload = result.payload ?? {};
  const direct = typeof payload.chat_mode === "string"
    ? payload.chat_mode
    : typeof payload.style === "string"
      ? payload.style
      : null;
  const source = direct ?? `${payload.title ?? ""} ${payload.detail ?? ""} ${result.fallback_text ?? ""}`;
  const match = source.match(/\b(default|terminal)\b/i);
  if (!match) return null;
  const mode = match[1].toLowerCase();
  return mode === "default" || mode === "terminal" ? mode : null;
}

export function applyChatStyleSideEffect(
  queryClient: QueryClient,
  channelId: string | null | undefined,
  result: SlashCommandResult,
) {
  if (!channelId) return;
  const mode = resolveChatModeFromStyleResult(result);
  if (!mode) {
    queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
    queryClient.invalidateQueries({ queryKey: ["channels"] });
    return;
  }

  queryClient.setQueryData<any>(["channels", channelId], (old: any) => {
    if (!old) return old;
    const config = { ...(old.config ?? {}) };
    if (mode === "default") {
      delete config.chat_mode;
    } else {
      config.chat_mode = mode;
    }
    return { ...old, config };
  });
  queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
  queryClient.invalidateQueries({ queryKey: ["channels"] });
}
