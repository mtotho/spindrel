import { AgentSmellWidget } from "./AgentSmellWidget";
import { BlockyardWidget } from "./BlockyardWidget";
import { ChannelFilesWidget } from "./ChannelFilesWidget";
import type { ReactNode } from "react";
import { ContextTrackerWidget } from "./ContextTrackerWidget";
import { EcosystemSimWidget } from "./EcosystemSimWidget";
import { MachineControlWidget } from "./MachineControlWidget";
import { HarnessQuestionWidget } from "./HarnessQuestionWidget";
import { NotesWidget } from "./NotesWidget";
import { PlanQuestionsWidget } from "./PlanQuestionsWidget";
import { PinnedFilesWidget } from "./PinnedFilesWidget";
import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { StandingOrderWidget } from "./StandingOrderWidget";
import { StorybookWidget } from "./StorybookWidget";
import { TodoWidget } from "./TodoWidget";
import { UpcomingActivityWidget } from "./UpcomingActivityWidget";
import { UsageForecastWidget } from "./UsageForecastWidget";

type NativeWidgetComponent = (props: NativeAppRendererProps) => ReactNode;

const NATIVE_WIDGET_REGISTRY: Record<string, NativeWidgetComponent> = {
  "core/agent_smell_native": AgentSmellWidget,
  "core/channel_files_native": ChannelFilesWidget,
  "core/plan_questions": PlanQuestionsWidget,
  "core/context_tracker": ContextTrackerWidget,
  "core/game_blockyard": BlockyardWidget,
  "core/game_ecosystem": EcosystemSimWidget,
  "core/harness_question": HarnessQuestionWidget,
  "core/machine_control_native": MachineControlWidget,
  "core/notes_native": NotesWidget,
  "core/pinned_files_native": PinnedFilesWidget,
  "core/todo_native": TodoWidget,
  "core/usage_forecast_native": UsageForecastWidget,
  "core/upcoming_activity_native": UpcomingActivityWidget,
  "core/standing_order_native": StandingOrderWidget,
};

export function renderNativeWidget(props: NativeAppRendererProps): ReactNode {
  const payload = parsePayload(props.envelope);
  const Widget = payload.widget_ref ? NATIVE_WIDGET_REGISTRY[payload.widget_ref] : undefined;
  if (Widget) {
    return <Widget {...props} />;
  }
  return (
    <PreviewCard
      title={payload.display_label || "Native widget"}
      description={`No renderer registered for ${payload.widget_ref || "unknown widget"}.`}
      t={props.t}
    />
  );
}
