import { useState, useEffect, useCallback } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { Link, useParams, useNavigate, useLocation } from "react-router-dom";
import { useUIStore } from "@/src/stores/ui";
import {
  useCarapace,
  useCreateCarapace,
  useUpdateCarapace,
  useDeleteCarapace,
  useResolveCarapace,
  useCarapaceUsage,
} from "@/src/api/hooks/useCarapaces";
import type { CarapaceUsageItem } from "@/src/api/hooks/useCarapaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Save, Trash2, ArrowLeft, ChevronDown, ChevronRight,
  Layers, HelpCircle, Info, Bot, Hash, Home, Zap,
} from "lucide-react";
import { CarapaceHelpModal } from "./CarapaceHelpModal";
import { Section, FormRow } from "@/src/components/shared/FormControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { Carapace } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CarapaceDetailPage() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { carapaceId: rawId } = useParams<{ carapaceId: string }>();
  // Decode -- back to / for IDs with slashes (e.g. integration carapaces)
  const carapaceId = rawId?.replaceAll("--", "/");
  const isNew = carapaceId === "new";

  const { data: existing, isLoading } = useCarapace(isNew ? undefined : carapaceId);
  const { data: resolved } = useResolveCarapace(isNew ? undefined : carapaceId);
  const { data: usage } = useCarapaceUsage(isNew ? undefined : carapaceId);
  const createMut = useCreateCarapace();
  const updateMut = useUpdateCarapace(carapaceId || "");
  const deleteMut = useDeleteCarapace();

  const [draft, setDraft] = useState<Partial<Carapace>>({
    id: "",
    name: "",
    description: "",
    local_tools: [],
    mcp_tools: [],
    pinned_tools: [],
    system_prompt_fragment: "",
    includes: [],
    tags: [],
  });
  const [dirty, setDirty] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  // Enrich command palette recent with capability name
  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    if (existing?.name) enrichRecentPage(loc.pathname, existing.name);
  }, [existing?.name, loc.pathname, enrichRecentPage]);

  useEffect(() => {
    if (existing && !isNew) {
      setDraft({
        id: existing.id,
        name: existing.name,
        description: existing.description || "",
        local_tools: existing.local_tools || [],
        mcp_tools: existing.mcp_tools || [],
        pinned_tools: existing.pinned_tools || [],
        system_prompt_fragment: existing.system_prompt_fragment || "",
        includes: existing.includes || [],
        tags: existing.tags || [],
      });
    }
  }, [existing, isNew]);

  const update = useCallback((patch: Partial<Carapace>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  }, []);

  const handleSave = async () => {
    try {
      if (isNew) {
        await createMut.mutateAsync({
          id: draft.id || "",
          name: draft.name || "",
          description: draft.description || undefined,
          local_tools: draft.local_tools || [],
          mcp_tools: draft.mcp_tools || [],
          pinned_tools: draft.pinned_tools || [],
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes || [],
          tags: draft.tags || [],
        });
        navigate(-1);
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || undefined,
          local_tools: draft.local_tools,
          mcp_tools: draft.mcp_tools,
          pinned_tools: draft.pinned_tools,
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes,
          tags: draft.tags,
        });
        setDirty(false);
      }
    } catch {
      // error handled by mutation
    }
  };

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const handleDelete = () => {
    setShowDeleteConfirm(true);
  };

  const doDelete = async () => {
    setShowDeleteConfirm(false);
    try {
      await deleteMut.mutateAsync(carapaceId!);
      navigate(-1);
    } catch {
      // error shown via mutation state
    }
  };

  const isFileBased =
    existing?.source_type === "file" || existing?.source_type === "integration";

  if (!isNew && isLoading) {
    return <div style={{ marginTop: 60, display: "flex", flexDirection: "row", justifyContent: "center" }}><Spinner /></div>;
  }

  const hasIncludes = (draft.includes || []).length > 0;
  const inputStyle = makeInputStyle(t, isFileBased);
  const textareaStyle = makeTextareaStyle(t, isFileBased);

  return (
    <div style={{ overflow: "auto", flex: 1, background: t.surface }}>
      <PageHeader variant="detail" title={isNew ? "New Capability" : draft.name || "Capability"} backTo="/admin/carapaces" />
      <div style={{ padding: 16, maxWidth: 720 }}>
        {/* Top actions */}
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <button
            type="button"
            onClick={() => navigate(-1)}
            style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <span style={{ color: t.textMuted, fontSize: 13 }}>Back</span>
          </button>
          <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "center" }}>
            <button
              onClick={() => setShowHelp(true)}
              title="Help — what are capabilities?"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: 4,
                display: "flex", flexDirection: "row",
                alignItems: "center",
              }}
            >
              <HelpCircle size={16} color={t.textDim} />
            </button>
            {!isNew && !isFileBased && (
              <button
                type="button"
                onClick={handleDelete}
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  padding: "6px 10px",
                  borderRadius: 6,
                  backgroundColor: t.dangerSubtle,
                  border: `1px solid ${t.dangerBorder}`,
                  cursor: "pointer",
                }}
              >
                <Trash2 size={14} color={t.danger} />
                <span style={{ color: t.danger, fontSize: 12 }}>Delete</span>
              </button>
            )}
            {!isFileBased && (
              <button
                type="button"
                onClick={handleSave}
                disabled={!dirty && !isNew}
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  padding: "6px 12px",
                  borderRadius: 6,
                  backgroundColor: dirty || isNew ? t.accent : t.surfaceBorder,
                  opacity: dirty || isNew ? 1 : 0.5,
                  border: "none",
                  cursor: dirty || isNew ? "pointer" : "default",
                }}
              >
                <Save size={14} color="#fff" />
                <span style={{ color: "#fff", fontSize: 12, fontWeight: 600 }}>
                  {isNew ? "Create" : "Save"}
                </span>
              </button>
            )}
          </div>
        </div>

        {/* Error banner */}
        {(createMut.isError || updateMut.isError || deleteMut.isError) && (
          <div
            style={{
              background: t.dangerSubtle,
              border: `1px solid ${t.dangerBorder}`,
              padding: 10,
              borderRadius: 8,
              marginBottom: 12,
              color: t.danger,
              fontSize: 12,
            }}
          >
            {(createMut.error || updateMut.error || deleteMut.error)?.message ||
              "Operation failed"}
          </div>
        )}

        {/* File-managed banner */}
        {isFileBased && (
          <div
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "flex-start",
              gap: 8,
              background: t.accentSubtle,
              border: `1px solid ${t.accentBorder}`,
              padding: 10,
              borderRadius: 8,
              marginBottom: 16,
              color: t.accent,
              fontSize: 12,
            }}
          >
            <Info size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 } as any} />
            <span>
              This capability is managed by a {existing?.source_type} ({existing?.source_path}).
              Edit the source to make changes.
            </span>
          </div>
        )}

        {/* ─── Identity ─────────────────────────────────── */}
        <Section title="Identity" description="Name, description, and organizational tags">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {isNew && (
              <FormRow label="ID" description="Unique slug identifier (lowercase, hyphens). Cannot be changed after creation.">
                <input
                  value={draft.id || ""}
                  onChange={(e) =>
                    update({ id: e.target.value.toLowerCase().replace(/\s+/g, "-") })
                  }
                  placeholder="e.g. qa-expert"
                  style={inputStyle}
                  onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                  onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
                />
              </FormRow>
            )}

            <FormRow label="Name" description="Display name shown in the UI and bot config.">
              <input
                value={draft.name || ""}
                onChange={(e) => update({ name: e.target.value })}
                placeholder="e.g. QA Expert"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
            </FormRow>

            <FormRow label="Description" description="Brief summary of what this capability provides.">
              <input
                value={draft.description || ""}
                onChange={(e) => update({ description: e.target.value })}
                placeholder="e.g. Full QA workflow — test planning, execution, and reporting"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
            </FormRow>

            <FormRow label="Tags" description="Comma-separated labels for filtering and search.">
              <input
                value={(draft.tags || []).join(", ")}
                onChange={(e) =>
                  update({
                    tags: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. testing, quality"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.tags || []} t={t} color="purple" />
            </FormRow>
          </div>
        </Section>

        {/* ─── Tools ────────────────────────────────────── */}
        <Section
          title="Tools"
          description="Tools the bot gains when this capability is active. Skills are not declared on capabilities — point at them from the system prompt fragment via get_skill('id')."
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <FormRow
              label="Local Tools"
              description="Python tools added to the bot's toolbox — e.g. exec_command, file, web_search."
            >
              <input
                value={(draft.local_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    local_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. exec_command, file, web_search"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.local_tools || []} t={t} color="success" />
            </FormRow>

            <FormRow
              label="Pinned Tools"
              description="Tools that bypass RAG retrieval — always available regardless of query relevance."
            >
              <input
                value={(draft.pinned_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    pinned_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. exec_command"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.pinned_tools || []} t={t} color="warning" />
            </FormRow>

            <FormRow
              label="MCP Servers"
              description="External MCP server names — the bot gains access to all tools from these servers."
            >
              <input
                value={(draft.mcp_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    mcp_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. homeassistant, github"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.mcp_tools || []} t={t} color="accent" />
            </FormRow>
          </div>
        </Section>

        {/* ─── Behavior ─────────────────────────────────── */}
        <Section
          title="Behavior"
          description="System prompt fragment — the 'soul' of this capability"
        >
          <FormRow
            label="System Prompt Fragment"
            description="Markdown-formatted instructions injected into the system prompt. Define workflow steps, priorities, constraints, and decision-making guidelines."
          >
            <textarea
              value={draft.system_prompt_fragment || ""}
              onChange={(e) => update({ system_prompt_fragment: e.target.value })}
              placeholder={"## Expert Mode\n\nWhen activated, follow this workflow:\n1. Assess the situation\n2. Plan your approach\n3. Execute with precision"}
              disabled={isFileBased}
              rows={8}
              style={textareaStyle}
              onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
              onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
            />
            {(draft.system_prompt_fragment || "").length > 0 && (
              <div style={{ fontSize: 10, color: t.textDim, textAlign: "right" }}>
                {draft.system_prompt_fragment!.length} chars
              </div>
            )}
          </FormRow>
        </Section>

        {/* ─── Composition ──────────────────────────────── */}
        <Section
          title="Composition"
          description="Include other capabilities to inherit their tools, skills, and fragments"
        >
          <FormRow
            label="Includes"
            description="Comma-separated capability IDs. Resolved depth-first (max 5 levels, cycle-safe). All tools, skills, and prompt fragments merge in."
          >
            <input
              value={(draft.includes || []).join(", ")}
              onChange={(e) =>
                update({
                  includes: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              placeholder="e.g. code-review, testing"
              disabled={isFileBased}
              style={inputStyle}
              onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
              onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
            />
            <TagPreview items={draft.includes || []} t={t} color="accent" />
          </FormRow>
        </Section>

        {/* ─── Used By ─────────────────────────────────── */}
        {!isNew && usage && usage.length > 0 && (
          <Section title="Used By" description="Bots and channels that reference this capability">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {usage.map((item, i) => (
                <UsageRow key={`${item.type}-${item.id}-${i}`} item={item} t={t} />
              ))}
            </div>
          </Section>
        )}

        {/* ─── Resolved Preview ─────────────────────────── */}
        {!isNew && resolved && (hasIncludes || resolved.local_tools.length > 0) && (
          <div style={{ marginTop: 16 }}>
            <button
              onClick={() => setShowResolved(!showResolved)}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                padding: "8px 0",
                background: "none",
                border: "none",
                cursor: "pointer",
                color: t.text,
              }}
            >
              {showResolved ? (
                <ChevronDown size={14} color={t.textMuted} />
              ) : (
                <ChevronRight size={14} color={t.textMuted} />
              )}
              <Layers size={14} color={t.accent} />
              <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                Resolved Preview
              </span>
              {hasIncludes && (
                <span style={{ fontSize: 11, color: t.textDim }}>
                  ({resolved.resolved_ids.length} capabilit
                  {resolved.resolved_ids.length !== 1 ? "ies" : "y"})
                </span>
              )}
            </button>

            {showResolved && (
              <div
                style={{
                  background: t.surface,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 8,
                  padding: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                {resolved.resolved_ids.length > 1 && (
                  <ResolvedRow label="Includes chain" t={t}>
                    <span
                      style={{
                        fontSize: 11,
                        color: t.textMuted,
                        fontFamily: "monospace",
                      }}
                    >
                      {resolved.resolved_ids.join(" → ")}
                    </span>
                  </ResolvedRow>
                )}
                <ResolvedRow label="Tools" t={t}>
                  <TagPreview items={resolved.local_tools} t={t} color="success" />
                </ResolvedRow>
                {resolved.mcp_tools.length > 0 && (
                  <ResolvedRow label="MCP" t={t}>
                    <TagPreview items={resolved.mcp_tools} t={t} color="accent" />
                  </ResolvedRow>
                )}
                <ResolvedRow label="Pinned" t={t}>
                  <TagPreview items={resolved.pinned_tools} t={t} color="warning" />
                </ResolvedRow>
                <ResolvedRow label="Fragments" t={t}>
                  <span style={{ fontSize: 11, color: t.textMuted }}>
                    {resolved.system_prompt_fragments.length} fragment
                    {resolved.system_prompt_fragments.length !== 1 ? "s" : ""},{" "}
                    {resolved.system_prompt_fragments.reduce(
                      (a, f) => a + f.length,
                      0,
                    )}{" "}
                    chars
                  </span>
                </ResolvedRow>
              </div>
            )}
          </div>
        )}
      </div>

      {showHelp && <CarapaceHelpModal onClose={() => setShowHelp(false)} />}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete Capability"
        message={`Delete capability "${draft.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={doDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function UsageRow({ item, t }: { item: CarapaceUsageItem; t: ThemeTokens }) {
  const Icon = item.type === "bot" ? Bot : item.auto_injected ? Home : Hash;
  const label = item.type === "bot" ? "Bot" : "Channel";
  const href = item.type === "bot"
    ? `/admin/bots/${item.id}`
    : `/channels/${item.id}`;

  return (
    <Link to={href} style={{ textDecoration: "none" }}>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          padding: 8,
          borderRadius: 6,
          backgroundColor: t.surface,
          border: `1px solid ${t.surfaceBorder}`,
          cursor: "pointer",
        }}
      >
        <Icon size={14} color={item.auto_injected ? t.accent : t.textDim} />
        <span style={{ fontSize: 13, color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.name || item.id}
        </span>
        <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
        {item.auto_injected && (
          <span style={{
            display: "inline-flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 3,
            backgroundColor: t.accentSubtle,
            border: `1px solid ${t.accentBorder}`,
            padding: "1px 5px",
            borderRadius: 4,
          }}>
            <Zap size={9} color={t.accent} />
            <span style={{ fontSize: 10, color: t.accent }}>auto-injected</span>
          </span>
        )}
        {item.type === "channel_inherited" && (
          <span style={{ fontSize: 10, color: t.textDim }}>via bot</span>
        )}
      </div>
    </Link>
  );
}

function ResolvedRow({
  label,
  t,
  children,
}: {
  label: string;
  t: ThemeTokens;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim }}>{label}</span>
      {children}
    </div>
  );
}

type TagColor = "purple" | "accent" | "success" | "warning";

function TagPreview({
  items,
  t,
  color,
}: {
  items: string[];
  t: ThemeTokens;
  color: TagColor;
}) {
  if (items.length === 0) return null;
  const colorMap: Record<TagColor, { bg: string; border: string; text: string }> = {
    purple: { bg: t.purpleSubtle, border: t.purpleBorder, text: t.purple },
    accent: { bg: t.accentSubtle, border: t.accentBorder, text: t.accent },
    success: { bg: t.successSubtle, border: t.successBorder, text: t.success },
    warning: { bg: t.warningSubtle, border: t.warningBorder, text: t.warning },
  };
  const c = colorMap[color];
  return (
    <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
      {items.map((item) => (
        <span
          key={item}
          style={{
            fontSize: 11,
            color: c.text,
            background: c.bg,
            border: `1px solid ${c.border}`,
            borderRadius: 4,
            padding: "1px 6px",
          }}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

function makeInputStyle(
  t: ThemeTokens,
  disabled?: boolean,
): React.CSSProperties {
  return {
    background: t.inputBg,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 8,
    padding: "8px 12px",
    color: t.inputText,
    fontSize: 14,
    width: "100%",
    outline: "none",
    transition: "border-color 0.15s",
    opacity: disabled ? 0.6 : 1,
    cursor: disabled ? "not-allowed" : undefined,
  };
}

function makeTextareaStyle(
  t: ThemeTokens,
  disabled?: boolean,
): React.CSSProperties {
  return {
    ...makeInputStyle(t, disabled),
    resize: "vertical" as const,
    fontFamily: "monospace",
    fontSize: 13,
    lineHeight: 1.5,
  };
}

