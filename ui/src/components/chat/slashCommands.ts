import type { CompletionItem } from "../../types/api";

export interface SlashCommandItem {
  id: string;
  label: string;
  description: string;
}

export const SLASH_COMMANDS: SlashCommandItem[] = [
  { id: "context", label: "/context", description: "View context breakdown" },
  { id: "clear", label: "/clear", description: "Start new session" },
  { id: "compact", label: "/compact", description: "Compress conversation" },
];

/** Filter slash commands by query string and return as CompletionItems. */
export function filterSlashCommands(query: string): CompletionItem[] {
  const q = query.toLowerCase();
  return SLASH_COMMANDS
    .filter((cmd) => cmd.id.startsWith(q) || cmd.label.includes(q))
    .map((cmd): CompletionItem => ({
      value: cmd.id,
      label: cmd.label,
      description: cmd.description,
    }));
}
