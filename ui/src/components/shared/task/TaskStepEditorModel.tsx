import {
  Bot,
  HelpCircle,
  MessageCircleQuestion,
  Repeat,
  Terminal,
  Wrench,
} from "lucide-react";

import type { StepDef, StepType } from "@/src/api/hooks/useTasks";

export type StepTypeMeta = {
  value: StepType;
  label: string;
  icon: typeof Terminal;
  color: string;
  bgBadge: string;
  node: string;
};

export const STEP_TYPES: StepTypeMeta[] = [
  {
    value: "exec",
    label: "Shell",
    icon: Terminal,
    color: "text-warning-muted",
    bgBadge: "bg-surface-overlay text-text-muted",
    node: "bg-surface-overlay text-text-dim",
  },
  {
    value: "tool",
    label: "Tool",
    icon: Wrench,
    color: "text-text-muted",
    bgBadge: "bg-surface-overlay text-text-muted",
    node: "bg-surface-overlay text-text-dim",
  },
  {
    value: "agent",
    label: "LLM",
    icon: Bot,
    color: "text-purple",
    bgBadge: "bg-purple/10 text-purple",
    node: "bg-purple/10 text-purple",
  },
  {
    value: "user_prompt",
    label: "User prompt",
    icon: MessageCircleQuestion,
    color: "text-accent",
    bgBadge: "bg-accent/10 text-accent",
    node: "bg-accent/10 text-accent",
  },
  {
    value: "foreach",
    label: "For each",
    icon: Repeat,
    color: "text-text-muted",
    bgBadge: "bg-surface-overlay text-text-muted",
    node: "bg-surface-overlay text-text-dim",
  },
];

export const UNKNOWN_STEP_META: StepTypeMeta = {
  value: "exec",
  label: "Unknown",
  icon: HelpCircle,
  color: "text-text-dim",
  bgBadge: "bg-surface-overlay text-text-dim",
  node: "bg-surface-overlay text-text-dim",
};

let stepCounter = 0;

export function stepMeta(type: string): StepTypeMeta {
  return STEP_TYPES.find((s) => s.value === type) ?? UNKNOWN_STEP_META;
}

export function isKnownStepType(type: string): type is StepType {
  return STEP_TYPES.some((s) => s.value === type);
}

export function nextStepId(): string {
  stepCounter += 1;
  return `step_${stepCounter}`;
}

export function emptyStep(type: StepType): StepDef {
  const base: StepDef = {
    id: nextStepId(),
    type,
    label: "",
    on_failure: "abort",
  };
  if (type === "exec" || type === "agent") {
    base.prompt = "";
  } else if (type === "user_prompt") {
    base.title = "";
    base.response_schema = { type: "binary" };
  } else if (type === "foreach") {
    base.over = "";
    base.on_failure = "continue";
    base.do = [];
  }
  return base;
}

export function emptyToolSubStep(): StepDef {
  return {
    id: nextStepId(),
    type: "tool",
    label: "",
    on_failure: "abort",
  };
}
