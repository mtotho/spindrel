import type { ReactNode } from "react";
import { ContextTrackerWidget } from "./ContextTrackerWidget";
import { MachineControlWidget } from "./MachineControlWidget";
import { NotesWidget } from "./NotesWidget";
import { PlanQuestionsWidget } from "./PlanQuestionsWidget";
import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { StandingOrderWidget } from "./StandingOrderWidget";
import { TodoWidget } from "./TodoWidget";
import { UpcomingActivityWidget } from "./UpcomingActivityWidget";
import { UsageForecastWidget } from "./UsageForecastWidget";

type NativeWidgetComponent = (props: NativeAppRendererProps) => ReactNode;

const NATIVE_WIDGET_REGISTRY: Record<string, NativeWidgetComponent> = {
  "core/plan_questions": PlanQuestionsWidget,
  "core/context_tracker": ContextTrackerWidget,
  "core/machine_control_native": MachineControlWidget,
  "core/notes_native": NotesWidget,
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
