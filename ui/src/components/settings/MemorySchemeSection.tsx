/**
 * Global Memory Scheme settings section for the Memory & Learning group.
 * Enables/disables workspace-files memory mode across all bots at once.
 */
import { useState, useCallback, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, HelpCircle, Save, X } from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useMemorySchemeDefaults } from "@/src/api/hooks/useMemorySchemeDefaults";
import { useSettings, useUpdateSettings } from "@/src/api/hooks/useSettings";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "../../theme/tokens";

const ARCHITECTURE_DIAGRAM = `
┌─────────────────────────────────────────────────────────────────┐
│                    WORKSPACE FILES MEMORY MODE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  memory/                                                         │
│  ├── MEMORY.md           ← always in context (curated facts)    │
│  ├── logs/                                                       │
│  │   ├── 2026-03-28.md   ← auto-loaded (today)                 │
│  │   ├── 2026-03-27.md   ← auto-loaded (yesterday)             │
│  │   └── *.md            ← searchable only                      │
│  └── reference/                                                  │
│      └── *.md            ← searchable only                      │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────────────────┐          │
│  │  search_memory   │  │  get_memory_file              │          │
│  │  (hybrid search) │  │  (read by name)               │          │
│  │  vector + BM25   │  │  shorthand resolution         │          │
│  │  RRF merge       │  │  path traversal protection    │          │
│  └────────┬─────────┘  └──────────────────────────────┘          │
│           │                                                       │
│  ┌────────▼──────────────────────────────────────┐               │
│  │  filesystem_chunks (pgvector + tsvector)       │               │
│  │  ← indexed by existing fs_indexer pipeline     │               │
│  │  ← file watcher auto-reindexes on change       │               │
│  └────────────────────────────────────────────────┘               │
│                                                                    │
│  HIDDEN: save_memory, search_memories, purge_memory,              │
│          merge_memories, upsert_knowledge, edit_knowledge,        │
│          search_knowledge, + 8 more DB tools                      │
│                                                                    │
│  WRITING: bot uses exec_command (sed, echo, heredoc)              │
│                                                                    │
│  COMPACTION FLUSH: redirected to file writes                      │
│  SYSTEM PROMPT: built-in memory prompt auto-injected              │
└─────────────────────────────────────────────────────────────────┘

HOW IT WORKS

  Context injection (every turn):
    1. Read MEMORY.md from disk → inject as system message
    2. Read today's log (logs/YYYY-MM-DD.md) → inject as system message
    3. Read yesterday's log → inject as system message
    4. List reference/ files → inject filenames so bot knows what's available
    5. Exclude already-injected files from filesystem RAG (no duplication)

  Search (search_memory tool):
    Hybrid retrieval over all memory files:
    ┌─────────────┐   ┌───────────────┐
    │ Vector hits  │   │ Full-text hits │
    │ (pgvector    │   │ (tsvector      │
    │  cosine sim) │   │  BM25 rank)    │
    └──────┬───────┘   └──────┬─────────┘
           │                  │
           └────────┬─────────┘
                    │
           Reciprocal Rank Fusion (k=60)
                    │
              Top-K results

  Writing:
    Bot uses exec_command to write/edit files directly.
    No custom write tools — LLMs handle shell file ops well.
    File watcher detects changes → auto-reindex for search.

  Compaction flush:
    Before compaction runs, the bot is prompted to:
    - Append key decisions/events to today's daily log
    - Promote stable facts to MEMORY.md
    - Write anything needed for future conversations
`.trim();

// ---------------------------------------------------------------------------
// Architecture overlay (modal)
// ---------------------------------------------------------------------------

