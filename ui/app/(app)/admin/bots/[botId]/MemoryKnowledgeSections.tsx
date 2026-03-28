/**
 * Memory mode selector + Knowledge section for the bot editor.
 * Extracted to keep the main editor file manageable.
 */
import { useState } from "react";
import { Check, ChevronDown, HelpCircle, Trash2, X } from "lucide-react";
import { useBotMemories, useDeleteMemory } from "@/src/api/hooks/useMemories";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import {
  TextInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const WORKSPACE_FILES_PRESETS = [
  { label: "DB memory tools hidden", detail: "save_memory, search_memories, purge_memory, merge_memories" },
  { label: "DB knowledge tools hidden", detail: "upsert_knowledge, edit_knowledge, search_knowledge, and others" },
  { label: "File-based tools injected", detail: "search_memory (hybrid semantic+keyword) and get_memory_file" },
  { label: "MEMORY.md always in context", detail: "Curated bootstrap file with stable facts — always injected" },
  { label: "Daily logs auto-loaded", detail: "Today's and yesterday's logs injected every turn" },
  { label: "Memory prompt auto-injected", detail: "Built-in prompt guides the bot on file-based memory workflow" },
  { label: "Compaction flush redirected", detail: "Pre-compaction memory save writes to files instead of DB" },
];

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

const DIR_STRUCTURE = `memory/
├── MEMORY.md              # Always in context. Curated stable facts.
├── logs/
│   ├── YYYY-MM-DD.md      # Today + yesterday auto-loaded
│   └── *.md               # Older logs searchable via search_memory
└── reference/
    └── *.md               # Longer docs, searchable + readable via tools`;

// ---------------------------------------------------------------------------
// Bot memories list (DB mode)
// ---------------------------------------------------------------------------
function BotMemoriesSection({ botId }: { botId: string | undefined }) {
  const { data: memories, isLoading } = useBotMemories(botId);
  const deleteMut = useDeleteMemory();

  if (!botId) return null;

  return (
    <div style={{ marginTop: 8, borderTop: "1px solid #222", paddingTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e5e5", marginBottom: 4 }}>
        Stored Memories
      </div>
      <div style={{ fontSize: 10, color: "#555", marginBottom: 12 }}>
        Facts this bot has memorized. Delete individual memories that are no longer relevant.
      </div>

      {isLoading && (
        <div style={{ padding: 12, color: "#555", fontSize: 12 }}>Loading...</div>
      )}

      {!isLoading && (!memories || memories.length === 0) && (
        <div style={{ padding: 12, color: "#444", fontSize: 12, fontStyle: "italic" }}>
          No memories stored yet.
        </div>
      )}

      {memories && memories.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {memories.map((m) => (
            <div key={m.id} style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              padding: "8px 10px", background: "#111", borderRadius: 6,
              border: "1px solid #1a1a1a",
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12, color: "#ccc", lineHeight: 1.5,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>
                  {m.content}
                </div>
                <div style={{ fontSize: 10, color: "#555", marginTop: 4 }}>
                  {new Date(m.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  {m.client_id && <span> &middot; {m.client_id.slice(0, 12)}</span>}
                </div>
              </div>
              <button
                onClick={() => {
                  if (confirm("Delete this memory?")) deleteMut.mutate(m.id);
                }}
                disabled={deleteMut.isPending}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  padding: 4, flexShrink: 0, color: "#666",
                }}
                title="Delete memory"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Architecture help overlay
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
        onClick={(e) => e.stopPropagation()}
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
// Memory section — mode selector + settings
// ---------------------------------------------------------------------------
export function MemorySection({ draft, update, botId }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const isWorkspaceFiles = draft.memory_scheme === "workspace-files";
  const [showPrompt, setShowPrompt] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const selectMode = (mode: string | null) => {
    if (mode === "workspace-files") {
      update({
        memory_scheme: "workspace-files",
        memory: { ...draft.memory, enabled: false },
        knowledge: { ...draft.knowledge, enabled: false },
      });
    } else {
      update({ memory_scheme: null });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Memory</div>
        <button
          onClick={() => setShowHelp(true)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "#555", padding: 2, display: "flex", alignItems: "center",
          }}
          title="How workspace files memory works"
        >
          <HelpCircle size={15} />
        </button>
      </div>
      {showHelp && <ArchitectureOverlay onClose={() => setShowHelp(false)} />}

      {/* Mode selector cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {/* Database mode */}
        <button
          onClick={() => selectMode(null)}
          style={{
            textAlign: "left", cursor: "pointer",
            padding: "14px 16px", borderRadius: 8,
            border: !isWorkspaceFiles ? "2px solid #3b82f6" : "1px solid #2a2a2a",
            background: !isWorkspaceFiles ? "rgba(59,130,246,0.06)" : "#0f0f0f",
            transition: "all 0.15s",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <div style={{
              width: 16, height: 16, borderRadius: 8,
              border: !isWorkspaceFiles ? "5px solid #3b82f6" : "2px solid #444",
              background: "transparent",
            }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: !isWorkspaceFiles ? "#e5e5e5" : "#888" }}>
              Database
            </span>
            {!isWorkspaceFiles && (
              <span style={{
                fontSize: 9, padding: "2px 6px", borderRadius: 3,
                background: "rgba(59,130,246,0.15)", color: "#93c5fd",
                fontWeight: 600, letterSpacing: 0.5,
              }}>ACTIVE</span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "#666", lineHeight: 1.5, marginLeft: 24 }}>
            Short facts stored in PostgreSQL with pgvector embeddings.
            Semantic similarity retrieval each turn. Tools: save_memory,
            search_memories, upsert_knowledge.
          </div>
        </button>

        {/* Workspace Files mode */}
        <button
          onClick={() => selectMode("workspace-files")}
          style={{
            textAlign: "left", cursor: "pointer",
            padding: "14px 16px", borderRadius: 8,
            border: isWorkspaceFiles ? "2px solid #a855f7" : "1px solid #2a2a2a",
            background: isWorkspaceFiles ? "rgba(168,85,247,0.06)" : "#0f0f0f",
            transition: "all 0.15s",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <div style={{
              width: 16, height: 16, borderRadius: 8,
              border: isWorkspaceFiles ? "5px solid #a855f7" : "2px solid #444",
              background: "transparent",
            }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: isWorkspaceFiles ? "#e5e5e5" : "#888" }}>
              Workspace Files
            </span>
            {isWorkspaceFiles && (
              <span style={{
                fontSize: 9, padding: "2px 6px", borderRadius: 3,
                background: "rgba(168,85,247,0.15)", color: "#c4b5fd",
                fontWeight: 600, letterSpacing: 0.5,
              }}>ACTIVE</span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "#666", lineHeight: 1.5, marginLeft: 24 }}>
            File-based memory with daily logs, curated MEMORY.md, and
            reference docs. Hybrid semantic + keyword search. Replaces
            DB memory and knowledge tools.
          </div>
        </button>
      </div>

      {/* Workspace Files mode — preset info + built-in prompt */}
      {isWorkspaceFiles && (
        <>
          {/* What changes */}
          <div style={{
            background: "rgba(168,85,247,0.04)", border: "1px solid rgba(168,85,247,0.15)",
            borderRadius: 8, padding: "14px 16px",
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#c4b5fd", marginBottom: 10 }}>
              Applying presets
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {WORKSPACE_FILES_PRESETS.map((p, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <Check size={12} color="#a855f7" style={{ marginTop: 2, flexShrink: 0 } as any} />
                  <div>
                    <span style={{ fontSize: 12, color: "#ccc" }}>{p.label}</span>
                    <span style={{ fontSize: 11, color: "#555" }}> — {p.detail}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Directory structure preview */}
          <div style={{
            background: "#0a0a0a", border: "1px solid #1a1a1a",
            borderRadius: 8, padding: "12px 16px",
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 8 }}>
              Directory Structure
            </div>
            <pre style={{
              margin: 0, fontSize: 11, lineHeight: 1.7, color: "#999",
              fontFamily: "monospace",
            }}>{DIR_STRUCTURE}</pre>
          </div>

          {/* Built-in prompt (collapsible) */}
          <div style={{
            background: "#0a0a0a", border: "1px solid #1a1a1a",
            borderRadius: 8, overflow: "hidden",
          }}>
            <button
              onClick={() => setShowPrompt(!showPrompt)}
              style={{
                display: "flex", alignItems: "center", gap: 8, width: "100%",
                padding: "10px 16px", background: "none", border: "none",
                cursor: "pointer", color: "#888",
              }}
            >
              <ChevronDown
                size={14}
                style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
              />
              <span style={{ fontSize: 12, fontWeight: 600 }}>Built-in System Prompt</span>
              <span style={{
                fontSize: 9, padding: "2px 6px", borderRadius: 3,
                background: "rgba(168,85,247,0.1)", color: "#a78bfa",
                marginLeft: 4,
              }}>auto-injected</span>
            </button>
            {showPrompt && (
              <div style={{ padding: "0 16px 14px 16px" }}>
                <pre style={{
                  margin: 0, fontSize: 11, lineHeight: 1.7, color: "#888",
                  fontFamily: "monospace", whiteSpace: "pre-wrap",
                  background: "#111", borderRadius: 6, padding: 12,
                }}>{BUILT_IN_PROMPT}</pre>
              </div>
            )}
          </div>
        </>
      )}

      {/* Database mode — existing settings */}
      {!isWorkspaceFiles && (
        <>
          <div style={{
            background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)",
            borderRadius: 6, padding: "10px 14px",
          }}>
            <div style={{ fontSize: 11, color: "#888", lineHeight: 1.6 }}>
              Stores short facts in the database via pgvector embeddings. Relevant memories are
              automatically injected into context each turn via semantic similarity, and the bot
              can search/save/purge/merge memories via dedicated tools.
            </div>
          </div>
          <Toggle value={draft.memory?.enabled ?? false} onChange={(v) => update({ memory: { ...draft.memory, enabled: v } })} label="Enable Memory" />
          <Toggle value={draft.memory?.cross_channel ?? false} onChange={(v) => update({ memory: { ...draft.memory, cross_channel: v } })}
            label="Cross-Channel" description="Share memories across all channels for this client+bot" />
          <Row>
            <Col>
              <FormRow label="Similarity Threshold">
                <TextInput value={String(draft.memory?.similarity_threshold ?? 0.45)}
                  onChangeText={(v) => update({ memory: { ...draft.memory, similarity_threshold: v ? parseFloat(v) : 0.45 } })} type="number" />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Max Inject Chars">
                <TextInput value={String(draft.memory_max_inject_chars ?? "")}
                  onChangeText={(v) => update({ memory_max_inject_chars: v ? parseInt(v) : null })} placeholder="3000" type="number" />
              </FormRow>
            </Col>
          </Row>
          <FormRow label="Memory Prompt" description="Guidance on what the bot should remember">
            <LlmPrompt value={draft.memory?.prompt || ""}
              onChange={(v) => update({ memory: { ...draft.memory, prompt: v || undefined } })}
              rows={4} placeholder="Specific guidance on what's worth remembering..."
              generateContext="Guidance for an AI on what information to save to long-term memory from conversations. Should describe what to prioritize (facts, preferences, decisions) and what to skip (small talk, transient info)." />
          </FormRow>
          <BotMemoriesSection botId={botId} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knowledge section — shows notice when workspace files mode is active
// ---------------------------------------------------------------------------
export function KnowledgeSection({ draft, update }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
}) {
  const isWorkspaceFiles = draft.memory_scheme === "workspace-files";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Knowledge</div>

      {isWorkspaceFiles && (
        <div style={{
          background: "rgba(168,85,247,0.06)", border: "1px solid rgba(168,85,247,0.15)",
          borderRadius: 8, padding: "14px 16px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#c4b5fd" }}>
              Managed by Workspace Files
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#888", lineHeight: 1.6 }}>
            Knowledge is handled through <code style={{ color: "#a78bfa" }}>memory/reference/</code> files
            when workspace-files memory mode is active. DB knowledge tools are hidden and replaced
            with file-based search and retrieval. You can still enable DB knowledge below if you want both.
          </div>
        </div>
      )}

      {!isWorkspaceFiles && (
        <div style={{
          background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)",
          borderRadius: 6, padding: "10px 14px", marginBottom: 4,
        }}>
          <div style={{ fontSize: 11, color: "#888", lineHeight: 1.6 }}>
            Stores longer-form documents in the database via pgvector embeddings. The bot can
            create, update, append to, and search knowledge documents via dedicated tools.
            Relevant documents are automatically injected into context each turn via semantic
            similarity.
          </div>
        </div>
      )}

      <Toggle value={draft.knowledge?.enabled ?? false} onChange={(v) => update({ knowledge: { ...draft.knowledge, enabled: v } })} label="Enable Knowledge" />
      <div style={{ maxWidth: 300 }}>
        <FormRow label="Max Inject Chars">
          <TextInput value={String(draft.knowledge_max_inject_chars ?? "")}
            onChangeText={(v) => update({ knowledge_max_inject_chars: v ? parseInt(v) : null })} placeholder="8000" type="number" />
        </FormRow>
      </div>
    </div>
  );
}
