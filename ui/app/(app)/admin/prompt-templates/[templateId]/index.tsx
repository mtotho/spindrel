import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft, Trash2, Info, FileText, Pencil } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import {
  usePromptTemplate,
  useCreatePromptTemplate,
  useUpdatePromptTemplate,
  useDeletePromptTemplate,
} from "@/src/api/hooks/usePromptTemplates";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { FormRow, TextInput, Section, SelectInput } from "@/src/components/shared/FormControls";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: "#666" }}>{label}</span>
      <span style={{ fontSize: 11, color: "#ccc", fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

export default function PromptTemplateDetailScreen() {
  const { templateId } = useLocalSearchParams<{ templateId: string }>();
  const isNew = templateId === "new";
  const goBack = useGoBack("/admin/prompt-templates");
  const qc = useQueryClient();
  const { data: template, isLoading } = usePromptTemplate(isNew ? undefined : templateId);
  const createMut = useCreatePromptTemplate();
  const updateMut = useUpdatePromptTemplate(templateId);
  const deleteMut = useDeletePromptTemplate();

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const { data: workspaces } = useWorkspaces();

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
      qc.invalidateQueries({ queryKey: ["prompt-templates"] });
      goBack();
    } else {
      if (!name.trim()) return;
      await updateMut.mutateAsync(base as any);
      qc.invalidateQueries({ queryKey: ["prompt-templates"] });
    }
  }, [isNew, name, description, content, category, tags, sourceType, workspaceId, sourcePath, createMut, updateMut, qc, goBack]);

  const handleDelete = useCallback(async () => {
    if (!templateId || !confirm("Delete this template?")) return;
    await deleteMut.mutateAsync(templateId);
    qc.invalidateQueries({ queryKey: ["prompt-templates"] });
    goBack();
  }, [templateId, deleteMut, qc, goBack]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew
    ? (name.trim() && (sourceType === "workspace_file" ? (workspaceId && sourcePath.trim()) : content.trim()))
    : name.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: "1px solid #333", gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}>
          <ChevronLeft size={22} color="#999" />
        </button>
        <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New Template" : "Edit Template"}
        </span>
        <div style={{ flex: 1 }} />
        {!isNew && !isFileManaged && (
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            title="Delete"
            style={{
              display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: "1px solid #7f1d1d", borderRadius: 6,
              background: "transparent", color: "#fca5a5", cursor: "pointer", flexShrink: 0,
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
            background: (!canSave || isFileManaged) ? "#333" : "#3b82f6",
            color: (!canSave || isFileManaged) ? "#666" : "#fff",
            cursor: (!canSave || isFileManaged) ? "not-allowed" : "pointer",
          }}
        >
          {isSaving ? "..." : isNew ? "Create" : "Save"}
        </button>
      </div>

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: "#7f1d1d", color: "#fca5a5", fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* File-managed banner */}
      {isFileManaged && (
        <div style={{
          margin: isWide ? "16px 20px 0" : "12px 12px 0",
          padding: "12px 16px", borderRadius: 8,
          background: "rgba(59,130,246,0.08)", border: "1px solid rgba(59,130,246,0.2)",
          display: "flex", alignItems: "flex-start", gap: 10,
        }}>
          <Info size={14} color="#93c5fd" style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 12, color: "#93c5fd", lineHeight: 1.5 }}>
            This template is managed by a file (
            <code style={{ fontSize: 11, color: "#60a5fa" }}>{template?.source_path}</code>
            ). Edit the source file to make changes.
          </div>
        </div>
      )}

      {/* Workspace file banner */}
      {!isFileManaged && isWorkspaceFile && !isNew && (
        <div style={{
          margin: isWide ? "16px 20px 0" : "12px 12px 0",
          padding: "12px 16px", borderRadius: 8,
          background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)",
          display: "flex", alignItems: "flex-start", gap: 10,
        }}>
          <FileText size={14} color="#86efac" style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 12, color: "#86efac", lineHeight: 1.5 }}>
            Content is sourced from workspace file (
            <code style={{ fontSize: 11, color: "#4ade80" }}>{sourcePath}</code>
            ). Content updates automatically when the file changes.
          </div>
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        ...(isWide ? { flexDirection: "row", flex: 1 } : {}),
      }}>
        {/* Content editor */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: "1px solid #2a2a2a" } : {}),
          display: "flex", flexDirection: "column",
          padding: isWide ? "16px 20px" : "12px 12px",
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#999", marginBottom: 6 }}>
            {isWorkspaceFile ? "Content (from workspace file)" : "Content"}
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            readOnly={isFileManaged || isWorkspaceFile}
            placeholder={isWorkspaceFile ? "Content will be loaded from the workspace file..." : "Template content that will be inserted..."}
            style={{
              flex: 1, minHeight: isWide ? 400 : 250,
              background: (isFileManaged || isWorkspaceFile) ? "#0a0a0a" : "#111",
              border: "1px solid #222", borderRadius: 8,
              padding: 12, fontSize: 13, lineHeight: 1.6,
              color: (isFileManaged || isWorkspaceFile) ? "#888" : "#e5e5e5",
              fontFamily: "monospace", resize: "vertical",
              outline: "none",
              opacity: (isFileManaged || isWorkspaceFile) ? 0.7 : 1,
            }}
          />
        </div>

        {/* Metadata panel */}
        <div style={{
          ...(isWide ? { flex: 1.5, minWidth: 260 } : {}),
          padding: isWide ? "16px 20px" : "12px 12px",
          borderTop: isWide ? "none" : "1px solid #2a2a2a",
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
                    <FormRow label="File Path" description="Path within the workspace (e.g. bots/coder/prompts/nightly.md)">
                      <TextInput
                        value={sourcePath}
                        onChangeText={setSourcePath}
                        placeholder="e.g. prompts/nightly.md"
                      />
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
              <FormRow label="Tags" description="Comma-separated tags">
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
      </ScrollView>
    </View>
  );
}
