/**
 * TriggerSection — segmented control for Schedule / Event / Manual task triggers.
 *
 * Used in TaskCreateModal and TaskEditor to configure how a task is triggered.
 */
import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, Zap, Server, Radio } from "lucide-react";
import { ScheduledAtPicker, RecurrencePicker, ScheduleSummary } from "./SchedulingPickers";
import { useTriggerEvents, type TriggerEventSource, type TriggerEventOption } from "@/src/api/hooks/useTasks";
import { prettyIntegrationName } from "@/src/utils/format";

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

// ---------------------------------------------------------------------------
// Integration color map — brand colors for visual identity
// ---------------------------------------------------------------------------
const INTEGRATION_COLORS: Record<string, { border: string; bg: string; dot: string }> = {
  system:      { border: "#6b7280", bg: "rgba(107,114,128,0.08)", dot: "#6b7280" },
  slack:       { border: "#4A154B", bg: "rgba(74,21,75,0.10)",    dot: "#E01E5A" },
  github:      { border: "#8b949e", bg: "rgba(139,148,158,0.08)", dot: "#8b949e" },
  discord:     { border: "#5865F2", bg: "rgba(88,101,242,0.10)",  dot: "#5865F2" },
  wyoming:     { border: "#14b8a6", bg: "rgba(20,184,166,0.10)",  dot: "#14b8a6" },
  gmail:       { border: "#EA4335", bg: "rgba(234,67,53,0.10)",   dot: "#EA4335" },
  frigate:     { border: "#0ea5e9", bg: "rgba(14,165,233,0.10)",  dot: "#0ea5e9" },
  bluebubbles: { border: "#34D399", bg: "rgba(52,211,153,0.10)",  dot: "#34D399" },
};

const DEFAULT_COLOR = { border: "#6b7280", bg: "rgba(107,114,128,0.08)", dot: "#6b7280" };

function getColor(intType: string) {
  return INTEGRATION_COLORS[intType] ?? DEFAULT_COLOR;
}

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
// Types for grouped source data
// ---------------------------------------------------------------------------
interface SourceGroup {
  intType: string;
  label: string;
  eventCount: number;
  /** The integration-wide "any" source */
  anySource: TriggerEventSource | null;
  /** Per-binding sources */
  bindings: TriggerEventSource[];
  disabled: boolean;
}

// ---------------------------------------------------------------------------
// Build grouped source data from flat sources array
// ---------------------------------------------------------------------------
function useSourceGroups(sources: TriggerEventSource[]): SourceGroup[] {
  return useMemo(() => {
    const groups = new Map<string, SourceGroup>();

    for (const s of sources) {
      const intType = s.source === "system" ? "system" : (s.integration_type ?? s.source);

      if (!groups.has(intType)) {
        groups.set(intType, {
          intType,
          label: intType === "system" ? "System Events" : prettyIntegrationName(intType),
          eventCount: s.events.length,
          anySource: null,
          bindings: [],
          disabled: false,
        });
      }

      const group = groups.get(intType)!;
      group.eventCount = Math.max(group.eventCount, s.events.length);

      if (s.source === "system" || s.source === intType) {
        group.anySource = s;
        group.disabled = !!s.disabled;
      } else {
        group.bindings.push(s);
      }
    }

    return Array.from(groups.values());
  }, [sources]);
}

// ---------------------------------------------------------------------------
// Check if all events in a source share the same category
// ---------------------------------------------------------------------------
function hasUniformCategory(events: TriggerEventOption[]): boolean {
  if (events.length === 0) return false;
  const first = events[0].category;
  return events.every((e) => e.category === first);
}

