import { ExternalLink, FileText, FolderKanban, KeyRound, Layers, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCreateProject,
  useCreateProjectFromBlueprint,
  useProjectBlueprints,
  useProjects,
} from "@/src/api/hooks/useProjects";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, SelectInput, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

export default function ProjectsIndex() {
  const navigate = useNavigate();
  const { data: projects, isLoading } = useProjects();
  const { data: blueprints } = useProjectBlueprints();
  const { data: workspaces } = useWorkspaces();
  const createProject = useCreateProject();
  const createFromBlueprint = useCreateProjectFromBlueprint();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("common/projects");
  const [selectedBlueprintId, setSelectedBlueprintId] = useState("");
  const defaultWorkspaceId = workspaces?.[0]?.id;

  const attachedCount = useMemo(
    () => (projects ?? []).reduce((total, project) => total + (project.attached_channel_count ?? 0), 0),
    [projects],
  );
  const blueprintOptions = useMemo(
    () => [
      { label: "No blueprint", value: "" },
      ...(blueprints ?? []).map((blueprint) => ({
        label: blueprint.name,
        value: blueprint.id,
      })),
    ],
    [blueprints],
  );
  const selectedBlueprint = useMemo(
    () => (blueprints ?? []).find((blueprint) => blueprint.id === selectedBlueprintId) ?? null,
    [blueprints, selectedBlueprintId],
  );

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedRoot = rootPath.trim().replace(/^\/+|\/+$/g, "");
    if (!trimmedName || !defaultWorkspaceId) return;
    if (selectedBlueprintId) {
      createFromBlueprint.mutate({
        blueprint_id: selectedBlueprintId,
        workspace_id: defaultWorkspaceId,
        name: trimmedName,
        root_path: trimmedRoot || null,
      }, {
        onSuccess: () => {
          setName("");
          setRootPath("common/projects");
          setSelectedBlueprintId("");
          setCreating(false);
        },
      });
      return;
    }
    if (!trimmedRoot) return;
    createProject.mutate({
      workspace_id: defaultWorkspaceId,
      name: trimmedName,
      root_path: trimmedRoot,
    }, {
      onSuccess: () => {
        setName("");
        setRootPath("common/projects");
        setCreating(false);
      },
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="Projects"
        subtitle="Shared working roots for files, terminals, search, and harness runs."
        right={
          <ActionButton
            label={creating ? "Close" : "New Project"}
            icon={!creating ? <Plus size={14} /> : undefined}
            variant={creating ? "secondary" : "primary"}
            onPress={() => setCreating((value) => !value)}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-5 py-5 md:px-6">
          {creating && (
            <div data-testid="project-workspace-create-form" className="flex flex-col gap-3 rounded-md bg-surface-raised/35 px-3 py-3">
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,1fr)_auto] md:items-end">
                <FormRow label="Project name">
                  <TextInput
                    value={name}
                    onChangeText={setName}
                    placeholder="Project name"
                  />
                </FormRow>
                <FormRow label="Blueprint">
                  <SelectInput
                    value={selectedBlueprintId}
                    onChange={(value) => {
                      setSelectedBlueprintId(value);
                      setRootPath(value ? "" : "common/projects");
                    }}
                    options={blueprintOptions}
                  />
                </FormRow>
                <FormRow label="Root path">
                  <TextInput
                    value={rootPath}
                    onChangeText={setRootPath}
                    placeholder={selectedBlueprintId ? "Use blueprint pattern" : "common/projects"}
                  />
                </FormRow>
                <ActionButton
                  label="Create"
                  icon={<Plus size={14} />}
                  onPress={submit}
                  disabled={
                    !name.trim()
                    || (!selectedBlueprintId && !rootPath.trim())
                    || !defaultWorkspaceId
                    || createProject.isPending
                    || createFromBlueprint.isPending
                  }
                />
              </div>
              {selectedBlueprint && (
                <div data-testid="project-create-blueprint-preview" className="grid gap-2 md:grid-cols-3">
                  <SettingsControlRow
                    compact
                    leading={<Layers size={14} />}
                    title={selectedBlueprint.name}
                    description={<span className="font-mono">/{selectedBlueprint.default_root_path_pattern ?? "common/projects/{slug}"}</span>}
                    meta={<QuietPill label="blueprint" />}
                  />
                  <SettingsControlRow
                    compact
                    leading={<FileText size={14} />}
                    title="Starter surface"
                    description={`${selectedBlueprint.folders?.length ?? 0} folders, ${Object.keys(selectedBlueprint.files ?? {}).length} files`}
                    meta={<QuietPill label={`${Object.keys(selectedBlueprint.knowledge_files ?? {}).length} knowledge`} />}
                  />
                  <SettingsControlRow
                    compact
                    leading={<KeyRound size={14} />}
                    title="Declarations"
                    description={`${selectedBlueprint.repos?.length ?? 0} repos, ${Object.keys(selectedBlueprint.env ?? {}).length} env keys`}
                    meta={<QuietPill label={`${selectedBlueprint.required_secrets?.length ?? 0} secrets`} />}
                  />
                </div>
              )}
            </div>
          )}

          <Section
            title="Project Roots"
            description="A Project is a named root inside the shared workspace. Channels can attach to the same root without sharing bot-private memory."
          >
            <div data-testid="project-workspace-list" className="flex flex-col gap-2">
              <SettingsGroupLabel
                label="Current projects"
                count={projects?.length ?? 0}
                icon={<FolderKanban size={13} className="text-text-dim" />}
                action={<QuietPill label={`${attachedCount} attached channels`} maxWidthClass="max-w-none" />}
              />
              {isLoading ? (
                <div className="py-10"><Spinner size={18} /></div>
              ) : (projects ?? []).length === 0 ? (
                <EmptyState
                  message="No Projects yet. Create one to share a working root across channels."
                  action={<ActionButton label="New Project" icon={<Plus size={14} />} onPress={() => setCreating(true)} />}
                />
              ) : (
                (projects ?? []).map((project) => (
                  <div key={project.id} data-testid="project-workspace-row">
                    <SettingsControlRow
                      onClick={() => navigate(`/admin/projects/${project.id}`)}
                      leading={<FolderKanban size={15} />}
                      title={project.name}
                      description={<span className="font-mono">/{project.root_path}</span>}
                      meta={
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                          <QuietPill label={project.slug} maxWidthClass="max-w-[180px]" />
                          <span>{project.attached_channel_count ?? 0} attached</span>
                        </span>
                      }
                    />
                  </div>
                ))
              )}
            </div>
          </Section>

          <Section
            title="Blueprints"
            description="Reusable recipes for new Project roots. They define starter files, knowledge files, repo declarations, env defaults, and secret binding slots."
            action={<ActionButton label="Manage Blueprints" icon={<ExternalLink size={14} />} onPress={() => navigate("/admin/projects/blueprints")} />}
          >
            <div className="flex flex-col gap-3">
              <div data-testid="project-blueprint-list" className="flex flex-col gap-2">
                <SettingsGroupLabel
                  label="Available blueprints"
                  count={blueprints?.length ?? 0}
                  icon={<Layers size={13} className="text-text-dim" />}
                />
                {(blueprints ?? []).length === 0 ? (
                  <EmptyState message="No blueprints yet. Add one here or create one through the Projects API." />
                ) : (
                  (blueprints ?? []).map((blueprint) => (
                    <SettingsControlRow
                      key={blueprint.id}
                      onClick={() => navigate(`/admin/projects/blueprints/${blueprint.id}`)}
                      leading={<Layers size={15} />}
                      title={blueprint.name}
                      description={<span className="font-mono">/{blueprint.default_root_path_pattern ?? "common/projects/{slug}"}</span>}
                      meta={
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                          <QuietPill label={blueprint.slug} maxWidthClass="max-w-[180px]" />
                          <span>{blueprint.required_secrets?.length ?? 0} secrets</span>
                        </span>
                      }
                    />
                  ))
                )}
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
