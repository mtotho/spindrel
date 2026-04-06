/**
 * Workspace-level indexing defaults editor.
 * Lets admins set patterns, threshold, top_k, embedding_model,
 * cooldown, and segments at the workspace level so all bots
 * inherit shared config without per-bot duplication.
 */
import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Plus, RotateCcw, X } from "lucide-react";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { Slider } from "@/src/components/shared/FormControls";
import { useWorkspaceIndexing, useUpdateWorkspace } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SegmentDraft {
  path_prefix: string;
  embedding_model?: string;
  patterns?: string[];
  similarity_threshold?: number;
  top_k?: number;
}

// ---------------------------------------------------------------------------
// Inline segment editor for workspace-level segments
// ---------------------------------------------------------------------------

function WorkspaceSegmentEditor({
  segments,
  onChange,
}: {
  segments: SegmentDraft[];
  onChange: (segs: SegmentDraft[]) => void;
}) {
  const t = useThemeTokens();
  const [newPrefix, setNewPrefix] = useState("");
  const [newModel, setNewModel] = useState("");

  const addSegment = () => {
    const prefix = newPrefix.trim();
    if (!prefix) return;
    const seg: SegmentDraft = { path_prefix: prefix };
    if (newModel.trim()) seg.embedding_model = newModel.trim();
    onChange([...segments, seg]);
    setNewPrefix("");
    setNewModel("");
  };

  const removeSegment = (idx: number) => {
    onChange(segments.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
        Segments (Indexed Directories)
      </div>
      <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>
        Define which directories to index. All bots in this workspace will inherit these segments unless they define their own.
      </div>
      {segments.map((seg, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "4px 8px", background: t.inputBg, borderRadius: 4, fontSize: 11, marginBottom: 4,
        }}>
          <span style={{ fontFamily: "monospace", color: "#60a5fa", flex: 1 }}>{seg.path_prefix}</span>
          {seg.embedding_model && (
            <span style={{ color: t.textMuted, fontSize: 10 }}>model: <span style={{ color: "#a78bfa", fontFamily: "monospace" }}>{seg.embedding_model}</span></span>
          )}
          {seg.patterns && <span style={{ color: t.textDim, fontSize: 10 }}>patterns: {seg.patterns.length}</span>}
          {seg.similarity_threshold != null && <span style={{ color: t.textDim, fontSize: 10 }}>thresh: {seg.similarity_threshold}</span>}
          {seg.top_k != null && <span style={{ color: t.textDim, fontSize: 10 }}>k: {seg.top_k}</span>}
          <button
            onClick={() => removeSegment(i)}
            style={{ background: "none", border: "none", cursor: "pointer", padding: "0 2px", color: t.dangerMuted, fontSize: 12, lineHeight: 1 }}
            title="Remove segment"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      {segments.length === 0 && (
        <div style={{ fontSize: 10, color: t.textDim, fontStyle: "italic", marginBottom: 6 }}>
          No workspace-level segments — bots must define their own.
        </div>
      )}
      <div style={{ display: "flex", gap: 4, marginTop: 4, alignItems: "center" }}>
        <input
          type="text" value={newPrefix} onChange={(e) => setNewPrefix(e.target.value)}
          placeholder="directory (e.g. repos/vault/)"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSegment(); } }}
          style={{
            background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", flex: 1, minWidth: 100,
          }}
        />
        <div style={{ flex: 1, minWidth: 160 }}>
          <LlmModelDropdown
            value={newModel}
            onChange={setNewModel}
            placeholder="embedding model (optional)"
            variant="embedding"
          />
        </div>
        <button
          onClick={addSegment}
          disabled={!newPrefix.trim()}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            background: newPrefix.trim() ? t.surfaceRaised : t.inputBg,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            color: newPrefix.trim() ? t.text : t.textDim,
            cursor: newPrefix.trim() ? "pointer" : "default",
          }}
        >
          <Plus size={11} /> Add
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resettable field wrapper
// ---------------------------------------------------------------------------