// ---------------------------------------------------------------------------
// Event trigger sub-form — card picker
// ---------------------------------------------------------------------------
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
  selectedEvents: TriggerEventOption[];
}) {
  const [filterKey, setFilterKey] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const groups = useSourceGroups(sources);

  const filters = triggerConfig.event_filter ?? {};
  const filterEntries = Object.entries(filters);

  // Hide category labels when every event shares the same one (e.g. all "webhook")
  const uniformCategory = hasUniformCategory(selectedEvents);

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

  const selectSource = (source: string) => {
    onTriggerConfigChange({
      ...triggerConfig,
      event_source: source || undefined,
      event_type: undefined,
      event_action: undefined,
      event_filter: undefined,
    });
  };

  const isSelected = (sourceId: string) => triggerConfig.event_source === sourceId;

  const isGroupSelected = (group: SourceGroup) => {
    if (group.anySource && isSelected(group.anySource.source)) return true;
    return group.bindings.some((b) => isSelected(b.source));
  };

  const toggleGroup = (intType: string, group: SourceGroup) => {
    if (group.disabled) return;
    // System or no bindings: select the "any" source directly
    if (intType === "system" || group.bindings.length === 0) {
      if (group.anySource) {
        selectSource(isSelected(group.anySource.source) ? "" : group.anySource.source);
      }
      return;
    }
    setExpandedGroup(expandedGroup === intType ? null : intType);
  };

  if (sources.length === 0) {
    return (
      <div className="px-4 py-3.5 rounded-[10px] bg-surface-raised border border-surface-border text-xs text-text-dim leading-normal">
        No event sources available. Install integrations or configure channel bindings to enable event triggers.
      </div>
    );
  }

  return (
    <div className="flex gap-4">
      {/* Source card picker */}
      <div className="flex gap-1">
        <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider mb-1">
          Source
        </div>

        {groups.map((group) => {
          const color = getColor(group.intType);
          const expanded = expandedGroup === group.intType;
          const groupSel = isGroupSelected(group);
          const isSystem = group.intType === "system";
          const hasBindings = group.bindings.length > 0;

          return (
            <div key={group.intType}>
              {/* Card */}
              <button
                onClick={() => toggleGroup(group.intType, group)}
                disabled={group.disabled}
                className={`flex flex-row items-center gap-2.5 w-full px-3 py-2 rounded-lg border text-left transition-all duration-150 cursor-pointer ${
                  group.disabled
                    ? "opacity-30 cursor-not-allowed border-surface-border bg-surface-raised"
                    : groupSel
                    ? "border-accent/40 bg-accent/[0.04]"
                    : "border-surface-border bg-surface-raised hover:border-text-dim/20"
                }`}
                style={{
                  borderLeftWidth: 3,
                  borderLeftColor: group.disabled ? "transparent" : color.border,
                }}
              >
                {/* Icon */}
                <div
                  className="flex items-center justify-center w-6 h-6 rounded shrink-0"
                  style={{ backgroundColor: color.bg }}
                >
                  {isSystem ? (
                    <Server size={12} style={{ color: color.dot }} />
                  ) : (
                    <Zap size={12} style={{ color: color.dot }} />
                  )}
                </div>

                {/* Text */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-row items-center gap-2">
                    <span className={`text-[12px] font-semibold truncate ${group.disabled ? "text-text-dim" : "text-text"}`}>
                      {group.label}
                    </span>
                    <span className="text-[10px] text-text-dim/70 tabular-nums shrink-0">
                      {group.eventCount}
                    </span>
                  </div>
                  {group.disabled ? (
                    <div className="text-[10px] text-text-dim mt-px">No bindings</div>
                  ) : hasBindings ? (
                    <div className="text-[10px] text-text-dim mt-px">
                      {group.bindings.length} binding{group.bindings.length !== 1 ? "s" : ""}
                    </div>
                  ) : isSystem ? (
                    <div className="text-[10px] text-text-dim mt-px">Lifecycle hooks</div>
                  ) : null}
                </div>

                {/* Right side: chevron or selection dot */}
                {hasBindings && !group.disabled ? (
                  <div className="shrink-0 text-text-dim/50">
                    {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  </div>
                ) : !group.disabled && groupSel ? (
                  <div className="w-2 h-2 rounded-full bg-accent shrink-0" />
                ) : null}
              </button>

              {/* Expanded bindings */}
              {expanded && hasBindings && (
                <div
                  className="flex gap-px mt-px ml-4 pl-3 border-l"
                  style={{ borderLeftColor: color.border + "30" }}
                >
                  {/* "Any" option */}
                  {group.anySource && (
                    <BindingItem
                      label={`Any ${group.label} binding`}
                      selected={isSelected(group.anySource.source)}
                      onClick={() => selectSource(
                        isSelected(group.anySource!.source) ? "" : group.anySource!.source
                      )}
                      color={color}
                      isWildcard
                    />
                  )}
                  {/* Individual bindings */}
                  {group.bindings.map((b) => (
                    <BindingItem
                      key={b.source}
                      label={b.label}
                      selected={isSelected(b.source)}
                      onClick={() => selectSource(isSelected(b.source) ? "" : b.source)}
                      color={color}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Event type selector — only after a source is picked */}
      {triggerConfig.event_source && selectedEvents.length > 0 && (
        <div className="flex gap-1.5">
          <div className="flex flex-row items-center gap-2 mb-0.5">
            <span className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
              Event type
            </span>
            {!triggerConfig.event_type && (
              <span className="text-[10px] text-text-dim/60 normal-case tracking-normal font-normal">
                Listening to all events
              </span>
            )}
          </div>
          <div className="flex flex-row gap-1 flex-wrap">
            {selectedEvents.map((e) => (
              <EventPill
                key={e.type}
                label={e.label}
                description={e.description}
                category={uniformCategory ? undefined : e.category}
                selected={triggerConfig.event_type === e.type}
                onClick={() => onTriggerConfigChange({
                  ...triggerConfig,
                  event_type: triggerConfig.event_type === e.type ? undefined : e.type,
                  event_action: undefined,
                })}
              />
            ))}
          </div>
        </div>
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
            <div className="text-[11px] text-text-dim/60 italic">
              No filters — triggers on every matching event
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Binding item — selectable row within an expanded group
// ---------------------------------------------------------------------------
function BindingItem({
  label,
  selected,
  onClick,
  color,
  isWildcard,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
  color: { border: string; bg: string; dot: string };
  isWildcard?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-row items-center gap-2 w-full px-2.5 py-1.5 rounded-md text-left transition-all duration-100 cursor-pointer border ${
        selected
          ? "border-accent/30 bg-accent/[0.06]"
          : "border-transparent hover:bg-surface-overlay/50"
      }`}
    >
      {/* Radio dot */}
      <div className={`w-3 h-3 rounded-full border-[1.5px] shrink-0 flex items-center justify-center transition-colors ${
        selected ? "border-accent" : "border-text-dim/25"
      }`}>
        {selected && <div className="w-1.5 h-1.5 rounded-full bg-accent" />}
      </div>

      {/* Icon for wildcard */}
      {isWildcard && (
        <Radio size={11} className={selected ? "text-accent/70" : "text-text-dim/40"} />
      )}

      {/* Label */}
      <span className={`text-[11px] truncate ${
        selected ? "text-text font-medium" : isWildcard ? "text-text-dim" : "text-text-muted"
      }`}>
        {label}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Event pill — toggleable pill for event type selection
// ---------------------------------------------------------------------------
function EventPill({
  label,
  description,
  category,
  selected,
  onClick,
}: {
  label: string;
  description?: string;
  category?: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={description}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border transition-all duration-100 cursor-pointer ${
        selected
          ? "bg-accent/[0.12] text-accent border-accent/30"
          : "bg-transparent text-text-muted border-surface-border hover:border-text-dim/30 hover:text-text"
      }`}
    >
      {category && (
        <span className={`text-[9px] uppercase tracking-wider font-semibold ${
          selected ? "text-accent/50" : "text-text-dim/50"
        }`}>
          {category}
        </span>
      )}
      {label}
    </button>
  );
}
