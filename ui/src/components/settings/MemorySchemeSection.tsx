/**
 * Global Memory Scheme settings section for the Chat History group.
 * Enables/disables workspace-files memory mode across all bots at once.
 */
import { useState, useCallback, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, HelpCircle, Save, X } from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useMemorySchemeDefaults } from "@/src/api/hooks/useMemorySchemeDefaults";
import { useSettings, useUpdateSettings } from "@/src/api/hooks/useSettings";
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
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.75)", backdropFilter: "blur(4px)",
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        style={{
          background: t.surface, border: `1px solid ${t.surfaceOverlay}`,
          borderRadius: 12, maxWidth: 780, width: "100%",
          maxHeight: "90vh", overflow: "auto",
        }}
      >
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
          padding: "14px 18px", borderBottom: `1px solid ${t.surfaceRaised}`,
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
            Workspace Files Memory — Architecture
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: t.textDim, padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>
        <pre style={{
          margin: 0, padding: "16px 20px",
          fontSize: 11, lineHeight: 1.6, color: t.textMuted,
          fontFamily: "monospace", whiteSpace: "pre",
          overflowX: "auto",
        }}>{ARCHITECTURE_DIAGRAM}</pre>
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
    // Always re-bootstrap all bots (fixes paths for orchestrators, idempotent for others)
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
    <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header with help button */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
            Workspace Files Memory
          </span>
          <button
            onClick={() => setShowHelp(true)}
            style={{ padding: 2, background: "none", border: "none", cursor: "pointer", display: "flex", flexDirection: "row", alignItems: "center" }}
          >
            <HelpCircle size={15} color={t.textDim} />
          </button>
        </div>
        <span style={{ fontSize: 12, color: t.textDim }}>
          File-based memory with daily logs, curated MEMORY.md, and reference docs.
          Replaces DB memory/knowledge tools when active.
        </span>
      </div>
      {showHelp && <ArchitectureOverlay onClose={() => setShowHelp(false)} />}

      {isLoading ? (
        <div style={{ alignSelf: "flex-start" }}>
          <div className="chat-spinner" />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Status summary */}
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 12,
              backgroundColor: t.inputBg, borderRadius: 8,
              border: `1px solid ${t.surfaceOverlay}`,
              padding: 14,
            }}>
              <div style={{
                width: 40, height: 40, borderRadius: 20,
                backgroundColor: allEnabled ? t.purpleSubtle : noneEnabled ? "rgba(100,100,100,0.15)" : t.purpleSubtle,
                display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
              }}>
                <span style={{
                  fontSize: 16, fontWeight: 700,
                  color: allEnabled ? t.purple : noneEnabled ? t.textDim : t.purpleMuted,
                }}>
                  {enabledCount}
                </span>
              </div>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 13, color: t.text, fontWeight: 500, display: "block" }}>
                  {allEnabled
                    ? "All bots using workspace files"
                    : noneEnabled
                    ? "No bots using workspace files"
                    : `${enabledCount} of ${totalCount} bots using workspace files`}
                </span>
                <span style={{ fontSize: 11, color: t.textDim, marginTop: 2, display: "block" }}>
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
              <div style={{
                backgroundColor: t.surface, borderRadius: 8,
                border: `1px solid ${t.surfaceRaised}`,
                overflow: "hidden",
              }}>
                {bots.map((bot, i) => {
                  const enabled = bot.memory_scheme === "workspace-files";
                  return (
                    <div
                      key={bot.id}
                      style={{
                        display: "flex", flexDirection: "row", alignItems: "center",
                        paddingTop: 8, paddingBottom: 8, paddingLeft: 14, paddingRight: 14,
                        borderTop: i > 0 ? `1px solid ${t.surfaceRaised}` : "none",
                      }}
                    >
                      <div style={{
                        width: 8, height: 8, borderRadius: 4,
                        backgroundColor: enabled ? t.purple : t.surfaceBorder,
                        marginRight: 10,
                      }} />
                      <span style={{
                        flex: 1, fontSize: 12,
                        color: enabled ? t.text : t.textDim,
                      }}>
                        {bot.name}
                      </span>
                      <span style={{
                        fontSize: 10, fontWeight: 600,
                        color: enabled ? t.purpleMuted : t.surfaceBorder,
                      }}>
                        {enabled ? "workspace-files" : "database"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Action buttons */}
            <div style={{ display: "flex", flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
              <button
                onClick={handleEnableAll}
                disabled={isBusy || allEnabled}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  backgroundColor: allEnabled ? t.surfaceRaised : t.purpleSubtle,
                  paddingLeft: 14, paddingRight: 14, paddingTop: 8, paddingBottom: 8,
                  borderRadius: 8, border: `1px solid ${allEnabled ? t.surfaceOverlay : t.purpleBorder}`,
                  opacity: isBusy || allEnabled ? 0.5 : 1,
                  cursor: isBusy || allEnabled ? "default" : "pointer",
                }}
              >
                {enableAll.isPending ? (
                  <div className="chat-spinner" />
                ) : justEnabled ? (
                  <Check size={14} color={t.purple} />
                ) : null}
                <span style={{
                  fontSize: 12, fontWeight: 600,
                  color: allEnabled ? t.textDim : t.purple,
                }}>
                  {justEnabled ? "Enabled" : "Enable All Bots"}
                </span>
              </button>

              <button
                onClick={handleDisableAll}
                disabled={isBusy || noneEnabled}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  backgroundColor: t.surfaceRaised,
                  paddingLeft: 14, paddingRight: 14, paddingTop: 8, paddingBottom: 8,
                  borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
                  opacity: isBusy || noneEnabled ? 0.5 : 1,
                  cursor: isBusy || noneEnabled ? "default" : "pointer",
                }}
              >
                {disableAll.isPending ? (
                  <div className="chat-spinner" />
                ) : justDisabled ? (
                  <Check size={14} color={t.textMuted} />
                ) : null}
                <span style={{
                  fontSize: 12, fontWeight: 600, color: noneEnabled ? t.surfaceBorder : t.textMuted,
                }}>
                  {justDisabled ? "Disabled" : "Disable All"}
                </span>
              </button>
            </div>

            {/* System prompt — view built-in or edit custom override */}
            <div style={{
              backgroundColor: t.surface, borderRadius: 8,
              border: `1px solid ${t.surfaceRaised}`,
              overflow: "hidden",
            }}>
              <button
                onClick={() => setShowPrompt(!showPrompt)}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                  paddingTop: 10, paddingBottom: 10, paddingLeft: 14, paddingRight: 14,
                  background: "none", border: "none", cursor: "pointer", width: "100%",
                  textAlign: "left",
                }}
              >
                <ChevronDown
                  size={14}
                  color={t.textMuted}
                  style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" }}
                />
                <span style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>
                  System Prompt
                </span>
                <div style={{
                  backgroundColor: useCustomPrompt ? t.warningSubtle : t.purpleSubtle,
                  paddingLeft: 6, paddingRight: 6, paddingTop: 2, paddingBottom: 2, borderRadius: 3,
                  marginLeft: 4,
                }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: useCustomPrompt ? t.warning : t.purpleMuted }}>
                    {useCustomPrompt ? "custom" : "built-in"}
                  </span>
                </div>
              </button>
              {showPrompt && (
                <div style={{ paddingLeft: 14, paddingRight: 14, paddingBottom: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                  {/* Toggle for custom override */}
                  <button
                    onClick={() => handleToggleCustom(!useCustomPrompt)}
                    style={{
                      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                      background: "none", border: "none", cursor: "pointer", padding: 0,
                      textAlign: "left",
                    }}
                  >
                    <div
                      style={{
                        width: 44,
                        height: 24,
                        borderRadius: 12,
                        backgroundColor: useCustomPrompt ? t.warningSubtle : t.surfaceBorder,
                        position: "relative",
                        flexShrink: 0,
                        transition: "background-color 0.2s",
                      }}
                    >
                      <div
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: 10,
                          backgroundColor: "white",
                          position: "absolute",
                          top: 2,
                          left: useCustomPrompt ? 22 : 2,
                          transition: "left 0.2s",
                        }}
                      />
                    </div>
                    <span style={{ fontSize: 11, color: useCustomPrompt ? t.warning : t.textDim }}>
                      Use custom prompt (not recommended)
                    </span>
                  </button>

                  {useCustomPrompt ? (
                    <>
                      <textarea
                        value={customPrompt}
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => { setCustomPrompt(e.target.value); setPromptDirty(true); setPromptSaved(false); }}
                        style={{
                          width: "100%", minHeight: 280,
                          fontSize: 11, lineHeight: "1.7", color: t.text,
                          fontFamily: "monospace", whiteSpace: "pre-wrap",
                          background: t.inputBg, borderRadius: 6, padding: 12,
                          border: `1px solid ${t.surfaceOverlay}`, resize: "vertical",
                          boxSizing: "border-box",
                        }}
                      />
                      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <button
                          onClick={handleSavePrompt}
                          disabled={!promptDirty || updateSettings.isPending}
                          style={{
                            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                            backgroundColor: promptDirty ? t.warningSubtle : t.surfaceRaised,
                            paddingLeft: 12, paddingRight: 12, paddingTop: 6, paddingBottom: 6,
                            borderRadius: 6, opacity: promptDirty ? 1 : 0.5,
                            border: "none", cursor: promptDirty ? "pointer" : "default",
                          }}
                        >
                          {updateSettings.isPending ? (
                            <div className="chat-spinner" />
                          ) : promptSaved ? (
                            <Check size={12} color={t.warning} />
                          ) : (
                            <Save size={12} color={t.warning} />
                          )}
                          <span style={{ fontSize: 11, fontWeight: 600, color: t.warning }}>
                            {promptSaved ? "Saved" : "Save"}
                          </span>
                        </button>
                        <button
                          onClick={() => { setCustomPrompt(builtInPrompt); setPromptDirty(true); }}
                          style={{
                            paddingLeft: 8, paddingRight: 8, paddingTop: 4, paddingBottom: 4,
                            background: "none", border: "none", cursor: "pointer",
                          }}
                        >
                          <span style={{ fontSize: 10, color: t.textDim }}>Reset to default</span>
                        </button>
                      </div>
                    </>
                  ) : (
                    <pre style={{
                      margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
                      fontFamily: "monospace", whiteSpace: "pre-wrap",
                      background: t.inputBg, borderRadius: 6, padding: 12,
                    }}>{builtInPrompt}</pre>
                  )}
                </div>
              )}
            </div>

            {/* Flush prompt override notice */}
            <div style={{
              backgroundColor: t.surface, borderRadius: 8,
              border: `1px solid ${t.surfaceRaised}`,
              overflow: "hidden",
            }}>
              <button
                onClick={() => setShowFlush(!showFlush)}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                  paddingTop: 10, paddingBottom: 10, paddingLeft: 14, paddingRight: 14,
                  background: "none", border: "none", cursor: "pointer", width: "100%",
                  textAlign: "left",
                }}
              >
                <ChevronDown
                  size={14}
                  color={t.textMuted}
                  style={{ transform: showFlush ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" }}
                />
                <span style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>
                  Memory Flush Prompt
                </span>
                <div style={{
                  backgroundColor: t.warningSubtle,
                  paddingLeft: 6, paddingRight: 6, paddingTop: 2, paddingBottom: 2, borderRadius: 3,
                  marginLeft: 4,
                }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: t.warning }}>
                    overridden
                  </span>
                </div>
              </button>
              {showFlush && (
                <div style={{ paddingLeft: 14, paddingRight: 14, paddingBottom: 14 }}>
                  <span style={{ fontSize: 11, color: t.warning, marginBottom: 8, display: "block" }}>
                    The "Memory Flush Default Prompt" setting above is ignored for bots with
                    workspace-files enabled. This prompt is used instead:
                  </span>
                  <pre style={{
                    margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
                    fontFamily: "monospace", whiteSpace: "pre-wrap",
                    background: t.inputBg, borderRadius: 6, padding: 12,
                  }}>{builtInFlushPrompt}</pre>
                </div>
              )}
            </div>
          </div>
        )}
    </div>
  );
}