function FieldRow({
  label,
  placeholder,
  isSet,
  onReset,
  children,
}: {
  label: string;
  placeholder?: string;
  isSet: boolean;
  onReset: () => void;
  children: React.ReactNode;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minHeight: 32 }}>
      <span style={{ fontSize: 11, color: t.textMuted, minWidth: 110, fontWeight: 500 }}>{label}</span>
      <div style={{ flex: 1 }}>{children}</div>
      {placeholder && !isSet && (
        <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>default: {placeholder}</span>
      )}
      {isSet && (
        <button
          onClick={onReset}
          title="Reset to global default"
          style={{
            background: "none", border: "none", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 3,
            padding: "2px 6px", borderRadius: 3,
            fontSize: 10, color: t.textDim,
          }}
        >
          <RotateCcw size={10} /> reset
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tag input for patterns
// ---------------------------------------------------------------------------

function PatternTagInput({
  value,
  onChange,
  placeholder,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const t = useThemeTokens();
  const [input, setInput] = useState("");

  const addTag = () => {
    const trimmed = input.trim();
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed]);
      setInput("");
    }
  };

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: value.length > 0 ? 4 : 0 }}>
        {value.map((pat, i) => (
          <span key={i} style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            padding: "2px 6px", borderRadius: 3, fontSize: 11,
            fontFamily: "monospace", background: t.inputBg, color: "#60a5fa",
          }}>
            {pat}
            <button
              onClick={() => onChange(value.filter((_, j) => j !== i))}
              style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 0, fontSize: 10, lineHeight: 1 }}
            >
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <input
        type="text" value={input} onChange={(e) => setInput(e.target.value)}
        placeholder={placeholder || "Add pattern (e.g. **/*.md)"}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
        style={{
          background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
          padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", width: "100%",
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function WorkspaceDefaultsEditor({ workspaceId }: { workspaceId: string }) {
  const t = useThemeTokens();
  const { data } = useWorkspaceIndexing(workspaceId);
  const updateWorkspace = useUpdateWorkspace(workspaceId);

  const wsCfg = data?.workspace_defaults ?? {};
  const globalDefaults = data?.global_defaults ?? {};
  const hasAnyDefaults = Object.keys(wsCfg).length > 0;

  const [expanded, setExpanded] = useState(!hasAnyDefaults);

  // Local form state — synced from server data
  const [patterns, setPatterns] = useState<string[] | null>(null);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [topK, setTopK] = useState<number | null>(null);
  const [embeddingModel, setEmbeddingModel] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState<number | null>(null);
  const [segments, setSegments] = useState<SegmentDraft[] | null>(null);
  const [dirty, setDirty] = useState(false);

  // Sync from server data
  useEffect(() => {
    if (!data) return;
    const ws = data.workspace_defaults ?? {};
    setPatterns(ws.patterns ?? null);
    setThreshold(ws.similarity_threshold ?? null);
    setTopK(ws.top_k ?? null);
    setEmbeddingModel(ws.embedding_model ?? null);
    setCooldown(ws.cooldown_seconds ?? null);
    setSegments(ws.segments ?? null);
    setDirty(false);
  }, [data]);

  const markDirty = () => setDirty(true);

  const discard = () => {
    const ws = data?.workspace_defaults ?? {};
    setPatterns(ws.patterns ?? null);
    setThreshold(ws.similarity_threshold ?? null);
    setTopK(ws.top_k ?? null);
    setEmbeddingModel(ws.embedding_model ?? null);
    setCooldown(ws.cooldown_seconds ?? null);
    setSegments(ws.segments ?? null);
    setDirty(false);
  };

  const save = () => {
    const cfg: Record<string, any> = {};
    if (patterns !== null) cfg.patterns = patterns;
    if (threshold !== null) cfg.similarity_threshold = threshold;
    if (topK !== null) cfg.top_k = topK;
    if (embeddingModel !== null) cfg.embedding_model = embeddingModel;
    if (cooldown !== null) cfg.cooldown_seconds = cooldown;
    if (segments !== null) cfg.segments = segments;
    updateWorkspace.mutate({ indexing_config: cfg }, {
      onSuccess: () => setDirty(false),
    });
  };

  return (
    <div style={{
      background: t.surface, border: `1px solid ${t.surfaceBorder}`,
      borderRadius: 8, overflow: "hidden",
    }}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          width: "100%", padding: "10px 14px",
          background: "none", border: "none", cursor: "pointer", textAlign: "left",
        }}
      >
        {expanded
          ? <ChevronDown size={13} color={t.textMuted} />
          : <ChevronRight size={13} color={t.textMuted} />}
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
          Workspace Defaults
        </span>
        {hasAnyDefaults && (
          <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: t.accentSubtle, color: t.accentMuted }}>
            {Object.keys(wsCfg).length} configured
          </span>
        )}
        {!hasAnyDefaults && (
          <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
            not configured — bots use global defaults
          </span>
        )}
      </button>

      {/* Body */}
      {expanded && (
        <div style={{ padding: "0 14px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 10, color: t.textDim, lineHeight: 1.5 }}>
            Set workspace-level defaults inherited by all bots. Per-bot overrides take precedence.
          </div>

          <FieldRow label="Patterns" placeholder={globalDefaults.patterns?.join(", ")} isSet={patterns !== null} onReset={() => { setPatterns(null); markDirty(); }}>
            <PatternTagInput
              value={patterns ?? globalDefaults.patterns ?? []}
              onChange={(v) => { setPatterns(v); markDirty(); }}
            />
          </FieldRow>

          <FieldRow label="Threshold" placeholder={String(globalDefaults.similarity_threshold)} isSet={threshold !== null} onReset={() => { setThreshold(null); markDirty(); }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1 }}>
                <Slider
                  value={threshold ?? globalDefaults.similarity_threshold ?? 0.3}
                  onChange={(v: number) => { setThreshold(v); markDirty(); }}
                  min={0} max={1} step={0.05}
                />
              </div>
              <span style={{ fontSize: 11, fontFamily: "monospace", color: t.text, minWidth: 32, textAlign: "right" }}>
                {(threshold ?? globalDefaults.similarity_threshold ?? 0.3).toFixed(2)}
              </span>
            </div>
          </FieldRow>

          <FieldRow label="Top K" placeholder={String(globalDefaults.top_k)} isSet={topK !== null} onReset={() => { setTopK(null); markDirty(); }}>
            <input
              type="number"
              value={topK ?? globalDefaults.top_k ?? 8}
              onChange={(e) => { setTopK(parseInt(e.target.value) || null); markDirty(); }}
              min={1} max={50}
              style={{
                background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", width: 60,
              }}
            />
          </FieldRow>

          <FieldRow label="Embedding Model" placeholder={globalDefaults.embedding_model} isSet={embeddingModel !== null} onReset={() => { setEmbeddingModel(null); markDirty(); }}>
            <LlmModelDropdown
              value={embeddingModel ?? globalDefaults.embedding_model ?? ""}
              onChange={(v) => { setEmbeddingModel(v || null); markDirty(); }}
              variant="embedding"
            />
          </FieldRow>

          <FieldRow label="Cooldown (s)" placeholder={String(globalDefaults.cooldown_seconds)} isSet={cooldown !== null} onReset={() => { setCooldown(null); markDirty(); }}>
            <input
              type="number"
              value={cooldown ?? globalDefaults.cooldown_seconds ?? 300}
              onChange={(e) => { setCooldown(parseInt(e.target.value) || null); markDirty(); }}
              min={0} max={3600}
              style={{
                background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", width: 80,
              }}
            />
          </FieldRow>

          {/* Segments */}
          <div style={{ marginTop: 4, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
            <WorkspaceSegmentEditor
              segments={segments ?? []}
              onChange={(segs) => { setSegments(segs.length > 0 ? segs : null); markDirty(); }}
            />
          </div>

          {/* Save / Discard */}
          {dirty && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
              <button
                onClick={save}
                disabled={updateWorkspace.isPending}
                style={{
                  padding: "6px 16px", borderRadius: 5, fontSize: 12, fontWeight: 600,
                  background: t.accent, border: "none", color: "#fff",
                  cursor: updateWorkspace.isPending ? "default" : "pointer",
                  opacity: updateWorkspace.isPending ? 0.6 : 1,
                }}
              >
                {updateWorkspace.isPending ? "Saving..." : "Save Defaults"}
              </button>
              <button
                onClick={discard}
                disabled={updateWorkspace.isPending}
                style={{
                  padding: "6px 12px", borderRadius: 5, fontSize: 12, fontWeight: 500,
                  background: "none", border: `1px solid ${t.surfaceBorder}`, color: t.textMuted,
                  cursor: "pointer",
                }}
              >
                Discard
              </button>
              {updateWorkspace.isError && (
                <span style={{ fontSize: 11, color: t.dangerMuted }}>Save failed</span>
              )}
            </div>
          )}
          {!dirty && updateWorkspace.isSuccess && (
            <span style={{ fontSize: 11, color: "#14b8a6" }}>Saved</span>
          )}
        </div>
      )}
    </div>
  );
}
