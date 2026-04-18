import { useSearchParams } from "react-router-dom";

import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type { ToolResultEnvelope } from "@/src/types/api";

import { WidgetEditor } from "./editor/WidgetEditor";

export function TemplatesTab() {
  const [searchParams] = useSearchParams();
  const packageId = searchParams.get("id") ?? undefined;
  const initialToolName = searchParams.get("tool") ?? "";
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  return (
    <WidgetEditor
      packageId={packageId}
      initialToolName={initialToolName}
      onPinEnvelope={async ({ envelope, draft, samplePayload }) => {
        const toolName = draft.tool_name.trim();
        if (!toolName) {
          throw new Error("Set a tool name before pinning");
        }
        await pinWidget({
          source_kind: "adhoc",
          source_bot_id: null,
          source_channel_id: null,
          tool_name: toolName,
          tool_args: {},
          widget_config: {
            // Forward-compat sentinel — a future live-draft-pin refresh path
            // can detect this and re-apply `render_preview_inline` with the
            // stored yaml / sample.
            draft_template: true,
            yaml: draft.yaml_template,
            sample: samplePayload,
          },
          envelope: envelope as unknown as ToolResultEnvelope,
          display_label: draft.name.trim() || null,
        });
      }}
    />
  );
}
