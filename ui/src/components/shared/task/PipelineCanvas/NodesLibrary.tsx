import type { StepType } from "@/src/api/hooks/useTasks";
import { STEP_TYPES } from "../TaskStepEditorModel";

interface NodesLibraryProps {
  onAdd: (type: StepType) => void;
  disabled?: boolean;
}

export function NodesLibrary({ onAdd, disabled }: NodesLibraryProps) {
  return (
    <div className="flex flex-col gap-2 p-3 border-r border-surface-border bg-surface-raised/30 w-[200px] shrink-0 overflow-y-auto">
      <div className="text-[10px] font-bold uppercase tracking-wider text-text-dim">
        Add step
      </div>
      <div className="flex flex-col gap-1">
        {STEP_TYPES.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.value}
              onClick={() => onAdd(t.value)}
              disabled={disabled}
              data-testid={`palette-${t.value}`}
              className="flex flex-row items-center gap-2 px-2.5 py-2 text-xs font-medium bg-transparent rounded-md cursor-pointer text-text hover:bg-surface-overlay/60 hover:text-accent transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Icon size={13} className={t.color} />
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="mt-3 text-[10px] text-text-dim leading-relaxed">
        Click to add at the canvas center. Drag any node to reposition. The
        runtime executes steps in array order — drag changes layout, not flow.
      </div>
    </div>
  );
}
