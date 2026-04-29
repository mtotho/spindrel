import { FileText, FolderOpen, GitBranch, Hash, KeyRound, Layers, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  useDeleteProjectBlueprint,
  useProjectBlueprint,
  useUpdateProjectBlueprint,
} from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, TextInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

type KeyValueRow = { id: string; key: string; value: string };
type RepoRow = { id: string; name: string; url: string; path: string; branch: string };

function uid() {
  return Math.random().toString(36).slice(2);
}

function recordToRows(record: Record<string, string> | undefined): KeyValueRow[] {
  return Object.entries(record ?? {}).map(([key, value]) => ({ id: uid(), key, value: String(value) }));
}

function rowsToRecord(rows: KeyValueRow[]): Record<string, string> {
  return Object.fromEntries(
    rows
      .map((row) => [row.key.trim(), row.value] as const)
      .filter(([key]) => key.length > 0),
  );
}

function listToText(items: string[] | undefined): string {
  return (items ?? []).join("\n");
}

function textToList(value: string): string[] {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function reposToRows(repos: Array<Record<string, any>> | undefined): RepoRow[] {
  return (repos ?? []).map((repo) => ({
    id: uid(),
    name: String(repo.name ?? ""),
    url: String(repo.url ?? ""),
    path: String(repo.path ?? ""),
    branch: String(repo.branch ?? ""),
  }));
}

function rowsToRepos(rows: RepoRow[]): Array<Record<string, string>> {
  return rows.flatMap((row) => {
    const repo = {
      name: row.name.trim(),
      url: row.url.trim(),
      path: row.path.trim(),
      branch: row.branch.trim(),
    };
    if (!repo.name && !repo.url && !repo.path && !repo.branch) return [];
    return [Object.fromEntries(Object.entries(repo).filter(([, value]) => value))];
  });
}

function TextArea({
  value,
  onChangeText,
  placeholder,
  rows = 5,
}: {
  value: string;
  onChangeText: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(event) => onChangeText(event.target.value)}
      className="w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none transition-colors placeholder:text-text-dim focus:border-accent focus:ring-2 focus:ring-accent/40"
    />
  );
}

