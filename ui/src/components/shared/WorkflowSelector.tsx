/**
 * Rich workflow selector with search, grouping by source, and metadata display.
 */
import { useMemo } from "react";
import { Zap } from "lucide-react";
import { useWorkflows } from "../../api/hooks/useWorkflows";
import type { Workflow } from "../../types/api";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

interface Props {
  value: string | null;
  onChange: (workflowId: string | null) => void;
}

interface WorkflowOption extends SelectDropdownOption {
  workflow: Workflow;
}

function sourceLabel(sourceType: string): string {
  if (sourceType === "file") return "File-managed";
  if (sourceType === "integration") return "Integration";
  return "User created";
}

function sourceOrder(sourceType: string): number {
  if (sourceType === "manual") return 0;
  if (sourceType === "file") return 1;
  if (sourceType === "integration") return 2;
  return 3;
}

export function WorkflowSelector({ value, onChange }: Props) {
  const { data: workflows } = useWorkflows();

  const options = useMemo<WorkflowOption[]>(() => {
    return [...(workflows ?? [])]
      .sort((a, b) => sourceOrder(a.source_type) - sourceOrder(b.source_type) || (a.name || a.id).localeCompare(b.name || b.id))
      .map((workflow) => ({
        value: workflow.id,
        label: workflow.name || workflow.id,
        description: workflow.description ?? undefined,
        group: workflow.source_type,
        groupLabel: sourceLabel(workflow.source_type),
        searchText: `${workflow.id} ${workflow.name} ${workflow.description ?? ""} ${workflow.tags.join(" ")} ${workflow.source_type}`,
        workflow,
      }));
  }, [workflows]);

  if (workflows && workflows.length === 0) {
    return (
      <div className="rounded-md bg-surface-raised/40 px-3 py-4 text-center">
        <div className="text-[13px] font-medium text-text-muted">No workflows available</div>
        <div className="mt-1 text-[11px] text-text-dim">Create a workflow in Admin &rarr; Workflows first.</div>
      </div>
    );
  }

  return (
    <SelectDropdown
      value={value}
      onChange={(next) => onChange(next)}
      onClear={() => onChange(null)}
      allowClear={!!value}
      options={options}
      placeholder="Select a workflow..."
      loading={!workflows}
      loadingLabel="Loading workflows..."
      searchable
      searchPlaceholder="Search workflows..."
      emptyLabel="No workflows found"
      popoverWidth="wide"
      leadingIcon={<Zap size={14} className="shrink-0 text-text-dim" />}
      renderValue={(option) => {
        const workflow = (option as WorkflowOption).workflow;
        return (
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-text">{workflow.name || workflow.id}</span>
            {workflow.source_type !== "manual" && (
              <span className="shrink-0 rounded-full bg-accent/[0.08] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-accent">
                {workflow.source_type}
              </span>
            )}
          </span>
        );
      }}
      renderOption={(option, state) => {
        const workflow = (option as WorkflowOption).workflow;
        return (
          <>
            <Zap size={13} className={`mt-0.5 shrink-0 ${state.selected ? "text-accent" : "text-text-dim"}`} />
            <span className="min-w-0 flex-1">
              <span className={`flex min-w-0 items-center gap-1.5 text-[12px] font-semibold ${state.selected ? "text-accent" : "text-text"}`}>
                <span className="truncate">{workflow.name || workflow.id}</span>
                {workflow.source_type !== "manual" && (
                  <span className="shrink-0 rounded-full bg-accent/[0.08] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-accent">
                    {workflow.source_type}
                  </span>
                )}
              </span>
              {workflow.description && (
                <span className="mt-0.5 block truncate text-[11px] text-text-dim">{workflow.description}</span>
              )}
              <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] text-text-dim">
                <span>{workflow.steps?.length ?? 0} step{(workflow.steps?.length ?? 0) !== 1 ? "s" : ""}</span>
                {workflow.tags?.slice(0, 3).map((tag) => (
                  <span key={tag} className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[9px] text-text-dim">
                    {tag}
                  </span>
                ))}
              </span>
            </span>
          </>
        );
      }}
    />
  );
}
