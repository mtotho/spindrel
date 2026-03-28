/**
 * Global Memory Scheme settings section for the Chat History group.
 * Enables/disables workspace-files memory mode across all bots at once.
 */
import { useState, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, HelpCircle, X } from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { apiFetch } from "@/src/api/client";

// ---------------------------------------------------------------------------
// Constants (shared with MemoryKnowledgeSections.tsx in bot editor)
// ---------------------------------------------------------------------------

const BUILT_IN_PROMPT = `## Memory

Your persistent memory lives in \`memory/\` relative to your workspace directory.
MEMORY.md and recent daily logs are in your context — do not re-read them.

### MEMORY.md — Curated Knowledge
Stable facts: user preferences, key decisions, system configs, learned patterns.
Keep under ~100 lines. Promote important learnings from daily logs here.
Format: ## sections with _Updated: YYYY-MM-DD_ headers. Edit in place.

### logs/YYYY-MM-DD.md — Daily Logs
Session notes, events, decisions, task progress. Today's log and yesterday's
are in your context. Append to today's log during the session.

### reference/ — Reference Documents
Longer guides, runbooks, architecture notes. Not in your context.
Use get_memory_file("name") or search_memory("query") to access.

### Tools
- search_memory(query) — hybrid semantic+keyword search across all memory files
- get_memory_file(name) — read a specific memory file

### Rules
- Use exec_command to write/edit memory files (sed, echo, heredoc, etc.)
- Write session events and decisions to today's daily log
- Promote stable facts to MEMORY.md — keep it curated and under ~100 lines
- Search memory before assuming you don't know something
- Write important learnings immediately, don't wait for session end`;

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
    - Write anything needed for future sessions
