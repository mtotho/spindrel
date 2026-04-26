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
    <div className="flex w-[min(95vw,600px)] max-h-[calc(100dvh-32px)] flex-col gap-5 overflow-y-auto rounded-md border border-surface-border bg-surface p-4 text-text sm:rounded-lg sm:p-6">
      <div className="flex flex-row items-center justify-between">
        <span className="text-[15px] font-bold tracking-tight text-text">New Task</span>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex items-center justify-center w-7 h-7 rounded-md bg-transparent border-none cursor-pointer text-text-muted hover:text-text hover:bg-surface-overlay transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <span className="text-xs text-text-muted">Pick how this task is described.</span>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <button
          onClick={() => onPick("prompt")}
          className="flex flex-col items-start gap-2 rounded-md border border-surface-border bg-surface-raised p-4 text-left cursor-pointer transition-colors hover:border-accent/40 hover:bg-surface-overlay"
        >
          <MessageSquare size={22} className="text-accent" />
          <span className="text-sm font-semibold text-text">Prompt</span>
          <span className="text-[11.5px] text-text-muted leading-snug">
            Single-shot agent turn. The bot reads the prompt and runs to completion.
          </span>
        </button>
        <button
          onClick={() => onPick("pipeline")}
          className="flex flex-col items-start gap-2 rounded-md border border-surface-border bg-surface-raised p-4 text-left cursor-pointer transition-colors hover:border-accent/40 hover:bg-surface-overlay"
        >
          <Workflow size={22} className="text-accent" />
          <span className="text-sm font-semibold text-text">Pipeline</span>
          <span className="text-[11.5px] text-text-muted leading-snug">
            Ordered steps with conditionals. Mixes shells, tools, agent turns, prompts, foreach.
          </span>
        </button>
      </div>
    </div>
  );
}
