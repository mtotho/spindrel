import { useCallback } from "react";

import { apiFetch } from "@/src/api/client";
import { toast } from "@/src/stores/toast";
import type {
  Message,
  SlashCommandId,
  SlashCommandResult,
  SlashCommandSideEffectPayload,
  SlashCommandSurface,
} from "@/src/types/api";

import { buildSlashCommandResultMessage } from "./slashCommands";
import { buildSlashCommandExecuteBody } from "./slashCommandRequest";

interface Options {
  availableCommands: SlashCommandId[];
  surface: SlashCommandSurface;
  channelId?: string;
  sessionId?: string;
  onSyntheticMessage?: (message: Message) => void;
  onClear?: () => Promise<void> | void;
  onScratch?: () => Promise<void> | void;
  onSideEffect?: (result: SlashCommandResult) => Promise<void> | void;
}

export function useSlashCommandExecutor({
  availableCommands,
  surface,
  channelId,
  sessionId,
  onSyntheticMessage,
  onClear,
  onScratch,
  onSideEffect,
}: Options) {
  return useCallback(
    async (id: string) => {
      if (!availableCommands.includes(id as SlashCommandId)) return;
      switch (id as SlashCommandId) {
        case "clear":
          await onClear?.();
          return;
        case "scratch":
          await onScratch?.();
          return;
        case "context":
        case "stop":
        case "compact":
        case "plan": {
          const body = buildSlashCommandExecuteBody({
            commandId: id as SlashCommandId,
            surface,
            channelId,
            sessionId,
          });
          if (!body) return;
          const result = await apiFetch<SlashCommandResult>("/api/v1/slash-commands/execute", {
            method: "POST",
            body: JSON.stringify(body),
          });
          if (result.result_type === "side_effect") {
            const payload = result.payload as SlashCommandSideEffectPayload;
            toast({
              kind: "info",
              message: payload.detail || result.fallback_text,
            });
            await onSideEffect?.(result);
            return;
          }
          const resolvedSessionId = sessionId ?? (result.payload.session_id as string | undefined) ?? "";
          if (!resolvedSessionId) return;
          onSyntheticMessage?.(
            buildSlashCommandResultMessage(result, resolvedSessionId, channelId),
          );
          return;
        }
      }
    },
    [availableCommands, channelId, onClear, onScratch, onSideEffect, onSyntheticMessage, sessionId, surface],
  );
}
