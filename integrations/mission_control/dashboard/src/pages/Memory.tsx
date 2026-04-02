import { useState, useEffect, useRef, useCallback } from "react";
import { Search, X, FileText } from "lucide-react";
import { useMemory, useReferenceFile, useMemorySearch } from "../hooks/useMC";
import { useScope } from "../lib/ScopeContext";
import { botColor, botDotColor } from "../lib/colors";
import MarkdownViewer from "../components/MarkdownViewer";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import ScopeToggle from "../components/ScopeToggle";

export default function Memory() {
  const { scope } = useScope();
  const { data: sections, isLoading, error, refetch } = useMemory(scope);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const search = useMemorySearch();

  // Debounce search input
  const handleSearchChange = useCallback((q: string) => {
    setSearchQuery(q);
    clearTimeout(debounceRef.current);
    if (q.trim().length >= 2) {
      debounceRef.current = setTimeout(() => {
        setDebouncedQuery(q.trim());
      }, 500);
    } else {
      setDebouncedQuery("");
    }
  }, []);

  // Trigger search when debounced query changes
  useEffect(() => {
    if (debouncedQuery) {
      search.mutate({ query: debouncedQuery, scope });
    }
  }, [debouncedQuery, scope]); // eslint-disable-line react-hooks/exhaustive-deps

  const clearSearch = () => {
    setSearchQuery("");
    setDebouncedQuery("");
    clearTimeout(debounceRef.current);
    search.reset();
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Memory</h1>
          <p className="text-sm text-gray-500 mt-1">MEMORY.md and reference files from bots</p>
        </div>
        <ScopeToggle />
      </div>

      {/* Search input */}
      <div className="relative mb-6">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Search memory files..."
          className="w-full bg-surface-1 border border-surface-3 rounded-md pl-8 pr-8 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-accent/40"
        />
        {searchQuery && (
          <button onClick={clearSearch} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Search results */}
      {debouncedQuery && (
        <div className="mb-6">
          {search.isPending ? (
            <div className="flex items-center gap-2 text-xs text-gray-500 py-4">
              <LoadingSpinner /> Searching...
            </div>
          ) : search.data && search.data.length > 0 ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                Search Results ({search.data.length})
              </h3>
              {search.data.map((r, i) => (
                <div key={i} className="bg-surface-2 rounded-lg border border-surface-3 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: botDotColor(r.bot_id) }} />
                    <span className="text-xs font-medium text-gray-200">{r.bot_name}</span>
                    <span className="text-[10px] text-gray-500 font-mono">{r.file_path}</span>
                  </div>
                  {/* Similarity score bar */}
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-16 h-1 bg-surface-3 rounded-full overflow-hidden">
                      <div className="h-full bg-accent rounded-full" style={{ width: `${Math.min(r.score * 100, 100)}%` }} />
                    </div>
                    <span className="text-[10px] text-gray-500">{(r.score * 100).toFixed(0)}%</span>
                  </div>
                  <pre className="text-xs text-gray-400 whitespace-pre-wrap max-h-32 overflow-y-auto leading-relaxed">
                    {r.content.split("\n").slice(0, 6).join("\n")}
                  </pre>
                </div>
              ))}
            </div>
          ) : search.data ? (
            <p className="text-xs text-gray-500 py-2">No results found for &ldquo;{debouncedQuery}&rdquo;</p>
          ) : null}
        </div>
      )}

      {/* Memory sections */}
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      ) : !sections?.length ? (
        <EmptyState
          icon="◇"
          title="No memory data"
          description="Memory sections will appear here for bots using memory_scheme: workspace-files."
        />
      ) : (
        <div className="space-y-6">
          {sections.map((section) => (
            <MemorySectionView key={section.bot_id} section={section} />
          ))}
        </div>
      )}
    </div>
  );
}

function MemorySectionView({
  section,
}: {
  section: { bot_id: string; bot_name: string; memory_content: string | null; reference_files: string[] };
}) {
  const [expanded, setExpanded] = useState(true);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const bc = botColor(section.bot_id);

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 overflow-hidden">
      {/* Header — tinted with bot color */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-3 transition-colors"
        style={{ backgroundColor: `${bc.dot}08` }}
      >
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: bc.dot }} />
          <span className="text-sm font-medium text-gray-100">{section.bot_name}</span>
          <span className="text-xs text-gray-500">{section.bot_id.slice(0, 8)}</span>
          {section.reference_files.length > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-gray-500 bg-surface-3/50 rounded-full px-1.5 py-px">
              <FileText size={10} />
              {section.reference_files.length} ref
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          {section.memory_content ? (
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">MEMORY.md</h3>
              <div className="bg-surface-1 rounded-lg border border-surface-3 p-4 max-h-96 overflow-y-auto">
                <MarkdownViewer content={section.memory_content} />
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-500 italic">No MEMORY.md file</p>
          )}

          {section.reference_files.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                Reference Files ({section.reference_files.length})
              </h3>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {section.reference_files.map((f) => (
                  <button
                    key={f}
                    onClick={() => setSelectedRef(selectedRef === f ? null : f)}
                    className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                      selectedRef === f
                        ? "border-accent bg-accent/15 text-accent-hover"
                        : "border-surface-3 text-gray-400 hover:text-gray-200"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
              {selectedRef && (
                <ReferenceFilePreview botId={section.bot_id} filename={selectedRef} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReferenceFilePreview({ botId, filename }: { botId: string; filename: string }) {
  const { data: content, isLoading, error } = useReferenceFile(botId, filename);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error.message} />;
  if (!content) return null;

  return (
    <div className="bg-surface-1 rounded-lg border border-surface-3 p-4 max-h-96 overflow-y-auto">
      <MarkdownViewer content={content} />
    </div>
  );
}