function KeyValueEditor({
  label,
  rows,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
  multiline = false,
}: {
  label: string;
  rows: KeyValueRow[];
  onChange: (rows: KeyValueRow[]) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
  multiline?: boolean;
}) {
  const updateRow = (id: string, patch: Partial<KeyValueRow>) => {
    onChange(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };
  return (
    <div className="flex flex-col gap-2">
      <SettingsGroupLabel
        label={label}
        count={rows.length}
        action={
          <ActionButton
            label="Add"
            icon={<Plus size={13} />}
            size="small"
            onPress={() => onChange([...rows, { id: uid(), key: "", value: "" }])}
          />
        }
      />
      {rows.length === 0 ? (
        <EmptyState message="No entries declared." />
      ) : (
        rows.map((row) => (
          <div key={row.id} className="grid gap-2 rounded-md bg-surface-raised/40 px-3 py-2.5 md:grid-cols-[minmax(160px,0.4fr)_minmax(0,1fr)_auto]">
            <TextInput
              value={row.key}
              onChangeText={(value) => updateRow(row.id, { key: value })}
              placeholder={keyPlaceholder}
            />
            {multiline ? (
              <TextArea
                value={row.value}
                onChangeText={(value) => updateRow(row.id, { value })}
                placeholder={valuePlaceholder}
                rows={4}
              />
            ) : (
              <TextInput
                value={row.value}
                onChangeText={(value) => updateRow(row.id, { value })}
                placeholder={valuePlaceholder}
              />
            )}
            <ActionButton
              label="Remove"
              icon={<Trash2 size={13} />}
              size="small"
              variant="secondary"
              onPress={() => onChange(rows.filter((item) => item.id !== row.id))}
            />
          </div>
        ))
      )}
    </div>
  );
}

export default function ProjectBlueprintDetail() {
  const navigate = useNavigate();
  const { blueprintId } = useParams<{ blueprintId: string }>();
  const { data: blueprint, isLoading } = useProjectBlueprint(blueprintId);
  const updateBlueprint = useUpdateProjectBlueprint(blueprintId);
  const deleteBlueprint = useDeleteProjectBlueprint();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [rootPattern, setRootPattern] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptFilePath, setPromptFilePath] = useState("");
  const [foldersText, setFoldersText] = useState("");
  const [requiredSecretsText, setRequiredSecretsText] = useState("");
  const [files, setFiles] = useState<KeyValueRow[]>([]);
  const [knowledgeFiles, setKnowledgeFiles] = useState<KeyValueRow[]>([]);
  const [envRows, setEnvRows] = useState<KeyValueRow[]>([]);
  const [repos, setRepos] = useState<RepoRow[]>([]);

  useEffect(() => {
    if (!blueprint) return;
    setName(blueprint.name ?? "");
    setSlug(blueprint.slug ?? "");
    setDescription(blueprint.description ?? "");
    setRootPattern(blueprint.default_root_path_pattern ?? "common/projects/{slug}");
    setPrompt(blueprint.prompt ?? "");
    setPromptFilePath(blueprint.prompt_file_path ?? "");
    setFoldersText(listToText(blueprint.folders));
    setRequiredSecretsText(listToText(blueprint.required_secrets));
    setFiles(recordToRows(blueprint.files));
    setKnowledgeFiles(recordToRows(blueprint.knowledge_files));
    setEnvRows(recordToRows(blueprint.env));
    setRepos(reposToRows(blueprint.repos));
  }, [blueprint]);

  const payload = useMemo(() => ({
    name: name.trim(),
    slug: slug.trim(),
    description: description.trim() || null,
    default_root_path_pattern: rootPattern.trim() || "common/projects/{slug}",
    prompt: prompt.trim() || null,
    prompt_file_path: promptFilePath.trim() || null,
    folders: textToList(foldersText),
    files: rowsToRecord(files),
    knowledge_files: rowsToRecord(knowledgeFiles),
    env: rowsToRecord(envRows),
    repos: rowsToRepos(repos),
    required_secrets: textToList(requiredSecretsText),
  }), [description, envRows, files, foldersText, knowledgeFiles, name, prompt, promptFilePath, repos, requiredSecretsText, rootPattern, slug]);

  const savedPayload = useMemo(() => {
    if (!blueprint) return null;
    return {
      name: blueprint.name,
      slug: blueprint.slug,
      description: blueprint.description ?? null,
      default_root_path_pattern: blueprint.default_root_path_pattern ?? "common/projects/{slug}",
      prompt: blueprint.prompt ?? null,
      prompt_file_path: blueprint.prompt_file_path ?? null,
      folders: blueprint.folders ?? [],
      files: blueprint.files ?? {},
      knowledge_files: blueprint.knowledge_files ?? {},
      env: blueprint.env ?? {},
      repos: blueprint.repos ?? [],
      required_secrets: blueprint.required_secrets ?? [],
    };
  }, [blueprint]);

  const dirty = savedPayload ? JSON.stringify(payload) !== JSON.stringify(savedPayload) : false;

  const save = () => {
    if (!name.trim() || updateBlueprint.isPending) return;
    updateBlueprint.mutate(payload);
  };

  const remove = () => {
    if (!blueprintId || deleteBlueprint.isPending) return;
    if (!window.confirm("Delete this Project Blueprint? Existing Projects keep their applied snapshot.")) return;
    deleteBlueprint.mutate(blueprintId, {
      onSuccess: () => navigate("/admin/projects/blueprints"),
    });
  };

  if (isLoading || !blueprint) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        title={blueprint.name}
        subtitle={`/${blueprint.default_root_path_pattern ?? "common/projects/{slug}"}`}
        backTo="/admin/projects/blueprints"
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <SaveStatusPill
              tone={updateBlueprint.isPending ? "pending" : dirty ? "dirty" : "idle"}
              label={updateBlueprint.isPending ? "Saving" : "Unsaved"}
            />
            <ActionButton
              label="Save"
              icon={<Save size={14} />}
              disabled={!dirty || !name.trim() || updateBlueprint.isPending}
              onPress={save}
            />
          </div>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div data-testid="project-blueprint-editor" className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
          <Section
            title="Identity"
            description="The reusable recipe name and default Project root pattern."
          >
            <div className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-2">
              <FormRow label="Name">
                <TextInput value={name} onChangeText={setName} placeholder="Node service" />
              </FormRow>
              <FormRow label="Slug">
                <TextInput value={slug} onChangeText={setSlug} placeholder="node-service" />
              </FormRow>
              <FormRow label="Root pattern" description="Supports {slug}, {name}, {project_slug}, and {project_name}.">
                <TextInput value={rootPattern} onChangeText={setRootPattern} placeholder="common/projects/{slug}" />
              </FormRow>
              <FormRow label="Description">
                <TextInput value={description} onChangeText={setDescription} placeholder="Reusable setup for a service repo" />
              </FormRow>
            </div>
          </Section>

          <Section
            title="Instructions"
            description="Prompt content applied to Projects created from this Blueprint."
          >
            <div className="flex flex-col gap-3">
              <PromptEditor
                value={prompt}
                onChange={setPrompt}
                label="Blueprint prompt"
                placeholder="Optional Project prompt copied into new Projects..."
                helpText="Copied into the Project at creation time; existing Projects keep their snapshot."
                rows={6}
                fieldType="project_prompt"
                generateContext={`Project Blueprint: ${blueprint.name}`}
              />
              <FormRow label="Prompt file">
                <TextInput value={promptFilePath} onChangeText={setPromptFilePath} placeholder=".spindrel/project-prompt.md" />
              </FormRow>
            </div>
          </Section>

          <Section
            title="Starter Surface"
            description="Folders and starter files created in the Project root when this Blueprint is applied."
          >
            <div className="grid gap-4 md:grid-cols-[minmax(0,0.45fr)_minmax(0,1fr)]">
              <FormRow label="Folders" description="One folder per line.">
                <TextArea
                  value={foldersText}
                  onChangeText={setFoldersText}
                  placeholder={".spindrel\n.spindrel/knowledge-base\ndocs"}
                  rows={9}
                />
              </FormRow>
              <KeyValueEditor
                label="Starter files"
                rows={files}
                onChange={setFiles}
                keyPlaceholder="README.md"
                valuePlaceholder="# New Project"
                multiline
              />
            </div>
          </Section>

          <Section
            title="Knowledge Files"
            description="Files created under the Project knowledge base folder."
          >
            <KeyValueEditor
              label="Knowledge files"
              rows={knowledgeFiles}
              onChange={setKnowledgeFiles}
              keyPlaceholder="overview.md"
              valuePlaceholder="Shared Project knowledge..."
              multiline
            />
          </Section>

          <Section
            title="Repo Declarations"
            description="Recorded for the Project snapshot. Cloning and setup execution are intentionally deferred."
          >
            <div className="flex flex-col gap-2">
              <SettingsGroupLabel
                label="Repositories"
                count={repos.length}
                icon={<GitBranch size={13} className="text-text-dim" />}
                action={
                  <ActionButton
                    label="Add"
                    icon={<Plus size={13} />}
                    size="small"
                    onPress={() => setRepos([...repos, { id: uid(), name: "", url: "", path: "", branch: "" }])}
                  />
                }
              />
              {repos.length === 0 ? (
                <EmptyState message="No repositories declared." />
              ) : repos.map((repo) => (
                <div key={repo.id} className="grid gap-2 rounded-md bg-surface-raised/40 px-3 py-2.5 md:grid-cols-[minmax(0,0.55fr)_minmax(0,1fr)_minmax(0,0.45fr)_minmax(0,0.35fr)_auto]">
                  <TextInput value={repo.name} onChangeText={(value) => setRepos(repos.map((item) => item.id === repo.id ? { ...item, name: value } : item))} placeholder="agent-server" />
                  <TextInput value={repo.url} onChangeText={(value) => setRepos(repos.map((item) => item.id === repo.id ? { ...item, url: value } : item))} placeholder="https://github.com/org/repo.git" />
                  <TextInput value={repo.path} onChangeText={(value) => setRepos(repos.map((item) => item.id === repo.id ? { ...item, path: value } : item))} placeholder="agent-server" />
                  <TextInput value={repo.branch} onChangeText={(value) => setRepos(repos.map((item) => item.id === repo.id ? { ...item, branch: value } : item))} placeholder="main" />
                  <ActionButton label="Remove" icon={<Trash2 size={13} />} size="small" variant="secondary" onPress={() => setRepos(repos.filter((item) => item.id !== repo.id))} />
                </div>
              ))}
            </div>
          </Section>

          <Section
            title="Env And Secrets"
            description="Env defaults are copied as declarations. Required secrets create binding slots on new Projects."
          >
            <div className="grid gap-4 md:grid-cols-2">
              <KeyValueEditor
                label="Env defaults"
                rows={envRows}
                onChange={setEnvRows}
                keyPlaceholder="NODE_ENV"
                valuePlaceholder="development"
              />
              <FormRow label="Required secrets" description="One secret name per line.">
                <TextArea
                  value={requiredSecretsText}
                  onChangeText={setRequiredSecretsText}
                  placeholder={"GITHUB_TOKEN\nNPM_TOKEN"}
                  rows={9}
                />
              </FormRow>
            </div>
          </Section>

          <Section title="Blueprint Summary">
            <div className="grid gap-2 md:grid-cols-4">
              <SettingsControlRow compact leading={<FolderOpen size={14} />} title="Folders" description={`${payload.folders.length}`} />
              <SettingsControlRow compact leading={<FileText size={14} />} title="Starter files" description={`${Object.keys(payload.files).length}`} />
              <SettingsControlRow compact leading={<Hash size={14} />} title="Env keys" description={`${Object.keys(payload.env).length}`} />
              <SettingsControlRow compact leading={<KeyRound size={14} />} title="Secrets" description={`${payload.required_secrets.length}`} />
            </div>
          </Section>

          <Section
            title="Danger Zone"
            description="Deleting a Blueprint does not delete Projects already created from it."
            action={
              <ActionButton
                label="Delete Blueprint"
                icon={<Trash2 size={14} />}
                variant="danger"
                disabled={deleteBlueprint.isPending}
                onPress={remove}
              />
            }
          >
            <SettingsControlRow
              leading={<Layers size={14} />}
              title="Existing Projects keep their snapshot"
              description="The live Blueprint reference is cleared, but Project settings, materialized files, and stored metadata remain."
              meta={<QuietPill label="non-destructive" />}
            />
          </Section>
        </div>
      </div>
    </div>
  );
}
