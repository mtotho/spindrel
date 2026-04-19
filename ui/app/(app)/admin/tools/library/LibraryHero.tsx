import { BookOpen, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { WidgetTemplatesDocsModal } from "./WidgetTemplatesDocsModal";

export function LibraryHero() {
  const navigate = useNavigate();
  const [docsOpen, setDocsOpen] = useState(false);

  return (
    <>
      <div className="border-b border-surface-border bg-surface-raised p-4 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-3xl space-y-1">
            <div className="text-[13px] text-text font-semibold">
              Widget Templates
            </div>
            <div className="text-[12px] text-text-muted leading-relaxed">
              How tool results render as interactive widgets. Grouped below by
              the tool each template extends — one default per tool is active at a time.{" "}
              <button
                onClick={() => setDocsOpen(true)}
                className="inline-flex items-center gap-1 text-accent hover:underline align-baseline focus:outline-none focus:ring-2 focus:ring-accent/40 rounded-sm"
              >
                <BookOpen size={11} />
                Read the docs
              </button>
            </div>
          </div>
          <button
            onClick={() => navigate("/widgets/dev#templates")}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 transition-opacity focus:outline-none focus:ring-2 focus:ring-accent/40"
            aria-label="Create a new widget template"
            title="Create a new widget template"
          >
            <Plus size={12} />
            <span className="hidden sm:inline">New template</span>
          </button>
        </div>
      </div>
      {docsOpen && <WidgetTemplatesDocsModal onClose={() => setDocsOpen(false)} />}
    </>
  );
}
