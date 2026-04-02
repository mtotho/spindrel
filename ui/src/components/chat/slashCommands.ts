import { Extension } from "@tiptap/core";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
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

export const SlashCommand = Extension.create<{
  suggestion: Omit<SuggestionOptions<CompletionItem>, "editor">;
}>({
  name: "slashCommand",

  addOptions() {
    return {
      suggestion: {
        char: "/",
        startOfLine: true,
        items: ({ query }: { query: string }): CompletionItem[] =>
          SLASH_COMMANDS
            .filter(
              (cmd) =>
                cmd.id.startsWith(query.toLowerCase()) ||
                cmd.label.includes(query.toLowerCase()),
            )
            .map((cmd): CompletionItem => ({
              value: cmd.id,
              label: cmd.label,
              description: cmd.description,
            })),
        command: ({ editor, range }: { editor: any; range: any }) => {
          editor.chain().focus().deleteRange(range).run();
        },
      },
    };
  },

  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        ...this.options.suggestion,
      }),
    ];
  },
});
