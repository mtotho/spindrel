import { useEffect } from "react";
import { X } from "lucide-react";
import { DashboardConfigForm } from "./DashboardConfigForm";

interface Props {
  slug: string | null;
  onClose: () => void;
  onResetLayout?: () => void;
}

export function EditDashboardDrawer({ slug, onClose, onResetLayout }: Props) {
  useEffect(() => {
    if (!slug) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [slug, onClose]);

  if (!slug) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
        role="presentation"
      />
      <div
        className="fixed right-0 top-0 bottom-0 z-50 flex w-full flex-col border-l border-surface-border bg-surface-raised shadow-2xl sm:w-[440px]"
        role="dialog"
        aria-label={`Edit dashboard ${slug}`}
      >
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              Edit dashboard
            </span>
            <span className="truncate font-mono text-[13px] text-text">
              /widgets/{slug}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
            title="Close"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex flex-1 flex-col overflow-y-auto p-4">
          <DashboardConfigForm
            slug={slug}
            variant="drawer"
            onClose={onClose}
            onResetLayout={onResetLayout}
          />
        </div>
      </div>
    </>
  );
}
