/**
 * ModePickerCard — first card shown for `?new=1` on the automations canvas.
 *
 * Two big choices: Prompt (single-shot agent turn) vs Pipeline (multi-step).
 * Once picked, the canvas page swaps to <CanvasEditor> with the chosen mode
 * pre-selected.
 */
import { MessageSquare, Workflow, X } from "lucide-react";

interface ModePickerCardProps {
  onPick: (mode: "prompt" | "pipeline") => void;
  onClose: () => void;
}

export function ModePickerCard({ onPick, onClose }: ModePickerCardProps) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-surface-border bg-surface shadow-2xl w-[min(95vw,600px)] p-6">
      <div className="flex flex-row items-center justify-between">
        <span className="text-[15px] font-bold tracking-tight">New Task</span>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex items-center justify-center w-7 h-7 rounded-md bg-transparent border-none cursor-pointer text-text-muted hover:bg-surface-overlay transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <span className="text-xs text-text-dim">Pick how this task is described.</span>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => onPick("prompt")}
          className="flex flex-col items-start gap-2 p-4 rounded-lg border border-surface-border bg-surface-raised/40 cursor-pointer text-left hover:border-accent/40 hover:bg-surface-raised transition-colors"
        >
          <MessageSquare size={20} className="text-accent" />
          <span className="text-sm font-semibold">Prompt</span>
          <span className="text-[11.5px] text-text-dim leading-snug">
            Single-shot agent turn. The bot reads the prompt and runs to completion.
          </span>
        </button>
        <button
          onClick={() => onPick("pipeline")}
          className="flex flex-col items-start gap-2 p-4 rounded-lg border border-surface-border bg-surface-raised/40 cursor-pointer text-left hover:border-accent/40 hover:bg-surface-raised transition-colors"
        >
          <Workflow size={20} className="text-accent" />
          <span className="text-sm font-semibold">Pipeline</span>
          <span className="text-[11.5px] text-text-dim leading-snug">
            Ordered steps with conditionals. Mixes shells, tools, agent turns, prompts, foreach.
          </span>
        </button>
      </div>
    </div>
  );
}
