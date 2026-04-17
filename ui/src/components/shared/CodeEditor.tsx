/** Shared re-export of the channel-message CodeEditor for use outside that page.
 *
 * Accepts either a `filePath` (language inferred) or an explicit `language`.
 */
import { CodeEditor as ChannelCodeEditor } from "@/app/(app)/channels/[channelId]/CodeEditor";
import type { ThemeTokens } from "@/src/theme/tokens";

type Language = "yaml" | "json" | "py" | "md";

interface SharedCodeEditorProps {
  content: string;
  onChange: (content: string) => void;
  language?: Language;
  filePath?: string;
  t: ThemeTokens;
}

const LANG_TO_EXT: Record<Language, string> = {
  yaml: "sample.yaml",
  json: "sample.json",
  py: "sample.py",
  md: "sample.md",
};

export function CodeEditor({ content, onChange, language, filePath, t }: SharedCodeEditorProps) {
  const resolvedPath = filePath ?? (language ? LANG_TO_EXT[language] : "sample.txt");
  return (
    <ChannelCodeEditor
      content={content}
      onChange={onChange}
      filePath={resolvedPath}
      t={t}
    />
  );
}
