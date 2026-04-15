import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useCallback, useRef } from "react";

import { useParams } from "react-router-dom";
import { Trash2, Info, FileText, Sparkles } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  usePromptTemplate,
  useCreatePromptTemplate,
  useUpdatePromptTemplate,
  useDeletePromptTemplate,
} from "@/src/api/hooks/usePromptTemplates";
import { useGeneratePrompt } from "@/src/api/hooks/usePrompts";
import { useWorkspaces, useWorkspaceFileContent } from "@/src/api/hooks/useWorkspaces";
import { FormRow, TextInput, Section, SelectInput } from "@/src/components/shared/FormControls";
import { WorkspaceFilePicker } from "@/src/components/shared/WorkspaceFilePicker";
import { useThemeTokens } from "@/src/theme/tokens";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
      <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

export default function PromptTemplateDetailScreen() {
  const t = useThemeTokens();
  const { templateId } = useParams<{ templateId: string }>();
  const isNew = templateId === "new";
  const goBack = useGoBack("/admin/prompt-templates");
  const { data: template, isLoading } = usePromptTemplate(isNew ? undefined : templateId);
  const createMut = useCreatePromptTemplate();
  const updateMut = useUpdatePromptTemplate(templateId);
  const deleteMut = useDeletePromptTemplate();

  const { width } = useWindowSize();
  const isWide = width >= 768;

  const { data: workspaces } = useWorkspaces();
  const generateMut = useGeneratePrompt();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [hasSelection, setHasSelection] = useState(false);
  const [genFlash, setGenFlash] = useState<"success" | "error" | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [sourceType, setSourceType] = useState<"manual" | "workspace_file">("manual");
  const [workspaceId, setWorkspaceId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [initialized, setInitialized] = useState(isNew);

  if (template && !initialized) {
    setName(template.name || "");
    setDescription(template.description || "");
    setContent(template.content || "");
    setCategory(template.category || "");
    setTags((template.tags || []).join(", "));
    setSourceType((template.source_type as any) || "manual");
    setWorkspaceId(template.workspace_id || "");
    setSourcePath(template.source_path || "");
    setInitialized(true);
  }

  const isFileManaged = template?.source_type === "file";
  const isWorkspaceFile = sourceType === "workspace_file";

  const handleSelectionChange = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    setHasSelection(ta.selectionStart !== ta.selectionEnd);
  }, []);

  const handleGenerate = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta || ta.selectionStart === ta.selectionEnd) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selectedText = content.substring(start, end);
    const surrounding = content.substring(0, start) + "[SELECTION]" + content.substring(end);

    generateMut.mutate(
      {
        user_input: selectedText,
        mode: "inline",
        surrounding_context: surrounding,
      },
      {
        onSuccess: (data) => {
          const newContent = content.substring(0, start) + data.prompt + content.substring(end);
          setContent(newContent);
          setHasSelection(false);
          setGenFlash("success");
          setTimeout(() => setGenFlash(null), 1200);
          requestAnimationFrame(() => {
            if (textareaRef.current) {
              const newEnd = start + data.prompt.length;
              textareaRef.current.selectionStart = newEnd;
              textareaRef.current.selectionEnd = newEnd;
              textareaRef.current.focus();
            }
          });
        },
        onError: () => {
          setGenFlash("error");
          setTimeout(() => setGenFlash(null), 1500);
        },
      }
    );
  }, [content, generateMut]);

  // Preview workspace file content
  const { data: wsFilePreview, isLoading: wsFileLoading } = useWorkspaceFileContent(
    isWorkspaceFile ? workspaceId || undefined : undefined,
    isWorkspaceFile && sourcePath ? sourcePath : null,
  );

  const handleSave = useCallback(async () => {
    const tagList = tags.split(",").map((t) => t.trim()).filter(Boolean);
    const base: Record<string, any> = {
      name: name.trim(),
      description: description.trim() || undefined,
      category: category.trim() || undefined,
      tags: tagList,
    };

    if (sourceType === "workspace_file") {
      base.source_type = "workspace_file";
      base.workspace_id = workspaceId || undefined;
      base.source_path = sourcePath.trim() || undefined;
    } else {
      base.source_type = "manual";
      base.content = content;
    }

    if (isNew) {
      if (!name.trim()) return;
      if (sourceType === "manual" && !content.trim()) return;
      if (sourceType === "workspace_file" && (!workspaceId || !sourcePath.trim())) return;
      await createMut.mutateAsync(base as any);
      goBack();
    } else {
      if (!name.trim()) return;
      await updateMut.mutateAsync(base as any);
    }
  }, [isNew, name, description, content, category, tags, sourceType, workspaceId, sourcePath, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!templateId || !confirm("Delete this template?")) return;
    await deleteMut.mutateAsync(templateId);
    goBack();
  }, [templateId, deleteMut, goBack]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew
    ? (name.trim() && (sourceType === "workspace_file" ? (workspaceId && sourcePath.trim()) : content.trim()))
    : name.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Prompt Templates"
        backTo="/admin/prompt-templates"
        title={isNew ? "New Template" : "Edit Template"}
        right={
          <>
            {!isNew && !isFileManaged && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                title="Delete"
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: isWide ? 6 : 0,
                  padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
                  border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                  background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
                }}
              >
                <Trash2 size={14} />
                {isWide && "Delete"}
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={isSaving || !canSave || isFileManaged}
              style={{
                padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
                border: "none", borderRadius: 6, flexShrink: 0,
                background: (!canSave || isFileManaged) ? t.surfaceBorder : t.accent,
                color: (!canSave || isFileManaged) ? t.textDim : "#fff",
                cursor: (!canSave || isFileManaged) ? "not-allowed" : "pointer",
              }}
            >
              {isSaving ? "..." : isNew ? "Create" : "Save"}
            </button>
          </>
        }
      />

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* File-managed banner */}
      {isFileManaged && (
        <div style={{
          margin: isWide ? "16px 20px 0" : "12px 12px 0",
          padding: "12px 16px", borderRadius: 8,
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 10,
        }}>
          <Info size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 12, color: t.accent, lineHeight: 1.5 }}>
            This template is managed by a file (
            <code style={{ fontSize: 11, fontWeight: 600 }}>{template?.source_path}</code>
            ). Edit the source file to make changes.
          </div>
        </div>
      )}

      {/* Workspace file banner */}
      {!isFileManaged && isWorkspaceFile && !isNew && (
        <div style={{
          margin: isWide ? "16px 20px 0" : "12px 12px 0",
          padding: "12px 16px", borderRadius: 8,
          background: t.successSubtle, border: `1px solid ${t.success}33`,
          display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 10,
        }}>
          <FileText size={14} color={t.success} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 12, color: t.success, lineHeight: 1.5 }}>
            Content is sourced from workspace file (
            <code style={{ fontSize: 11, color: t.success }}>{sourcePath}</code>
            ). Content updates automatically when the file changes.
          </div>
        </div>
      )}

      {/* Body */}
      <div style={{ flex: 1, ...(isWide ? { flexDirection: "row" as const } : {}) }}>
        {/* Content editor */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: `1px solid ${t.surfaceOverlay}` } : {}),
          display: "flex", flexDirection: "column",
          padding: isWide ? "16px 20px" : "12px 12px",
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6,
            display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center",
          }}>
            <span>{isWorkspaceFile ? "Content Preview" : "Content"}</span>
            {!isFileManaged && !isWorkspaceFile && (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: t.textDim, fontWeight: 400 }}>
                  {hasSelection ? "" : "Select text to generate"}
                </span>
                <button
                  onClick={handleGenerate}
                  disabled={!hasSelection || generateMut.isPending}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                    background: "none",
                    border: `1px solid ${hasSelection ? (genFlash === "success" ? t.success : genFlash === "error" ? t.danger : t.accent) : t.surfaceBorder}`,
                    borderRadius: 4,
                    color: hasSelection ? (genFlash === "success" ? t.success : genFlash === "error" ? t.danger : t.accent) : t.textDim,
                    fontSize: 11, padding: "2px 8px", fontWeight: 500,
                    cursor: hasSelection && !generateMut.isPending ? "pointer" : "default",
                    opacity: hasSelection ? 1 : 0.5,
                    transition: "all 0.15s",
                  }}
                >
                  <Sparkles size={10} />
                  {generateMut.isPending ? "Generating..." : genFlash === "success" ? "Done!" : genFlash === "error" ? "Failed" : "Generate"}
                </button>
              </div>
            )}
          </div>
          {isWorkspaceFile ? (
            <div style={{
              flex: 1, minHeight: isWide ? 400 : 250,
              background: t.surface, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8,
              padding: 12, overflowY: "auto",
            }}>
              {!sourcePath ? (
                <div style={{ color: t.textDim, fontSize: 12, fontStyle: "italic" }}>
                  Select a file from the workspace to preview its content.
                </div>
              ) : wsFileLoading ? (
                <div style={{ color: t.textDim, fontSize: 12 }}>Loading file content...</div>
              ) : wsFilePreview?.content ? (
                <pre style={{
                  color: t.text, fontSize: 12, fontFamily: "monospace",
                  whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.5,
                  wordBreak: "break-all",
                }}>
                  {wsFilePreview.content}
                </pre>
              ) : (
                <div style={{ color: t.textDim, fontSize: 12, fontStyle: "italic" }}>
                  {sourcePath ? "(empty file)" : "No file selected"}
                </div>
              )}
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onSelect={handleSelectionChange}
              onMouseUp={handleSelectionChange}
              onKeyUp={handleSelectionChange}
              readOnly={isFileManaged}
              placeholder="Template content that will be inserted..."
              style={{
                flex: 1, minHeight: isWide ? 400 : 250,
                background: isFileManaged ? t.surface : t.inputBg,
                border: `1px solid ${isFileManaged ? t.surfaceBorder : t.surfaceOverlay}`, borderRadius: 8,
                padding: 12, fontSize: 13, lineHeight: 1.6,
                color: isFileManaged ? t.textMuted : t.text,
                fontFamily: "monospace", resize: "vertical",
                outline: "none",
              }}
            />
          )}
        </div>

        {/* Metadata panel */}
        <div style={{
          ...(isWide ? { flex: 1.5, minWidth: 260 } : {}),
          padding: isWide ? "16px 20px" : "12px 12px",
          borderTop: isWide ? "none" : `1px solid ${t.surfaceOverlay}`,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Source type (only for new or non-file-managed) */}
            {!isFileManaged && (
              <Section title="Source">
                <FormRow label="Source Type">
                  <SelectInput
                    value={sourceType}
                    onChange={(v) => setSourceType(v as "manual" | "workspace_file")}
                    options={[
                      { label: "Manual", value: "manual" },
                      { label: "Workspace File", value: "workspace_file" },
                    ]}
                  />
                </FormRow>
                {isWorkspaceFile && (
                  <>
                    <FormRow label="Workspace">
                      <SelectInput
                        value={workspaceId}
                        onChange={setWorkspaceId}
                        options={[
                          { label: "Select workspace...", value: "" },
                          ...(workspaces || []).map((w) => ({
                            label: w.name,
                            value: w.id,
                          })),
                        ]}
                      />
                    </FormRow>
                    <FormRow label="File" description="Browse and select a file from the workspace">
                      {workspaceId ? (
                        <WorkspaceFilePicker
                          workspaceId={workspaceId}
                          value={sourcePath}
                          onChange={setSourcePath}
                          fileFilter=".md"
                        />
                      ) : (
                        <div style={{ fontSize: 11, color: t.textDim }}>Select a workspace first</div>
                      )}
                    </FormRow>
                  </>
                )}
              </Section>
            )}

            <Section title="Details">
              <FormRow label="Name">
                <TextInput
                  value={name}
                  onChangeText={isFileManaged ? () => {} : setName}
                  placeholder="e.g. Coding Assistant Prompt"
                  style={isFileManaged ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                />
              </FormRow>
              <FormRow label="Description" description="Short summary of what this template is for">
                <TextInput
                  value={description}
                  onChangeText={isFileManaged ? () => {} : setDescription}
                  placeholder="Optional description"
                  style={isFileManaged ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                />
              </FormRow>
              <FormRow label="Category" description="Group templates by category (e.g. coding, creative, analysis)">
                <TextInput
                  value={category}
                  onChangeText={isFileManaged ? () => {} : setCategory}
                  placeholder="e.g. coding"
                  style={isFileManaged ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                />
              </FormRow>
              <FormRow label="Tags" description="Comma-separated tags for filtering and search">
                <TextInput
                  value={tags}
                  onChangeText={isFileManaged ? () => {} : setTags}
                  placeholder="e.g. python, api, backend"
                  style={isFileManaged ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                />
              </FormRow>
            </Section>

            {template && (
              <Section title="Info">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <InfoRow label="ID" value={template.id} />
                  <InfoRow label="Source" value={template.source_type} />
                  {template.source_path && <InfoRow label="Path" value={template.source_path} />}
                  <InfoRow label="Scope" value={template.workspace_id ? "Workspace" : "Global"} />
                  <InfoRow label="Created" value={fmtDate(template.created_at)} />
                  <InfoRow label="Updated" value={fmtDate(template.updated_at)} />
                </div>
              </Section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
