/**
 * WizardStepIndicator — 3-dot step indicator with labels for the task creation wizard.
 */
import { Check } from "lucide-react";

const STEPS = [
  { label: "Content", description: "What should this task do?" },
  { label: "Execution", description: "How should it run?" },
  { label: "Trigger", description: "When should it run?" },
] as const;

export function WizardStepIndicator({ currentStep, visitedSteps, validSteps, onStepClick }: {
  currentStep: number;
  visitedSteps: Set<number>;
  validSteps: Set<number>;
  onStepClick: (step: number) => void;
}) {
  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;

  return (
    <div className="flex flex-row items-center justify-center gap-0 px-5 py-3 border-b border-surface-border shrink-0">
      {STEPS.map((step, i) => {
        const isCurrent = i === currentStep;
        const isVisited = visitedSteps.has(i);
        const isValid = validSteps.has(i);
        const canClick = isVisited && !isCurrent;

        return (
          <div key={i} className="flex flex-row items-center">
            {/* Connector line (before all but first) */}
            {i > 0 && (
              <div className={`w-8 md:w-12 h-px mx-1 ${isVisited ? "bg-accent/40" : "bg-surface-border"}`} />
            )}

            {/* Step dot + label */}
            <button
              onClick={() => canClick && onStepClick(i)}
              disabled={!canClick}
              className={`flex flex-row items-center gap-2 bg-transparent border-none transition-colors rounded-lg px-1.5 py-1 -mx-1.5 -my-1 ${
                canClick ? "cursor-pointer hover:bg-surface-overlay" : "cursor-default"
              }`}
            >
              {/* Dot */}
              <div className={`flex items-center justify-center w-7 h-7 rounded-full text-[11px] font-bold transition-all duration-200 shrink-0 ${
                isCurrent
                  ? "bg-accent text-white shadow-sm shadow-accent/30"
                  : isValid
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : isVisited
                      ? "bg-surface-raised text-text-muted border border-surface-border"
                      : "bg-surface-raised text-text-dim border border-surface-border"
              }`}>
                {isValid && !isCurrent ? <Check size={13} strokeWidth={2.5} /> : i + 1}
              </div>

              {/* Label (hidden on small screens) */}
              {!isMobile && (
                <div className="flex flex-col">
                  <span className={`text-xs font-semibold leading-tight ${
                    isCurrent ? "text-text" : "text-text-muted"
                  }`}>
                    {step.label}
                  </span>
                  {isCurrent && (
                    <span className="text-[10px] text-text-dim leading-tight mt-0.5">
                      {step.description}
                    </span>
                  )}
                </div>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
}
