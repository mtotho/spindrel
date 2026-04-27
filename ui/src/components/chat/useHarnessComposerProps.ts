import { useMemo } from "react";
import {
  useSessionHarnessSettings,
  useSetSessionHarnessSettings,
} from "../../api/hooks/useApprovals";
import { useRuntimeCapabilities } from "../../api/hooks/useRuntimes";

interface BotLike {
  harness_runtime?: string | null;
}

/**
 * Resolve the harness-related MessageInput props for a (bot, sessionId) pair.
 *
 * MessageInput renders a different model pill when ``harnessRuntime`` is set:
 * the label reads "default" instead of leaking the bot's unrelated LLM ``model``
 * field, and clicking the pill opens a harness-aware picker. Without these
 * props the composer falls back to ``defaultModel`` (=``bot.model``), which is
 * meaningless for harness bots. Use this hook at every composer site that
 * accepts a harness bot.
 */
export function useHarnessComposerProps(
  bot: BotLike | undefined | null,
  sessionId: string | null | undefined,
) {
  const runtime = bot?.harness_runtime ?? null;
  const { data: caps } = useRuntimeCapabilities(runtime);
  const { data: settings } = useSessionHarnessSettings(sessionId ?? null);
  const setHarnessSettings = useSetSessionHarnessSettings();

  return useMemo(() => {
    if (!runtime) {
      return {
        harnessRuntime: null as string | null,
        harnessAvailableModels: [] as string[],
        harnessEffortValues: [] as string[],
        harnessCurrentModel: null as string | null,
        harnessCurrentEffort: null as string | null,
        onHarnessModelChange: undefined as ((model: string | null) => void) | undefined,
        onHarnessEffortChange: undefined as ((effort: string | null) => void) | undefined,
        harnessModelMutating: false,
      };
    }
    return {
      harnessRuntime: runtime,
      harnessAvailableModels: caps?.available_models ?? [],
      harnessEffortValues:
        caps?.model_options?.find((m) => m.id === settings?.model)?.effort_values
        ?? caps?.effort_values
        ?? [],
      harnessCurrentModel: settings?.model ?? null,
      harnessCurrentEffort: settings?.effort ?? null,
      onHarnessModelChange: (model: string | null) => {
        if (!sessionId) return;
        setHarnessSettings.mutate({ sessionId, patch: { model } });
      },
      onHarnessEffortChange: (effort: string | null) => {
        if (!sessionId) return;
        setHarnessSettings.mutate({ sessionId, patch: { effort } });
      },
      harnessModelMutating: setHarnessSettings.isPending,
    };
  }, [runtime, caps, settings, sessionId, setHarnessSettings]);
}
