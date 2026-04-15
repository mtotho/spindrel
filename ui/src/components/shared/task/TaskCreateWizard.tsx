/**
 * TaskCreateWizard — 3-step wizard modal for creating / cloning tasks.
 *
 * Steps: Content → Execution → Trigger
 * Centered modal on desktop (720px), full-screen on mobile.
 */
import { useState, useCallback, useEffect, useMemo } from "react";
import ReactDOM from "react-dom";
import { X, ChevronRight, ChevronLeft } from "lucide-react";
import { useTaskFormState } from "./useTaskFormState";
import { WizardStepIndicator } from "./WizardStepIndicator";
import { ContentFields, ExecutionFields, TriggerFields } from "./TaskFormFields";

export interface TaskCreateWizardProps {
  onClose: () => void;
  onSaved: () => void;
  defaultChannelId?: string;
  defaultBotId?: string;
  cloneFromId?: string;
  extraQueryKeysToInvalidate?: string[][];
}

export function TaskCreateWizard({
  onClose,
  onSaved,
  defaultChannelId,
  defaultBotId,
  cloneFromId,
  extraQueryKeysToInvalidate,
}: TaskCreateWizardProps) {
  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;

  const form = useTaskFormState({
    mode: "create",
    cloneFromId,
    defaultBotId,
    defaultChannelId,
    extraQueryKeysToInvalidate,
    onSaved,
  });

  // Wizard state
  const [currentStep, setCurrentStep] = useState(0);
  const [visitedSteps, setVisitedSteps] = useState<Set<number>>(() => new Set([0]));

  // Step validity
  const validSteps = useMemo(() => {
    const s = new Set<number>();
    if (form.hasPromptOrWorkflow) s.add(0);
    if (form.botId) s.add(1);
    s.add(2); // trigger is always valid
    return s;
  }, [form.hasPromptOrWorkflow, form.botId]);

  const goToStep = useCallback((step: number) => {
    setCurrentStep(step);
    setVisitedSteps((prev) => new Set([...prev, step]));
  }, []);

  const goNext = useCallback(() => {
    if (currentStep < 2) goToStep(currentStep + 1);
  }, [currentStep, goToStep]);

  const goBack = useCallback(() => {
    if (currentStep > 0) setCurrentStep(currentStep - 1);
  }, [currentStep]);

  // Keyboard: Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  if (typeof document === "undefined") return null;

  const isLastStep = currentStep === 2;
  const canGoNext = currentStep === 0 ? form.hasPromptOrWorkflow : true;
  const editorTitle = cloneFromId ? "New Task (Clone)" : "New Task";

  return ReactDOM.createPortal(
    <div
      className="flex fixed inset-0 z-[10000] items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className={`flex flex-col bg-surface ${
        isMobile
          ? "w-full h-full"
          : "w-[min(95vw,720px)] max-h-[85vh] rounded-2xl shadow-2xl border border-surface-border"
      } overflow-hidden`}>

        {/* Header */}
        <div className="flex flex-row items-center px-5 py-3 border-b border-surface-border shrink-0 gap-2.5">
          <button
            onClick={onClose}
            className="flex items-center justify-center bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md hover:bg-surface-overlay transition-colors"
          >
            <X size={18} className="text-text-muted" />
          </button>
          <span className="text-text text-[15px] font-bold flex-1 tracking-tight">
            {editorTitle}
          </span>
          <button
            onClick={form.handleSave}
            disabled={form.saving || !form.canSave}
            className={`px-5 py-1.5 text-[13px] font-semibold border-none rounded-lg shrink-0 transition-all duration-150 ${
              form.canSave
                ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
                : "bg-surface-border text-text-dim cursor-not-allowed"
            } ${form.saving ? "opacity-70" : ""}`}
          >
            {form.saving ? "Creating..." : "Create"}
          </button>
        </div>

        {/* Step indicator */}
        <WizardStepIndicator
          currentStep={currentStep}
          visitedSteps={visitedSteps}
          validSteps={validSteps}
          onStepClick={goToStep}
        />

        {/* Error display */}
        {form.error && (
          <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs shrink-0">
            {form.error?.message || "An error occurred"}
          </div>
        )}

        {/* Body — scrollable content area for current step */}
        {cloneFromId && form.loadingTask ? (
          <div className="flex flex-col flex-1 items-center justify-center p-10">
            <div className="chat-spinner" />
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-5">
            {currentStep === 0 && <ContentFields form={form} promptRows={8} />}
            {currentStep === 1 && <ExecutionFields form={form} />}
            {currentStep === 2 && <TriggerFields form={form} />}
          </div>
        )}

        {/* Footer — navigation */}
        <div className="flex flex-row items-center px-5 py-3 border-t border-surface-border shrink-0 gap-2">
          {currentStep > 0 ? (
            <button
              onClick={goBack}
              className="flex flex-row items-center gap-1 px-3 py-1.5 text-xs font-semibold text-text-muted bg-transparent border border-surface-border rounded-lg cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
            >
              <ChevronLeft size={14} />
              Back
            </button>
          ) : (
            <div />
          )}
          <div className="flex-1" />
          {!isLastStep ? (
            <button
              onClick={goNext}
              disabled={!canGoNext}
              className={`flex flex-row items-center gap-1 px-4 py-1.5 text-xs font-semibold border-none rounded-lg transition-all duration-150 ${
                canGoNext
                  ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
                  : "bg-surface-border text-text-dim cursor-not-allowed"
              }`}
            >
              Next
              <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={form.handleSave}
              disabled={form.saving || !form.canSave}
              className={`px-5 py-1.5 text-xs font-semibold border-none rounded-lg transition-all duration-150 ${
                form.canSave
                  ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
                  : "bg-surface-border text-text-dim cursor-not-allowed"
              } ${form.saving ? "opacity-70" : ""}`}
            >
              {form.saving ? "Creating..." : "Create Task"}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
