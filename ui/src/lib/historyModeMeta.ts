export type HistoryModeValue = "file" | "summary" | "structured";

export type HistoryModeMeta = {
  value: HistoryModeValue;
  label: string;
  accentColor: string;
  summary: string;
  detail: string;
  recommended?: boolean;
  legacy?: boolean;
  showFileArtifacts?: boolean;
};

export const HISTORY_MODE_META: ReadonlyArray<HistoryModeMeta> = [
  {
    value: "file",
    label: "File",
    accentColor: "#d97706",
    summary: "Active default",
    detail:
      "Conversation is archived into titled, searchable sections stored in the database. " +
      "The bot gets an executive summary plus a section index, and can search or open any section with the " +
      "read_conversation_history tool (keyword, content grep, and semantic search). " +
      "This is the active/default path for channels that need specific historical recall.",
    recommended: true,
    showFileArtifacts: true,
  },
  {
    value: "summary",
    label: "Summary",
    accentColor: "#2563eb",
    summary: "Legacy rolling summary",
    detail:
      "Each compaction replaces the previous summary with a new one. " +
      "The bot sees a single summary block plus recent messages. Supported for compatibility, " +
      "but not the preferred default for knowledge-heavy channels.",
    legacy: true,
  },
  {
    value: "structured",
    label: "Structured",
    accentColor: "#9333ea",
    summary: "Legacy semantic retrieval",
    detail:
      "Conversation is archived into titled sections with embeddings, and the system attempts " +
      "to retrieve relevant sections automatically. Supported for compatibility, but the product " +
      "default is the file-mode section index plus on-demand browsing.",
    legacy: true,
  },
];

export function getHistoryModeMeta(mode: string | null | undefined): HistoryModeMeta {
  return HISTORY_MODE_META.find((entry) => entry.value === mode) ?? HISTORY_MODE_META[0];
}

export function historyModeOptionLabel(mode: HistoryModeMeta): string {
  if (mode.recommended) return `${mode.label} (active default)`;
  if (mode.legacy) return `${mode.label} (legacy)`;
  return mode.label;
}
