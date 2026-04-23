export type ChatModeId = "default" | "terminal" | (string & {});
export type ResultRenderMode = "default" | "terminal" | (string & {});
export type ComposerPlacement = "viewport-overlay" | "transcript-flow";
export type ComposerRendererKey = "default" | "terminal" | (string & {});

export interface ChatModeConfig {
  id: ChatModeId;
  resultMode: ResultRenderMode;
  composerRenderer: ComposerRendererKey;
  composerPlacement: ComposerPlacement;
}

const DEFAULT_CHAT_MODE: ChatModeConfig = {
  id: "default",
  resultMode: "default",
  composerRenderer: "default",
  composerPlacement: "viewport-overlay",
};

const CHAT_MODE_CONFIGS: Record<string, ChatModeConfig> = {
  default: DEFAULT_CHAT_MODE,
  terminal: {
    id: "terminal",
    resultMode: "terminal",
    composerRenderer: "terminal",
    composerPlacement: "transcript-flow",
  },
};

export function getChatModeConfig(mode: ChatModeId | null | undefined): ChatModeConfig {
  return CHAT_MODE_CONFIGS[mode || "default"] ?? {
    ...DEFAULT_CHAT_MODE,
    id: mode || "default",
    resultMode: mode || DEFAULT_CHAT_MODE.resultMode,
    composerRenderer: mode || DEFAULT_CHAT_MODE.composerRenderer,
  };
}

export function isTranscriptFlowComposer(mode: ChatModeId | null | undefined): boolean {
  return getChatModeConfig(mode).composerPlacement === "transcript-flow";
}
