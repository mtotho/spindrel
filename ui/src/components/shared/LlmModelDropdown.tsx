import { useMemo, useState } from "react";
import { Brain, Download, Loader2 } from "lucide-react";

import {
  useDownloadEmbeddingModel,
  useEmbeddingModelGroups,
  useModelGroups,
} from "../../api/hooks/useModels";
import type { LlmModel, ModelGroup } from "../../types/api";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

interface Props {
  value: string;
  onChange: (modelId: string, providerId?: string | null) => void;
  placeholder?: string;
  label?: string;
  allowClear?: boolean;
  /** Where to anchor the dropdown relative to the trigger. Kept for compatibility; the shared dropdown auto-flips. */
  anchor?: "bottom" | "top";
  /** "llm" (default) fetches /models; "embedding" fetches /embedding-models (includes local fastembed). */
  variant?: "llm" | "embedding";
  /** When set, only highlight the model in the matching provider group. */
  selectedProviderId?: string | null;
  className?: string;
}

interface ModelOption extends SelectDropdownOption {
  model: LlmModel;
  providerId: string | null;
  providerName: string;
}

function modelOptionKey(modelId: string, providerId?: string | null): string {
  return `${providerId ?? "default"}::${modelId}`;
}

function buildModelOptions(groups: ModelGroup[] | undefined): ModelOption[] {
  return (groups ?? []).flatMap((group) =>
    group.models.map((model) => ({
      value: modelOptionKey(model.id, group.provider_id ?? null),
      label: model.id,
      description: model.display !== model.id ? model.display : undefined,
      group: group.provider_name,
      groupLabel: group.provider_name,
      searchText: `${model.id} ${model.display} ${group.provider_name}`,
      disabled: model.download_status === "downloading",
      model,
      providerId: group.provider_id ?? null,
      providerName: group.provider_name,
    })),
  );
}

function selectedKeyFor(options: ModelOption[], value: string, selectedProviderId?: string | null): string | null {
  if (!value) return null;
  const match = options.find((option) => {
    if (option.model.id !== value) return false;
    return selectedProviderId === undefined || option.providerId === (selectedProviderId ?? null);
  });
  return match?.value ?? null;
}

function ModelStatusBadge({
  model,
  onDownload,
  isDownloadPending,
}: {
  model: LlmModel;
  onDownload: (id: string) => void;
  isDownloadPending: boolean;
}) {
  if (!model.download_status) return null;

  if (model.download_status === "cached") {
    return <span className="h-2 w-2 shrink-0 rounded-full bg-success" title="Downloaded" />;
  }

  if (model.download_status === "downloading") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-text-dim">
        <Loader2 size={12} className="animate-spin" />
        downloading
      </span>
    );
  }

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5">
      {model.size_mb != null && <span className="text-[10px] text-text-dim">{model.size_mb} MB</span>}
      <span
        role="button"
        tabIndex={-1}
        title="Download model"
        onClick={(event) => {
          event.stopPropagation();
          onDownload(model.id);
        }}
        className={
          `inline-flex h-6 w-6 items-center justify-center rounded-md text-accent transition-colors ` +
          `hover:bg-accent/[0.08] ${isDownloadPending ? "pointer-events-none opacity-50" : ""}`
        }
      >
        <Download size={12} />
      </span>
    </span>
  );
}

function ModelOptionRow({
  option,
  selected,
  onDownload,
  isDownloadPending,
}: {
  option: ModelOption;
  selected: boolean;
  onDownload: (id: string) => void;
  isDownloadPending: boolean;
}) {
  return (
    <>
      <span className="min-w-0 flex-1">
        <span className={`flex min-w-0 items-center gap-1.5 text-[13px] font-medium ${selected ? "text-accent" : "text-text"}`}>
          <span className="truncate">{option.model.id}</span>
          {option.model.supports_reasoning && (
            <span
              title="Supports reasoning / effort budget"
              className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent/[0.08] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-accent"
            >
              <Brain size={9} />
              reasoning
            </span>
          )}
        </span>
        {option.model.display !== option.model.id && (
          <span className="mt-0.5 block truncate text-[11px] text-text-dim">{option.model.display}</span>
        )}
      </span>
      <ModelStatusBadge
        model={option.model}
        onDownload={onDownload}
        isDownloadPending={isDownloadPending}
      />
    </>
  );
}

interface ContentProps {
  value: string;
  selectedProviderId?: string | null;
  onSelect: (modelId: string, providerId?: string | null) => void;
  variant?: "llm" | "embedding";
  autoFocusSearch?: boolean;
}

/**
 * Just the popover body (search + grouped list) of the model dropdown.
 * Used by compact composer controls that provide their own anchoring.
 */
