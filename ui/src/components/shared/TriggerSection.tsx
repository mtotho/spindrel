/**
 * TriggerSection — segmented control for Schedule / Event / Manual task triggers.
 *
 * Used in TaskCreateModal and TaskEditor to configure how a task is triggered.
 */
import { useState, useMemo } from "react";
import { FormRow, SelectInput } from "./FormControls";
import { ScheduledAtPicker, RecurrencePicker, ScheduleSummary } from "./SchedulingPickers";
import { useTriggerEvents, type TriggerEventSource } from "@/src/api/hooks/useTasks";

export type TriggerType = "schedule" | "event" | "manual";

export interface TriggerConfig {
  type: TriggerType;
  event_source?: string;
  event_type?: string;
  event_action?: string;
  event_filter?: Record<string, string>;
}

interface TriggerSectionProps {
  triggerConfig: TriggerConfig;
  onTriggerConfigChange: (tc: TriggerConfig) => void;
  scheduledAt: string;
  onScheduledAtChange: (v: string) => void;
  recurrence: string;
  onRecurrenceChange: (v: string) => void;
}

const TRIGGER_TYPES: { label: string; value: TriggerType }[] = [
  { label: "Schedule", value: "schedule" },
  { label: "Event", value: "event" },
  { label: "Manual", value: "manual" },
];

