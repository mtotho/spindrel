const DEFAULT_CHAT_MODE = {
    id: "default",
    resultMode: "default",
    composerRenderer: "default",
    composerPlacement: "viewport-overlay",
};
const CHAT_MODE_CONFIGS = {
    default: DEFAULT_CHAT_MODE,
    terminal: {
        id: "terminal",
        resultMode: "terminal",
        composerRenderer: "terminal",
        composerPlacement: "transcript-flow",
    },
};
export function getChatModeConfig(mode) {
    return CHAT_MODE_CONFIGS[mode || "default"] ?? {
        ...DEFAULT_CHAT_MODE,
        id: mode || "default",
        resultMode: mode || DEFAULT_CHAT_MODE.resultMode,
        composerRenderer: mode || DEFAULT_CHAT_MODE.composerRenderer,
    };
}
export function isTranscriptFlowComposer(mode) {
    return getChatModeConfig(mode).composerPlacement === "transcript-flow";
}
