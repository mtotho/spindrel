import { WidgetLibrary } from "@/app/(app)/widgets/WidgetLibrary";

/** Dev-panel Library tab. Mounts the unified ``WidgetLibrary`` in browse
 *  mode with all-bots enumeration so every bot's ``widget://bot/<name>/``
 *  library is visible alongside core, integrations, workspace, and channel
 *  widgets. Tool renderers live under the component's second top-level tab. */
export function LibraryTab({ originChannelId }: { originChannelId?: string | null }) {
  return (
    <div className="flex-1 flex flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-4 pt-4 md:px-6">
        <div className="rounded-lg bg-surface-raised p-4">
          <h2 className="text-[14px] font-semibold text-text">Widget library</h2>
          <p className="mt-1 text-[12px] text-text-muted">
            Every widget bundle in the system. <span className="font-medium text-text">Pinnable</span> widgets
            (core, integrations, bot libraries, workspace library, channel workspaces) sit under the first tab —
            click any row to preview the live render, contract, source HTML, or manifest inline. <span className="font-medium text-text">Tool renderers</span>
            {" "}live under the second tab — they shape a specific tool's output and are instantiated from tool calls or presets rather than pinned as standalone bundles.
          </p>
        </div>
      </div>
      <div className="mx-auto w-full max-w-6xl px-4 pt-2 md:px-6">
        <WidgetLibrary
          mode="browse"
          botEnumeration="all-bots"
          scopeChannelId={originChannelId ?? null}
        />
      </div>
    </div>
  );
}