`.trim();

// ---------------------------------------------------------------------------
// Architecture overlay (modal)
// ---------------------------------------------------------------------------

function ArchitectureOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.75)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e: any) => e.stopPropagation()}
        style={{
          background: "#0a0a0a", border: "1px solid #2a2a2a",
          borderRadius: 12, maxWidth: 780, width: "100%",
          maxHeight: "90vh", overflow: "auto",
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "14px 18px", borderBottom: "1px solid #1a1a1a",
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#e5e5e5" }}>
            Workspace Files Memory — Architecture
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "#666", padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>
        <pre style={{
          margin: 0, padding: "16px 20px",
          fontSize: 11, lineHeight: 1.6, color: "#999",
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
  const { data: bots, isLoading } = useAdminBots();
  const enableAll = useEnableAllMemoryScheme();
  const disableAll = useDisableAllMemoryScheme();
  const [showHelp, setShowHelp] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [justEnabled, setJustEnabled] = useState(false);
  const [justDisabled, setJustDisabled] = useState(false);

  const enabledCount = bots?.filter((b) => b.memory_scheme === "workspace-files").length ?? 0;
  const totalCount = bots?.length ?? 0;
  const allEnabled = totalCount > 0 && enabledCount === totalCount;
  const noneEnabled = enabledCount === 0;

  const handleEnableAll = useCallback(async () => {
    if (!bots) return;
    const toEnable = bots.filter((b) => b.memory_scheme !== "workspace-files").map((b) => b.id);
    if (!toEnable.length) return;
    await enableAll.mutateAsync(toEnable);
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
    <View style={{ marginTop: 16, gap: 16 }}>
      {/* Header with help button */}
      <View style={{ gap: 4 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ fontSize: 14, fontWeight: "700", color: "#e5e5e5" }}>
            Workspace Files Memory
          </Text>
          <Pressable onPress={() => setShowHelp(true)} style={{ padding: 2 }}>
            <HelpCircle size={15} color="#555" />
          </Pressable>
        </View>
        <Text style={{ fontSize: 12, color: "#666" }}>
          File-based memory with daily logs, curated MEMORY.md, and reference docs.
          Replaces DB memory/knowledge tools when active.
        </Text>
      </View>
      {showHelp && <ArchitectureOverlay onClose={() => setShowHelp(false)} />}

      {isLoading ? (
        <ActivityIndicator color="#3b82f6" style={{ alignSelf: "flex-start" }} />
      ) : (
        <View style={{ gap: 14 }}>
            {/* Status summary */}
            <View style={{
              flexDirection: "row", alignItems: "center", gap: 12,
              backgroundColor: "#111", borderRadius: 8,
              borderWidth: 1, borderColor: "#222",
              padding: 14,
            }}>
              <View style={{
                width: 40, height: 40, borderRadius: 20,
                backgroundColor: allEnabled ? "rgba(168,85,247,0.15)" : noneEnabled ? "rgba(100,100,100,0.15)" : "rgba(168,85,247,0.08)",
                alignItems: "center", justifyContent: "center",
              }}>
                <Text style={{
                  fontSize: 16, fontWeight: "700",
                  color: allEnabled ? "#c4b5fd" : noneEnabled ? "#666" : "#a78bfa",
                }}>
                  {enabledCount}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 13, color: "#e5e5e5", fontWeight: "500" }}>
                  {allEnabled
                    ? "All bots using workspace files"
                    : noneEnabled
                    ? "No bots using workspace files"
                    : `${enabledCount} of ${totalCount} bots using workspace files`}
                </Text>
                <Text style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
                  {allEnabled
                    ? "DB memory and knowledge tools are hidden for all bots"
                    : noneEnabled
                    ? "All bots using database memory (legacy)"
                    : "Mixed mode — some bots on workspace files, others on database"}
                </Text>
              </View>
            </View>

            {/* Per-bot status list */}
            {bots && bots.length > 0 && (
              <View style={{
                backgroundColor: "#0d0d0d", borderRadius: 8,
                borderWidth: 1, borderColor: "#1a1a1a",
                overflow: "hidden",
              }}>
                {bots.map((bot, i) => {
                  const enabled = bot.memory_scheme === "workspace-files";
                  return (
                    <View
                      key={bot.id}
                      style={{
                        flexDirection: "row", alignItems: "center",
                        paddingVertical: 8, paddingHorizontal: 14,
                        borderTopWidth: i > 0 ? 1 : 0,
                        borderTopColor: "#1a1a1a",
                      }}
                    >
                      <View style={{
                        width: 8, height: 8, borderRadius: 4,
                        backgroundColor: enabled ? "#a855f7" : "#333",
                        marginRight: 10,
                      }} />
                      <Text style={{
                        flex: 1, fontSize: 12,
                        color: enabled ? "#ccc" : "#666",
                      }}>
                        {bot.name}
                      </Text>
                      <Text style={{
                        fontSize: 10, fontWeight: "600",
                        color: enabled ? "#a78bfa" : "#444",
                      }}>
                        {enabled ? "workspace-files" : "database"}
                      </Text>
                    </View>
                  );
                })}
              </View>
            )}

            {/* Action buttons */}
            <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
              <Pressable
                onPress={handleEnableAll}
                disabled={isBusy || allEnabled}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 6,
                  backgroundColor: allEnabled ? "#1a1a1a" : "rgba(168,85,247,0.15)",
                  paddingHorizontal: 14, paddingVertical: 8,
                  borderRadius: 8, borderWidth: 1,
                  borderColor: allEnabled ? "#222" : "rgba(168,85,247,0.3)",
                  opacity: isBusy || allEnabled ? 0.5 : 1,
                }}
              >
                {enableAll.isPending ? (
                  <ActivityIndicator size="small" color="#a855f7" />
                ) : justEnabled ? (
                  <Check size={14} color="#a855f7" />
                ) : null}
                <Text style={{
                  fontSize: 12, fontWeight: "600",
                  color: allEnabled ? "#555" : "#c4b5fd",
                }}>
                  {justEnabled ? "Enabled" : "Enable All Bots"}
                </Text>
              </Pressable>

              <Pressable
                onPress={handleDisableAll}
                disabled={isBusy || noneEnabled}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 6,
                  backgroundColor: "#1a1a1a",
                  paddingHorizontal: 14, paddingVertical: 8,
                  borderRadius: 8, borderWidth: 1, borderColor: "#333",
                  opacity: isBusy || noneEnabled ? 0.5 : 1,
                }}
              >
                {disableAll.isPending ? (
                  <ActivityIndicator size="small" color="#888" />
                ) : justDisabled ? (
                  <Check size={14} color="#888" />
                ) : null}
                <Text style={{
                  fontSize: 12, fontWeight: "600", color: noneEnabled ? "#444" : "#999",
                }}>
                  {justDisabled ? "Disabled" : "Disable All"}
                </Text>
              </Pressable>
            </View>

            {/* Built-in prompt (collapsible) */}
            <View style={{
              backgroundColor: "#0a0a0a", borderRadius: 8,
              borderWidth: 1, borderColor: "#1a1a1a",
              overflow: "hidden",
            }}>
              <Pressable
                onPress={() => setShowPrompt(!showPrompt)}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 8,
                  paddingVertical: 10, paddingHorizontal: 14,
                }}
              >
                <ChevronDown
                  size={14}
                  color="#888"
                  style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
                />
                <Text style={{ fontSize: 12, fontWeight: "600", color: "#888" }}>
                  Built-in System Prompt
                </Text>
                <View style={{
                  backgroundColor: "rgba(168,85,247,0.1)",
                  paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3,
                  marginLeft: 4,
                }}>
                  <Text style={{ fontSize: 9, fontWeight: "600", color: "#a78bfa" }}>
                    auto-injected
                  </Text>
                </View>
              </Pressable>
              {showPrompt && (
                <View style={{ paddingHorizontal: 14, paddingBottom: 14 }}>
                  <pre style={{
                    margin: 0, fontSize: 11, lineHeight: 1.7, color: "#888",
                    fontFamily: "monospace", whiteSpace: "pre-wrap",
                    background: "#111", borderRadius: 6, padding: 12,
                  }}>{BUILT_IN_PROMPT}</pre>
                  <Text style={{
                    fontSize: 10, color: "#555", marginTop: 8, fontStyle: "italic",
                  }}>
                    This prompt is automatically prepended to the system prompt for all bots with
                    workspace-files memory enabled. Per-bot customization is available in the bot editor.
                  </Text>
                </View>
              )}
            </View>
          </View>
        )}
    </View>
  );
}
