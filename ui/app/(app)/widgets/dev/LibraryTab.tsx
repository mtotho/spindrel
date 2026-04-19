import { useSearchParams } from "react-router-dom";

import { WidgetLibraryTab } from "@/app/(app)/admin/tools/library/WidgetLibraryTab";
import { HtmlWidgetsLibrarySection } from "./HtmlWidgetsLibrarySection";

/** Dev-panel Library tab.
 *
 *  Two kinds of widgets live in the product and they answer different
 *  questions:
 *
 *    - **Tool renderers** (``*.widgets.yaml``): how should a given tool's
 *      output be rendered? Tied to a specific tool name; pinned via the
 *      tool's output (Recent calls → Pin).
 *
 *    - **HTML widgets** (``.html`` in a channel workspace): standalone
 *      dashboard control surfaces. Pinned directly from the Add-widget
 *      sheet's "HTML widgets" tab.
 *
 *  The dev panel's Library shows both, labeled distinctly so authors don't
 *  conflate them. */
export function LibraryTab() {
  const [searchParams] = useSearchParams();
  const initialToolFilter = searchParams.get("tool") ?? "";

  return (
    <div className="flex-1 flex flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <h2 className="text-[14px] font-semibold text-text">Widget library</h2>
          <p className="mt-1 text-[12px] text-text-muted">
            Two kinds of widgets live in the product.
            {" "}<span className="font-medium text-text">Tool renderers</span> shape a specific tool's output and pin via the tool's result.
            {" "}<span className="font-medium text-text">HTML widgets</span> are standalone dashboard surfaces pinned directly from a channel workspace.
          </p>
        </div>
      </div>

      <section className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <div className="mb-2 flex items-end justify-between">
          <div>
            <h3 className="text-[13px] font-semibold text-text">Tool renderers</h3>
            <p className="text-[11px] text-text-muted">
              Render the output of a specific tool. Authored in <span className="font-mono">*.widgets.yaml</span>.
            </p>
          </div>
        </div>
      </section>

      {/* Tool-renderer inventory — the existing shared component, unmodified. */}
      <WidgetLibraryTab initialToolFilter={initialToolFilter} />

      <div className="mx-auto w-full max-w-6xl px-4 py-4 md:px-6">
        <HtmlWidgetsLibrarySection />
      </div>
    </div>
  );
}
