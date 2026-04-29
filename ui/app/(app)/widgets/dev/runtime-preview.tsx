import { useMemo } from "react";

import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { adaptToToolResultEnvelope } from "@/src/components/chat/renderers/resolveEnvelope";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { useThemeTokens } from "@/src/theme/tokens";
import type { PreviewEnvelope } from "@/src/api/hooks/useWidgetPackages";

const STORAGE_KEY = "spindrel:widget-authoring-preview";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

function readEnvelope(): PreviewEnvelope | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { envelope?: unknown };
    if (!parsed.envelope || typeof parsed.envelope !== "object") return null;
    return parsed.envelope as PreviewEnvelope;
  } catch {
    return null;
  }
}

export default function WidgetAuthoringRuntimePreview() {
  const t = useThemeTokens();
  const envelope = useMemo(readEnvelope, []);

  return (
    <div className="min-h-screen bg-surface p-6 text-text">
      <main
        data-testid="widget-authoring-runtime-preview"
        className="mx-auto flex max-w-5xl flex-col gap-3"
      >
        {!envelope ? (
          <div
            data-testid="widget-authoring-runtime-preview-error"
            className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-[13px] text-danger"
          >
            Widget authoring preview envelope is missing.
          </div>
        ) : (
          <div className="rounded-md border border-surface-border bg-surface-raised p-4">
            <RichToolResult
              envelope={adaptToToolResultEnvelope(envelope)}
              dispatcher={NOOP_DISPATCHER}
              t={t}
            />
          </div>
        )}
      </main>
    </div>
  );
}