export function TriggerSection({
  triggerConfig,
  onTriggerConfigChange,
  scheduledAt,
  onScheduledAtChange,
  recurrence,
  onRecurrenceChange,
}: TriggerSectionProps) {
  const triggerType = triggerConfig.type ?? "schedule";
  const { data: triggerEventsData } = useTriggerEvents();
  const sources = triggerEventsData?.sources ?? [];

  const selectedSource = sources.find((s) => s.source === triggerConfig.event_source);
  const selectedEvents = selectedSource?.events ?? [];

  return (
    <div className="flex gap-3">
      {/* Segmented control */}
      <div className="flex flex-row gap-0.5 bg-surface-raised rounded-[10px] border border-surface-border p-[3px]">
        {TRIGGER_TYPES.map((tt) => (
          <button
            key={tt.value}
            onClick={() => onTriggerConfigChange({ ...triggerConfig, type: tt.value })}
            className={`flex flex-1 items-center justify-center py-[7px] text-xs font-semibold border-none cursor-pointer rounded-[7px] transition-all duration-150 ${
              triggerType === tt.value
                ? "bg-accent text-white shadow-sm"
                : "bg-transparent text-text-muted hover:text-text"
            }`}
          >
            {tt.label}
          </button>
        ))}
      </div>

      {/* Schedule fields */}
      {triggerType === "schedule" && (
        <>
          <ScheduledAtPicker value={scheduledAt} onChange={onScheduledAtChange} />
          <RecurrencePicker value={recurrence} onChange={onRecurrenceChange} />
          <ScheduleSummary scheduledAt={scheduledAt} recurrence={recurrence} />
        </>
      )}

      {/* Event trigger fields */}
      {triggerType === "event" && (
        <EventTriggerFields
          triggerConfig={triggerConfig}
          onTriggerConfigChange={onTriggerConfigChange}
          sources={sources}
          selectedSource={selectedSource}
          selectedEvents={selectedEvents}
        />
      )}

      {/* Manual */}
      {triggerType === "manual" && (
        <div className="px-4 py-3.5 rounded-[10px] bg-surface-raised border border-surface-border text-xs text-text-muted leading-relaxed">
          Run on demand only — no schedule or event trigger. Use the API or admin UI to execute.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event trigger sub-form
// ---------------------------------------------------------------------------

/** Group sources by integration type for <optgroup> display. */
function useGroupedSourceOptions(sources: TriggerEventSource[]) {
  return useMemo(() => {
    // Separate system from integration sources
    const systemSources = sources.filter((s) => s.source === "system");
    const integrationSources = sources.filter((s) => s.source !== "system");

    // Group integration sources by integration_type
    const groups = new Map<string, TriggerEventSource[]>();
    for (const s of integrationSources) {
      const key = s.integration_type ?? s.source;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(s);
    }

    return { systemSources, groups };
  }, [sources]);
}

function EventTriggerFields({
  triggerConfig,
  onTriggerConfigChange,
  sources,
  selectedSource,
  selectedEvents,
}: {
  triggerConfig: TriggerConfig;
  onTriggerConfigChange: (tc: TriggerConfig) => void;
  sources: TriggerEventSource[];
  selectedSource: TriggerEventSource | undefined;
  selectedEvents: { type: string; label: string }[];
}) {
  const [filterKey, setFilterKey] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const { systemSources, groups } = useGroupedSourceOptions(sources);

  const eventOptions = [
    { label: "All events", value: "" },
    ...selectedEvents.map((e) => ({ label: e.label, value: e.type })),
  ];

  const filters = triggerConfig.event_filter ?? {};
  const filterEntries = Object.entries(filters);

  const addFilter = () => {
    if (!filterKey.trim() || !filterValue.trim()) return;
    const updated = { ...filters, [filterKey.trim()]: filterValue.trim() };
    onTriggerConfigChange({ ...triggerConfig, event_filter: updated });
    setFilterKey("");
    setFilterValue("");
  };

  const removeFilter = (key: string) => {
    const updated = { ...filters };
    delete updated[key];
    onTriggerConfigChange({
      ...triggerConfig,
      event_filter: Object.keys(updated).length > 0 ? updated : undefined,
    });
  };

  const handleSourceChange = (v: string) => {
    onTriggerConfigChange({
      ...triggerConfig,
      event_source: v || undefined,
      event_type: undefined,
      event_action: undefined,
      event_filter: undefined,
    });
  };

  if (sources.length === 0) {
    return (
      <div className="px-4 py-3.5 rounded-[10px] bg-surface-raised border border-surface-border text-xs text-text-dim leading-normal">
        No event sources available. Install integrations or configure channel bindings to enable event triggers.
      </div>
    );
  }

  return (
    <div className="flex gap-2.5">
      <FormRow label="Source" description="Which integration or system emits the event">
        <select
          value={triggerConfig.event_source ?? ""}
          onChange={(e) => handleSourceChange(e.target.value)}
          className="w-full px-2.5 py-2 text-xs bg-input border border-surface-border rounded-lg text-text outline-none focus:border-accent appearance-none cursor-pointer"
        >
          <option value="">Select source...</option>
          {systemSources.length > 0 && (
            <optgroup label="System">
              {systemSources.map((s) => (
                <option key={s.source} value={s.source}>{s.label}</option>
              ))}
            </optgroup>
          )}
          {Array.from(groups.entries()).map(([intType, groupSources]) => (
            <optgroup key={intType} label={intType.charAt(0).toUpperCase() + intType.slice(1)}>
              {groupSources.map((s) => (
                <option key={s.source} value={s.source} disabled={s.disabled}>
                  {s.label}{s.disabled ? " (not configured)" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </FormRow>

      {triggerConfig.event_source && (
        <FormRow label="Event" description="Filter to a specific event type, or leave on 'All'">
          <SelectInput
            value={triggerConfig.event_type ?? ""}
            onChange={(v) => onTriggerConfigChange({
              ...triggerConfig,
              event_type: v || undefined,
              event_action: undefined,
            })}
            options={eventOptions}
          />
        </FormRow>
      )}

      {/* Filter conditions */}
      {triggerConfig.event_source && (
        <div className="flex gap-1.5">
          <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
            Filter conditions
          </div>
          {filterEntries.map(([k, v]) => (
            <div key={k} className="flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-raised border border-surface-border">
              <span className="text-[11px] text-accent font-bold font-mono">{k}</span>
              <span className="text-[10px] text-text-dim/60">=</span>
              <span className="text-[11px] text-text flex-1 font-mono">{v}</span>
              <button
                onClick={() => removeFilter(k)}
                className="bg-transparent border-none cursor-pointer text-sm text-text-dim/50 px-0.5 leading-none hover:text-danger hover:opacity-100"
              >
                &times;
              </button>
            </div>
          ))}
          <div className="flex flex-row gap-1.5 items-center">
            <input
              type="text"
              value={filterKey}
              onChange={(e) => setFilterKey(e.target.value)}
              placeholder="key"
              className="flex-1 px-2 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
            />
            <input
              type="text"
              value={filterValue}
              onChange={(e) => setFilterValue(e.target.value)}
              placeholder="value"
              onKeyDown={(e) => { if (e.key === "Enter") addFilter(); }}
              className="flex-[2] px-2 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
            />
            <button
              onClick={addFilter}
              disabled={!filterKey.trim() || !filterValue.trim()}
              className="px-2.5 py-1.5 text-[11px] font-semibold rounded-md border-none cursor-pointer bg-accent text-white disabled:opacity-40"
            >
              Add
            </button>
          </div>
          {filterEntries.length === 0 && (
            <div className="text-[11px] text-text-dim">
              No filters — triggers on every matching event
            </div>
          )}
        </div>
      )}
    </div>
  );
}
