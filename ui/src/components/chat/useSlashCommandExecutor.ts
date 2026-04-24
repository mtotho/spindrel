import { useCallback } from "react";

import { apiFetch } from "@/src/api/client";
import { toast } from "@/src/stores/toast";
import type {
  Message,
  SlashCommandId,
  SlashCommandResult,
  SlashCommandSideEffectPayload,
  SlashCommandSpec,
  SlashCommandSurface,
} from "@/src/types/api";

import { buildSlashCommandResultMessage } from "./slashCommands";
import { buildSlashCommandExecuteBody } from "./slashCommandRequest";

/** Local handler for a client-only slash command (local_only=true in the spec).
 *
 * `clear`, `scratch`, `model`, and `theme` are purely client-side. Callers
 * register handlers for whichever ones apply in their surface; unregistered
 * local commands surface a no-op warning.
 */
export type SlashLocalHandler = (args: string[]) => Promise<void> | void;

interface Options {
  availableCommands: SlashCommandId[];
  catalog: SlashCommandSpec[];
  surface: SlashCommandSurface;
  channelId?: string;
  sessionId?: string;
  onSyntheticMessage?: (message: Message) => void;
  onSideEffect?: (result: SlashCommandResult) => Promise<void> | void;
  localHandlers?: Partial<Record<SlashCommandId, SlashLocalHandler>>;
}

export function useSlashCommandExecutor({
  availableCommands,
  catalog,
  surface,
  channelId,
  sessionId,
  onSyntheticMessage,
  onSideEffect,
  localHandlers,
}: Options) {
  return useCallback(
    async (id: string, args: string[] = []) => {
      if (!availableCommands.includes(id as SlashCommandId)) return;
      const spec = catalog.find((c) => c.id === id);
      if (!spec) {
        // Unknown command — either catalog hasn't loaded yet, or this id is a
        // stale client-side reference. Surface softly rather than hang.
        toast({ kind: "error", message: `Unknown command /${id}` });
        return;
      }

      if (spec.local_only) {
        const handler = localHandlers?.[id as SlashCommandId];
        if (!handler) {
          // Catalog says client-only but no handler is wired up here —
          // likely a surface mismatch (e.g. /scratch on a session dock).
          toast({
            kind: "error",
            message: `/${id} isn't available in this surface`,
          });
          return;
        }
        try {
          await handler(args);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          toast({ kind: "error", message });
        }
        return;
      }

      const body = buildSlashCommandExecuteBody({
        commandId: id as SlashCommandId,
        surface,
        channelId,
        sessionId,
        args,
      });
      if (!body) return;
      try {
        const result = await apiFetch<SlashCommandResult>(
          "/api/v1/slash-commands/execute",
          { method: "POST", body: JSON.stringify(body) },
        );
        if (result.result_type === "side_effect") {
          const payload = result.payload as SlashCommandSideEffectPayload;
          if (payload.effect !== "compact") {
            toast({
              kind: "info",
              message: payload.detail || result.fallback_text,
            });
          }
          await onSideEffect?.(result);
          return;
        }
        // context_summary, find_results, or any future renderer-backed result
        // → surface as a synthetic assistant message the chat feed renders.
        const resolvedSessionId =
          sessionId ?? (result.payload.session_id as string | undefined) ?? "";
        if (!resolvedSessionId) return;
        onSyntheticMessage?.(
          buildSlashCommandResultMessage(result, resolvedSessionId, channelId),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast({ kind: "error", message });
      }
    },
    [
      availableCommands,
      catalog,
      channelId,
      localHandlers,
      onSideEffect,
      onSyntheticMessage,
      sessionId,
      surface,
    ],
  );
}
