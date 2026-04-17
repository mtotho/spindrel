import { BookOpen } from "lucide-react";
import { useState } from "react";

import { WidgetTemplatesDocsModal } from "./WidgetTemplatesDocsModal";

export function LibraryHero() {
  const [docsOpen, setDocsOpen] = useState(false);

  return (
    <>
      <div className="border-b border-surface-border bg-surface-raised p-4 md:p-6">
        <div className="max-w-3xl space-y-2">
          <div className="text-[13px] text-text font-semibold">
            Widget Templates
          </div>
          <div className="text-[12px] text-text-muted leading-relaxed">
            Every tool can render its result as an interactive widget. Browse
            the library, customize a default, or write your own — YAML template
            with optional Python transforms, activated per tool.
          </div>
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={() => setDocsOpen(true)}
              className="inline-flex items-center gap-1.5 text-[12px] text-accent hover:underline"
            >
              <BookOpen size={12} />
              Read the docs
            </button>
          </div>
        </div>
      </div>
      {docsOpen && <WidgetTemplatesDocsModal onClose={() => setDocsOpen(false)} />}
    </>
  );
}