export function LlmModelDropdownContent({
  value,
  selectedProviderId,
  onSelect,
  variant = "llm",
  autoFocusSearch = true,
}: ContentProps) {
  const [search, setSearch] = useState("");
  const llmQuery = useModelGroups();
  const embeddingQuery = useEmbeddingModelGroups();
  const { data: groups, isLoading } = variant === "embedding" ? embeddingQuery : llmQuery;
  const downloadMutation = useDownloadEmbeddingModel();
  const options = useMemo(() => buildModelOptions(groups), [groups]);
  const selectedKey = selectedKeyFor(options, value, selectedProviderId);
  const query = search.trim().toLowerCase();
  const filtered = query
    ? options.filter((option) => (option.searchText ?? "").toLowerCase().includes(query))
    : options;

  return (
    <div className="flex max-h-[340px] flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised ring-1 ring-black/10">
      <div className="shrink-0 p-2">
        <input
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search models..."
          autoFocus={autoFocusSearch}
          className="min-h-[34px] w-full rounded-md bg-input px-2.5 text-[12px] text-text outline-none placeholder:text-text-dim focus:ring-2 focus:ring-accent/25"
        />
      </div>
      <div className="min-h-0 overflow-y-auto py-1">
        {isLoading ? (
          <div className="px-3 py-4 text-[12px] text-text-dim">Loading models...</div>
        ) : filtered.length === 0 ? (
          <div className="px-3 py-4 text-center text-[12px] text-text-dim">No models found</div>
        ) : (
          filtered.map((option, index) => {
            const previous = filtered[index - 1];
            const selected = option.value === selectedKey;
            const showGroup = option.group !== previous?.group;
            return (
              <div key={option.value}>
                {showGroup && (
                  <div className="sticky top-0 z-10 bg-surface-raised px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                    {option.groupLabel}
                  </div>
                )}
                <button
                  type="button"
                  disabled={option.disabled}
                  onClick={() => onSelect(option.model.id, option.providerId)}
                  className={
                    `flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors disabled:cursor-default disabled:opacity-60 ` +
                    (selected ? "bg-accent/[0.07]" : "hover:bg-surface-overlay/45")
                  }
                >
                  <ModelOptionRow
                    option={option}
                    selected={selected}
                    onDownload={(id) => downloadMutation.mutate(id)}
                    isDownloadPending={downloadMutation.isPending}
                  />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export function LlmModelDropdown({
  value,
  onChange,
  placeholder = "Select model...",
  label,
  allowClear = true,
  variant = "llm",
  selectedProviderId,
  className = "",
}: Props) {
  const llmQuery = useModelGroups();
  const embeddingQuery = useEmbeddingModelGroups();
  const { data: groups, isLoading } = variant === "embedding" ? embeddingQuery : llmQuery;
  const downloadMutation = useDownloadEmbeddingModel();
  const modelOptions = useMemo(() => buildModelOptions(groups), [groups]);
  const selectedKey = selectedKeyFor(modelOptions, value, selectedProviderId);
  const options = useMemo(() => {
    if (!value || selectedKey) return modelOptions;
    return [
      {
        value: modelOptionKey(value, selectedProviderId ?? null),
        label: value,
        searchText: value,
        model: { id: value, display: value },
        providerId: selectedProviderId ?? null,
        providerName: "Selected",
      } satisfies ModelOption,
      ...modelOptions,
    ];
  }, [modelOptions, selectedKey, selectedProviderId, value]);
  const effectiveValue = selectedKey ?? (value ? modelOptionKey(value, selectedProviderId ?? null) : null);

  return (
    <div className={`flex w-full flex-col gap-1 ${className}`}>
      {label && <div className="text-[12px] text-text-dim">{label}</div>}
      <SelectDropdown
        value={effectiveValue}
        onChange={(_, option) => {
          const modelOption = option as ModelOption;
          onChange(modelOption.model.id, modelOption.providerId);
        }}
        onClear={() => onChange("", null)}
        allowClear={allowClear}
        options={options}
        placeholder={value || placeholder}
        loading={isLoading}
        searchable
        searchPlaceholder="Search models..."
        emptyLabel="No models found"
        popoverWidth={520}
        maxHeight={340}
        renderValue={(option) => {
          const modelOption = option as ModelOption;
          return modelOption.model.id;
        }}
        renderOption={(option, state) => (
          <ModelOptionRow
            option={option as ModelOption}
            selected={state.selected}
            onDownload={(id) => downloadMutation.mutate(id)}
            isDownloadPending={downloadMutation.isPending}
          />
        )}
      />
    </div>
  );
}
