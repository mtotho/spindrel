import { Plus } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

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
  const navigate = useNavigate();
  const initialToolFilter = searchParams.get("tool") ?? "";

  return (
    <div className="flex-1 flex flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <div className="rounded-lg bg-surface-raised p-4">
          <h2 className="text-[14px] font-semibold text-text">Widget library</h2>
          <p className="mt-1 text-[12px] text-text-muted">
            Two kinds of widgets live in the product.
            {" "}<span className="font-medium text-text">HTML widgets</span> are standalone dashboard surfaces — shipped with the app, included in an integration, or authored as <span className="font-mono">.html</span> in a channel workspace.
            {" "}<span className="font-medium text-text">Tool renderers</span> shape a specific tool's output and pin via the tool's result.
          </p>
        </div>
      </div>

      {/* HTML widgets first — these are the end-user-pinnable surfaces and
          the catalog needs to make them findable regardless of which channel
          you happen to be viewing. */}
      <div className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <HtmlWidgetsLibrarySection />
      </div>

      <section className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <div className="mb-2 flex items-end justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[13px] font-semibold text-text">Tool renderers</h3>
            <p className="text-[11px] text-text-muted">
              Render the output of a specific tool. Authored in <span className="font-mono">*.widgets.yaml</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/widgets/dev#templates")}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label="Create a new widget template"
            title="Create a new widget template"
          >
            <Plus size={12} />
            <span className="hidden sm:inline">New template</span>
          </button>
        </div>
      </section>

      {/* Tool-renderer inventory — the existing shared component, unmodified. */}
      <div className="pb-4">
        <WidgetLibraryTab initialToolFilter={initialToolFilter} />
      </div>
    </div>
  );
}
