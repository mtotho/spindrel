import { Activity, ExternalLink } from "lucide-react";
import { openTraceInspector, type TraceInspectorRequest } from "@/src/stores/traceInspector";
import { ActionButton } from "./SettingsControls";

type TraceActionSize = "default" | "small";
type TraceActionVariant = "primary" | "secondary" | "danger" | "ghost";

export function TraceActionButton({
  correlationId,
  title,
  subtitle,
  label = "View trace",
  size = "small",
  variant = "secondary",
  iconOnly = false,
  className = "",
  stopPropagation = false,
}: {
  correlationId: string;
  title?: string;
  subtitle?: string;
  label?: string;
  size?: TraceActionSize;
  variant?: TraceActionVariant;
  iconOnly?: boolean;
  className?: string;
  stopPropagation?: boolean;
}) {
  const open = () => {
    const request: TraceInspectorRequest = { correlationId };
    if (title) request.title = title;
    if (subtitle) request.subtitle = subtitle;
    openTraceInspector(request);
  };

  if (iconOnly) {
    return (
      <button
        type="button"
        title={label}
        aria-label={label}
        onClick={(event) => {
          if (stopPropagation) event.stopPropagation();
          open();
        }}
        className={
          className ||
          "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
        }
      >
        <Activity size={11} />
      </button>
    );
  }

  return (
    <span
      onClick={(event) => {
        if (stopPropagation) event.stopPropagation();
      }}
    >
      <ActionButton
        label={label}
        size={size}
        variant={variant}
        icon={<ExternalLink size={11} />}
        onPress={open}
      />
    </span>
  );
}