function ArchitectureOverlay({ onClose }: { onClose: () => void }) {
  const t = useThemeTokens();
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[100] flex items-center justify-center p-5"
      style={{ background: "rgba(0,0,0,0.75)", backdropFilter: "blur(4px)" }}
    >
      <div
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        className="bg-surface rounded-xl w-full max-w-[780px] max-h-[90vh] overflow-auto"
        style={{ border: `1px solid ${t.surfaceOverlay}` }}
      >
        <div
          className="flex items-center justify-between px-4 py-3.5"
          style={{ borderBottom: `1px solid ${t.surfaceRaised}` }}
        >
          <span className="text-text text-sm font-bold">
            Workspace Files Memory — Architecture
          </span>
          <button
            onClick={onClose}
            className="bg-transparent border-none cursor-pointer text-text-dim p-1"
          >
            <X size={16} />
          </button>
        </div>
        <pre className="m-0 px-5 py-4 text-[11px] leading-relaxed text-text-muted font-mono whitespace-pre overflow-x-auto">
          {ARCHITECTURE_DIAGRAM}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bulk enable/disable mutations
// ---------------------------------------------------------------------------

function useEnableAllMemoryScheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (botIds: string[]) => {
      await Promise.all(
        botIds.map((id) =>
          apiFetch(`/api/v1/admin/bots/${id}/memory-scheme`, { method: "POST" })
        )
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-bots"] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

function useDisableAllMemoryScheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (botIds: string[]) => {
      await Promise.all(
        botIds.map((id) =>
          apiFetch(`/api/v1/admin/bots/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ memory_scheme: null }),
          })
        )
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-bots"] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Main section component
// ---------------------------------------------------------------------------

export function MemorySchemeSection() {
  const t = useThemeTokens();
  const { data: bots, isLoading } = useAdminBots();
  const { data: defaults } = useMemorySchemeDefaults();
  const builtInPrompt = defaults?.prompt ?? "";
  const builtInFlushPrompt = defaults?.flush_prompt ?? "";
  const enableAll = useEnableAllMemoryScheme();
  const disableAll = useDisableAllMemoryScheme();
  const [showHelp, setShowHelp] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showFlush, setShowFlush] = useState(false);
  const [justEnabled, setJustEnabled] = useState(false);
  const [justDisabled, setJustDisabled] = useState(false);

  // Custom prompt override (ui_hidden setting, managed here instead of in the settings list)
  const { data: settingsData } = useSettings();
  const updateSettings = useUpdateSettings();
  const [useCustomPrompt, setUseCustomPrompt] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [promptDirty, setPromptDirty] = useState(false);
  const [promptSaved, setPromptSaved] = useState(false);

  // Load saved override from settings data
  useEffect(() => {
    const val = settingsData?.groups
      ?.flatMap((g: any) => g.settings)
      ?.find((s: any) => s.key === "MEMORY_SCHEME_PROMPT")?.value as string | undefined;
    if (val) {
      setUseCustomPrompt(true);
      setCustomPrompt(val);
    }
  }, [settingsData]);

  const handleSavePrompt = useCallback(async () => {
    const val = useCustomPrompt ? customPrompt : "";
    await updateSettings.mutateAsync({ MEMORY_SCHEME_PROMPT: val });
    setPromptDirty(false);
    setPromptSaved(true);
    setTimeout(() => setPromptSaved(false), 2000);
  }, [useCustomPrompt, customPrompt, updateSettings]);

  const handleToggleCustom = useCallback((v: boolean) => {
    setUseCustomPrompt(v);
    if (v && !customPrompt) {
      setCustomPrompt(builtInPrompt);
    }
    setPromptDirty(true);
    setPromptSaved(false);
  }, [customPrompt, builtInPrompt]);

  const enabledCount = bots?.filter((b) => b.memory_scheme === "workspace-files").length ?? 0;
  const totalCount = bots?.length ?? 0;
  const allEnabled = totalCount > 0 && enabledCount === totalCount;
  const noneEnabled = enabledCount === 0;

  const handleEnableAll = useCallback(async () => {
    if (!bots?.length) return;
    await enableAll.mutateAsync(bots.map((b) => b.id));
    setJustEnabled(true);
    setJustDisabled(false);
    setTimeout(() => setJustEnabled(false), 2000);
  }, [bots, enableAll]);

  const handleDisableAll = useCallback(async () => {
    if (!bots) return;
    const toDisable = bots.filter((b) => b.memory_scheme === "workspace-files").map((b) => b.id);
    if (!toDisable.length) return;
    await disableAll.mutateAsync(toDisable);
    setJustDisabled(true);
    setJustEnabled(false);
    setTimeout(() => setJustDisabled(false), 2000);
  }, [bots, disableAll]);

  const isBusy = enableAll.isPending || disableAll.isPending;

  return (
    <div className="mt-4 flex flex-col gap-4">
      {/* Header with help button */}
      <div className="flex flex-col gap-1">
        <div className="flex flex-row items-center gap-2">
          <span className="text-text text-sm font-bold">
            Workspace Files Memory
          </span>
          <button
            onClick={() => setShowHelp(true)}
            className="p-0.5 bg-transparent border-none cursor-pointer flex flex-row items-center"
          >
            <HelpCircle size={15} className="text-text-dim" />
          </button>
        </div>
        <span className="text-text-dim text-xs">
          File-based memory with daily logs, curated MEMORY.md, and reference docs.
          Replaces DB memory/knowledge tools when active.
        </span>
      </div>
      {showHelp && <ArchitectureOverlay onClose={() => setShowHelp(false)} />}

      {isLoading ? (
        <div className="self-start">
          <div className="chat-spinner" />
        </div>
      ) : (
        <div className="flex flex-col gap-3.5">
          {/* Status summary */}
          <div
            className="flex flex-row items-center gap-3 rounded-lg p-3.5"
            style={{
              backgroundColor: t.inputBg,
              border: `1px solid ${t.surfaceOverlay}`,
            }}
          >
            <div
              className="w-10 h-10 rounded-full flex items-center justify-center shrink-0"
              style={{
                backgroundColor: allEnabled
                  ? t.purpleSubtle
                  : noneEnabled
                  ? "rgba(100,100,100,0.15)"
                  : t.purpleSubtle,
              }}
            >
              <span
                className="text-base font-bold"
                style={{
                  color: allEnabled
                    ? t.purple
                    : noneEnabled
                    ? t.textDim
                    : t.purpleMuted,
                }}
              >
                {enabledCount}
              </span>
            </div>
            <div className="flex-1">
              <span className="text-text text-[13px] font-medium block">
                {allEnabled
                  ? "All bots using workspace files"
                  : noneEnabled
                  ? "No bots using workspace files"
                  : `${enabledCount} of ${totalCount} bots using workspace files`}
              </span>
              <span className="text-text-dim text-[11px] mt-0.5 block">
                {allEnabled
                  ? "DB memory and knowledge tools are hidden for all bots"
                  : noneEnabled
                  ? "All bots using database memory (legacy)"
                  : "Mixed mode — some bots on workspace files, others on database"}
              </span>
            </div>
          </div>

          {/* Per-bot status list */}
          {bots && bots.length > 0 && (
            <div
              className="rounded-lg overflow-hidden"
              style={{
                backgroundColor: t.surface,
                border: `1px solid ${t.surfaceRaised}`,
              }}
            >
              {bots.map((bot, i) => {
                const enabled = bot.memory_scheme === "workspace-files";
                return (
                  <div
                    key={bot.id}
                    className="flex flex-row items-center px-3.5 py-2"
                    style={{
                      borderTop:
                        i > 0 ? `1px solid ${t.surfaceRaised}` : "none",
                    }}
                  >
                    <div
                      className="w-2 h-2 rounded-full mr-2.5 shrink-0"
                      style={{
                        backgroundColor: enabled ? t.purple : t.surfaceBorder,
                      }}
                    />
                    <span
                      className="flex-1 text-xs"
                      style={{ color: enabled ? t.text : t.textDim }}
                    >
                      {bot.name}
                    </span>
                    <span
                      className="text-[10px] font-semibold"
                      style={{
                        color: enabled ? t.purpleMuted : t.surfaceBorder,
                      }}
                    >
                      {enabled ? "workspace-files" : "database"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-row flex-wrap gap-2.5">
            <button
              onClick={handleEnableAll}
              disabled={isBusy || allEnabled}
              className="flex flex-row items-center gap-1.5 px-3.5 py-2 rounded-lg"
              style={{
                backgroundColor: allEnabled ? t.surfaceRaised : t.purpleSubtle,
                border: `1px solid ${allEnabled ? t.surfaceOverlay : t.purpleBorder}`,
                opacity: isBusy || allEnabled ? 0.5 : 1,
                cursor: isBusy || allEnabled ? "default" : "pointer",
              }}
            >
              {enableAll.isPending ? (
                <div className="chat-spinner" />
              ) : justEnabled ? (
                <Check size={14} color={t.purple} />
              ) : null}
              <span
                className="text-xs font-semibold"
                style={{ color: allEnabled ? t.textDim : t.purple }}
              >
                {justEnabled ? "Enabled" : "Enable All Bots"}
              </span>
            </button>

            <button
              onClick={handleDisableAll}
              disabled={isBusy || noneEnabled}
              className="flex flex-row items-center gap-1.5 px-3.5 py-2 rounded-lg"
              style={{
                backgroundColor: t.surfaceRaised,
                border: `1px solid ${t.surfaceBorder}`,
                opacity: isBusy || noneEnabled ? 0.5 : 1,
                cursor: isBusy || noneEnabled ? "default" : "pointer",
              }}
            >
              {disableAll.isPending ? (
                <div className="chat-spinner" />
              ) : justDisabled ? (
                <Check size={14} color={t.textMuted} />
              ) : null}
              <span
                className="text-xs font-semibold"
                style={{
                  color: noneEnabled ? t.surfaceBorder : t.textMuted,
                }}
              >
                {justDisabled ? "Disabled" : "Disable All"}
              </span>
            </button>
          </div>

          {/* System prompt — view built-in or edit custom override */}
          <div
            className="rounded-lg overflow-hidden"
            style={{
              backgroundColor: t.surface,
              border: `1px solid ${t.surfaceRaised}`,
            }}
          >
            <button
              onClick={() => setShowPrompt(!showPrompt)}
              className="flex flex-row items-center gap-2 px-3.5 py-2.5 bg-transparent border-none cursor-pointer w-full text-left"
            >
              <ChevronDown
                size={14}
                className={`text-text-muted transition-transform duration-150 ${
                  showPrompt ? "rotate-0" : "-rotate-90"
                }`}
              />
              <span className="text-text-muted text-xs font-semibold">
                System Prompt
              </span>
              <span
                className="text-[9px] font-semibold px-1.5 py-0.5 rounded ml-1"
                style={{
                  backgroundColor: useCustomPrompt
                    ? t.warningSubtle
                    : t.purpleSubtle,
                  color: useCustomPrompt ? t.warning : t.purpleMuted,
                }}
              >
                {useCustomPrompt ? "custom" : "built-in"}
              </span>
            </button>
            {showPrompt && (
              <div className="px-3.5 pb-3.5 flex flex-col gap-2.5">
                {/* Toggle for custom override */}
                <button
                  onClick={() => handleToggleCustom(!useCustomPrompt)}
                  className="flex flex-row items-center gap-2 bg-transparent border-none cursor-pointer p-0 text-left"
                >
                  <div
                    className="w-11 h-6 rounded-xl relative shrink-0 transition-colors duration-200"
                    style={{
                      backgroundColor: useCustomPrompt
                        ? t.warningSubtle
                        : t.surfaceBorder,
                    }}
                  >
                    <div
                      className="w-5 h-5 rounded-full bg-white absolute top-0.5 transition-[left] duration-200"
                      style={{ left: useCustomPrompt ? 22 : 2 }}
                    />
                  </div>
                  <span
                    className="text-[11px]"
                    style={{
                      color: useCustomPrompt ? t.warning : t.textDim,
                    }}
                  >
                    Use custom prompt (not recommended)
                  </span>
                </button>

                {useCustomPrompt ? (
                  <>
                    <LlmPrompt
                      value={customPrompt}
                      onChange={(v: string) => {
                        setCustomPrompt(v);
                        setPromptDirty(true);
                        setPromptSaved(false);
                      }}
                      placeholder="Custom workspace-files system prompt..."
                      rows={12}
                      fieldType="memory_scheme"
                      generateContext="Workspace-files memory system prompt. Instructs the bot how to use file-based memory."
                    />
                    <div className="flex flex-row items-center gap-2">
                      <button
                        onClick={handleSavePrompt}
                        disabled={!promptDirty || updateSettings.isPending}
                        className="flex flex-row items-center gap-1.5 px-3 py-1.5 rounded-md border-none"
                        style={{
                          backgroundColor: promptDirty
                            ? t.warningSubtle
                            : t.surfaceRaised,
                          opacity: promptDirty ? 1 : 0.5,
                          cursor: promptDirty ? "pointer" : "default",
                        }}
                      >
                        {updateSettings.isPending ? (
                          <div className="chat-spinner" />
                        ) : promptSaved ? (
                          <Check size={12} color={t.warning} />
                        ) : (
                          <Save size={12} color={t.warning} />
                        )}
                        <span
                          className="text-[11px] font-semibold"
                          style={{ color: t.warning }}
                        >
                          {promptSaved ? "Saved" : "Save"}
                        </span>
                      </button>
                      <button
                        onClick={() => {
                          setCustomPrompt(builtInPrompt);
                          setPromptDirty(true);
                        }}
                        className="px-2 py-1 bg-transparent border-none cursor-pointer"
                      >
                        <span className="text-[10px] text-text-dim">
                          Reset to default
                        </span>
                      </button>
                    </div>
                  </>
                ) : (
                  <pre className="m-0 text-[11px] leading-relaxed text-text-muted font-mono whitespace-pre-wrap rounded-md p-3 bg-surface-overlay">
                    {builtInPrompt}
                  </pre>
                )}
              </div>
            )}
          </div>

          {/* Flush prompt viewer */}
          <div
            className="rounded-lg overflow-hidden"
            style={{
              backgroundColor: t.surface,
              border: `1px solid ${t.surfaceRaised}`,
            }}
          >
            <button
              onClick={() => setShowFlush(!showFlush)}
              className="flex flex-row items-center gap-2 px-3.5 py-2.5 bg-transparent border-none cursor-pointer w-full text-left"
            >
              <ChevronDown
                size={14}
                className={`text-text-muted transition-transform duration-150 ${
                  showFlush ? "rotate-0" : "-rotate-90"
                }`}
              />
              <span className="text-text-muted text-xs font-semibold">
                Memory Flush Prompt
              </span>
              <span
                className="text-[9px] font-semibold px-1.5 py-0.5 rounded ml-1"
                style={{
                  backgroundColor: t.warningSubtle,
                  color: t.warning,
                }}
              >
                overridden
              </span>
            </button>
            {showFlush && (
              <div className="px-3.5 pb-3.5">
                <span
                  className="text-[11px] mb-2 block"
                  style={{ color: t.warning }}
                >
                  Workspace-files bots use this flush prompt instead of the
                  Memory Flush Default Prompt:
                </span>
                <pre className="m-0 text-[11px] leading-relaxed text-text-muted font-mono whitespace-pre-wrap rounded-md p-3 bg-surface-overlay">
                  {builtInFlushPrompt}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
