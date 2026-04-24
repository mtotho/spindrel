import { useMemo, useState } from "react";
import { Check, Code, Copy, Eye, FileText, Search, X } from "lucide-react";
import { useWorkspaceFileContent } from "@/src/api/hooks/useWorkspaces";
import { writeToClipboard } from "@/src/utils/clipboard";
import { ActionButton, EmptyState, QuietPill } from "./SettingsControls";

export interface SourceFileTarget {
  kind: "workspace_file";
  workspace_id: string;
  path: string;
  display_path: string;
  owner_type: "bot" | "channel";
  owner_id: string;
  owner_name: string;
}

interface SourceFileInspectorProps {
  target: SourceFileTarget;
  title?: string;
  subtitle?: string;
  fallbackUrl?: string | null;
  onClose: () => void;
  onOpenFallback?: (url: string) => void;
  className?: string;
}

function isMarkdown(path: string) {
  const lower = path.toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".markdown");
}

function lineFragments(line: string, query: string): Array<{ text: string; match: boolean }> {
  const term = query.trim();
  if (!term) return [{ text: line, match: false }];
  const lower = line.toLowerCase();
  const needle = term.toLowerCase();
  const parts: Array<{ text: string; match: boolean }> = [];
  let index = 0;
  while (index < line.length) {
    const found = lower.indexOf(needle, index);
    if (found < 0) {
      parts.push({ text: line.slice(index), match: false });
      break;
    }
    if (found > index) parts.push({ text: line.slice(index, found), match: false });
    parts.push({ text: line.slice(found, found + term.length), match: true });
    index = found + term.length;
  }
  return parts.length ? parts : [{ text: line, match: false }];
}

function MarkdownPreview({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="space-y-2 px-4 py-3 text-[13px] leading-relaxed text-text-muted">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={index} className="h-2" />;
        if (trimmed.startsWith("# ")) {
          return <h2 key={index} className="text-[16px] font-semibold text-text">{trimmed.slice(2)}</h2>;
        }
        if (trimmed.startsWith("## ")) {
          return <h3 key={index} className="text-[14px] font-semibold text-text">{trimmed.slice(3)}</h3>;
        }
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          return <div key={index} className="pl-3 before:mr-2 before:content-['-']">{trimmed.slice(2)}</div>;
        }
        if (trimmed.startsWith("```")) {
          return <div key={index} className="font-mono text-[12px] text-text-dim">{trimmed}</div>;
        }
        return <p key={index}>{line}</p>;
      })}
    </div>
  );
}

export function SourceFileInspector({
  target,
  title,
  subtitle,
  fallbackUrl,
  onClose,
  onOpenFallback,
  className = "",
}: SourceFileInspectorProps) {
  const { data, isLoading, error } = useWorkspaceFileContent(target.workspace_id, target.path);
  const [copied, setCopied] = useState(false);
  const [find, setFind] = useState("");
  const [preview, setPreview] = useState(isMarkdown(target.path));

  const content = data?.content ?? "";
  const lines = useMemo(() => content.split("\n"), [content]);
  const matchCount = useMemo(() => {
    const term = find.trim().toLowerCase();
    if (!term) return 0;
    return lines.reduce((count, line) => count + (line.toLowerCase().includes(term) ? 1 : 0), 0);
  }, [find, lines]);

  const handleCopy = async () => {
    await writeToClipboard(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <aside
      className={
        `fixed inset-3 z-40 flex min-h-0 flex-col overflow-hidden rounded-md bg-surface-raised ` +
        `ring-1 ring-surface-border xl:sticky xl:top-3 xl:inset-auto xl:z-auto xl:h-[calc(100vh-180px)] xl:w-[480px] xl:shrink-0 ` +
        className
      }
    >
      <div className="flex shrink-0 items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-1.5">
            <QuietPill label={target.owner_type} maxWidthClass="max-w-[90px]" />
            <span className="truncate text-[11px] text-text-dim">{target.owner_name}</span>
          </div>
          <h3 className="truncate text-[14px] font-semibold text-text">{title || target.display_path}</h3>
          {subtitle && <p className="mt-1 line-clamp-2 text-[12px] text-text-muted">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-[34px] min-w-[34px] shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
          aria-label="Close source viewer"
        >
          <X size={15} />
        </button>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-3">
        <div className="flex min-h-[34px] min-w-[180px] flex-1 items-center gap-2 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
          <Search size={13} className="shrink-0" />
          <input
            value={find}
            onChange={(event) => setFind(event.target.value)}
            placeholder="Find in file..."
            className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
          />
          {find && <span className="shrink-0 text-[11px]">{matchCount}</span>}
        </div>
        {isMarkdown(target.path) && (
          <ActionButton
            label={preview ? "Source" : "Preview"}
            size="small"
            variant="secondary"
            icon={preview ? <Code size={13} /> : <Eye size={13} />}
            onPress={() => setPreview((value) => !value)}
          />
        )}
        <ActionButton
          label={copied ? "Copied" : "Copy"}
          size="small"
          variant="secondary"
          icon={copied ? <Check size={13} /> : <Copy size={13} />}
          disabled={data == null || isLoading}
          onPress={handleCopy}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-input/45">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3, 4].map((item) => (
              <div key={item} className="h-4 rounded bg-surface-overlay/35" />
            ))}
          </div>
        ) : error ? (
          <div className="p-4">
            <EmptyState
              message={
                <span>
                  Could not read <span className="font-mono">{target.display_path}</span>.
                </span>
              }
              action={
                fallbackUrl && onOpenFallback ? (
                  <ActionButton label="Open location" size="small" variant="secondary" onPress={() => onOpenFallback(fallbackUrl)} />
                ) : null
              }
            />
          </div>
        ) : preview ? (
          <MarkdownPreview content={content} />
        ) : (
          <pre className="m-0 py-3 font-mono text-[12px] leading-5 text-text-muted">
            {lines.map((line, index) => (
              <div key={index} className="flex min-w-max px-3">
                <span className="w-10 shrink-0 select-none pr-3 text-right tabular-nums text-text-dim/70">
                  {index + 1}
                </span>
                <span className="whitespace-pre-wrap break-words">
                  {lineFragments(line || " ", find).map((part, partIndex) => (
                    part.match ? (
                      <mark key={partIndex} className="rounded bg-warning/30 text-text">
                        {part.text}
                      </mark>
                    ) : (
                      <span key={partIndex}>{part.text}</span>
                    )
                  ))}
                </span>
              </div>
            ))}
          </pre>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2 px-4 py-2 text-[11px] text-text-dim">
        <FileText size={12} />
        <span className="min-w-0 truncate">{target.display_path}</span>
        {data?.size != null && <span className="shrink-0">{data.size} bytes</span>}
      </div>
    </aside>
  );
}
