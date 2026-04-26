import { useState } from "react";
import { Bot, ChevronDown, ChevronRight } from "lucide-react";

import {
  useSpatialBotPolicy,
  useUpdateSpatialBotPolicy,
  type SpatialBotPolicy,
} from "@/src/api/hooks/useWorkspaceSpatial";
import { FormRow, Toggle } from "@/src/components/shared/FormControls";
import { QuietPill, StatusBadge } from "@/src/components/shared/SettingsControls";

const INPUT_CLASS =
  "w-full bg-input border border-input-border rounded-md px-3 py-2 text-[13px] text-text " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 transition-colors";

export function SpatialPolicyStatusRow({
  channelId,
  botId,
  botName,
  label,
}: {
  channelId: string;
  botId: string;
  botName: string;
  label: string;
}) {
  const { data: policy } = useSpatialBotPolicy(channelId, botId);
  return (
    <div className="grid min-h-[38px] grid-cols-[20px_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md bg-surface-raised/35 px-3 py-1.5">
      <Bot size={14} className="text-text-dim" />
      <span className="min-w-0 truncate text-[13px] font-medium text-text">{botName}</span>
      <QuietPill label={label} title={label} />
      {policy?.enabled ? <StatusBadge label="spatial on" variant="success" /> : <StatusBadge label="off" />}
    </div>
  );
}

export function SpatialPolicyCard({
  channelId,
  botId,
  botName,
  label,
  defaultExpanded = false,
}: {
  channelId: string;
  botId: string;
  botName: string;
  label: string;
  defaultExpanded?: boolean;
}) {
  const { data: policy } = useSpatialBotPolicy(channelId, botId);
  const update = useUpdateSpatialBotPolicy(channelId, botId);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const p = policy;
  const patch = (body: Partial<SpatialBotPolicy>) => update.mutate(body);
  const unitsFor = (steps: number) => `${steps} × ${p?.step_world_units ?? 0} = ${(p?.step_world_units ?? 0) * steps} world units`;
  return (
    <div className="overflow-hidden rounded-md bg-surface-raised/40">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="grid min-h-[38px] w-full grid-cols-[16px_20px_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
      >
        {expanded ? <ChevronDown size={12} className="text-text-dim" /> : <ChevronRight size={12} className="text-text-dim" />}
        <Bot size={14} className="text-text-dim" />
        <span className="min-w-0 truncate text-[13px] font-medium text-text">{botName}</span>
        <QuietPill label={label} title={label} />
        {p?.enabled ? <StatusBadge label="spatial on" variant="success" /> : <StatusBadge label="off" />}
      </button>
      {expanded && p && (
        <div className="flex flex-col gap-3 border-t border-surface-border px-3 pt-2 pb-3">
          <FormRow label="Spatial awareness" description="Inject nearby canvas context into this bot's channel runs.">
            <Toggle value={p.enabled} onChange={(enabled) => patch({ enabled })} />
          </FormRow>
          <FormRow label="Allow bot movement">
            <Toggle value={p.allow_movement} onChange={(allow_movement) => patch({ allow_movement })} />
          </FormRow>
          <FormRow label="Allow object tugging" description="Lets the bot move very nearby canvas objects. Tugs create channel notices.">
            <Toggle
              value={p.allow_moving_spatial_objects}
              onChange={(allow_moving_spatial_objects) => patch({ allow_moving_spatial_objects })}
            />
          </FormRow>
          <FormRow label="Allow widget management" description="Lets the bot create, move, resize, and remove spatial widgets it owns.">
            <Toggle
              value={p.allow_spatial_widget_management}
              onChange={(allow_spatial_widget_management) => patch({ allow_spatial_widget_management })}
            />
          </FormRow>
          <FormRow label="Allow nearby inspection" description="Read-only summaries for nearby channels, bots, and widgets.">
            <Toggle value={p.allow_nearby_inspect} onChange={(allow_nearby_inspect) => patch({ allow_nearby_inspect })} />
          </FormRow>
          <FormRow label="Allow map view" description="Read-only viewport summaries of the whole canvas at different zoom levels.">
            <Toggle value={p.allow_map_view} onChange={(allow_map_view) => patch({ allow_map_view })} />
          </FormRow>
          <div className="grid gap-3 md:grid-cols-2">
            <NumberPolicyInput
              label="Step size"
              value={p.step_world_units}
              unit="world units"
              onCommit={(step_world_units) => patch({ step_world_units })}
            />
            <NumberPolicyInput
              label="Move budget"
              value={p.max_move_steps_per_turn}
              unit="steps per turn"
              description={`Max self-move: ${unitsFor(p.max_move_steps_per_turn)}`}
              onCommit={(max_move_steps_per_turn) => patch({ max_move_steps_per_turn })}
            />
            <NumberPolicyInput
              label="Min clearance"
              value={p.minimum_clearance_steps}
              unit="steps"
              description={`Personal space: ${unitsFor(p.minimum_clearance_steps)}`}
              onCommit={(minimum_clearance_steps) => patch({ minimum_clearance_steps })}
            />
            <NumberPolicyInput
              label="Awareness radius"
              value={p.awareness_radius_steps}
              unit="steps"
              description={`Nearby search radius: ${unitsFor(p.awareness_radius_steps)}`}
              onCommit={(awareness_radius_steps) => patch({ awareness_radius_steps })}
            />
            <NumberPolicyInput
              label="Nearest floor"
              value={p.nearest_neighbor_floor}
              unit="objects"
              description="Always includes this many closest objects, even outside radius."
              onCommit={(nearest_neighbor_floor) => patch({ nearest_neighbor_floor })}
            />
            <NumberPolicyInput
              label="Tug radius"
              value={p.tug_radius_steps}
              unit="steps"
              description={`Object tug range: ${unitsFor(p.tug_radius_steps)}`}
              onCommit={(tug_radius_steps) => patch({ tug_radius_steps })}
            />
            <NumberPolicyInput
              label="Tug budget"
              value={p.max_tug_steps_per_turn}
              unit="steps per turn"
              description={`Max object move: ${unitsFor(p.max_tug_steps_per_turn)}`}
              onCommit={(max_tug_steps_per_turn) => patch({ max_tug_steps_per_turn })}
            />
            <NumberPolicyInput
              label="Trace minutes"
              value={p.movement_trace_ttl_minutes}
              unit="minutes"
              onCommit={(movement_trace_ttl_minutes) => patch({ movement_trace_ttl_minutes })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function NumberPolicyInput({
  label,
  value,
  unit,
  description,
  onCommit,
}: {
  label: string;
  value: number;
  unit?: string;
  description?: string;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-[12px] text-text-dim">
      <span className="flex items-center justify-between gap-2">
        <span>{label}</span>
        {unit && <span className="text-[10px] text-text-dim/70">{unit}</span>}
      </span>
      <input
        type="number"
        min={0}
        defaultValue={value}
        className={INPUT_CLASS}
        onBlur={(e) => {
          const parsed = parseInt(e.target.value, 10);
          if (!Number.isNaN(parsed)) onCommit(parsed);
        }}
      />
      {description && <span className="text-[10px] leading-snug text-text-dim/75">{description}</span>}
    </label>
  );
}
