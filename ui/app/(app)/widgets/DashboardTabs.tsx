import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Menu, Plus, Settings } from "lucide-react";
import { cn } from "@/src/lib/cn";
import { useDashboards } from "@/src/stores/dashboards";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { useUIStore } from "@/src/stores/ui";
import { LucideIconByName } from "@/src/components/IconPicker";

interface Props {
  activeSlug: string;
  onOpenCreate: () => void;
  onOpenManage: () => void;
  /** Right-aligned slot for page-scoped actions (Edit layout / Add widget / Dev). */
  right?: ReactNode;
}

/** Unified dashboard bar: tab chips for switching dashboards (left), +/⚙ for
 *  dashboard-list management, and a `right` slot for actions scoped to the
 *  currently active dashboard. A vertical divider separates nav (left) from
 *  actions (right) so the two scopes read as distinct. */
export function DashboardTabs({ activeSlug, onOpenCreate, onOpenManage, right }: Props) {
  const { list, isLoading } = useDashboards();
  const columns = useResponsiveColumns();
  const openPalette = useUIStore((s) => s.openPalette);
  const isMobile = columns === "single";

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 border-b border-surface-border bg-surface px-4 py-1.5">
        <div className="h-6 w-16 animate-pulse rounded bg-surface-raised" />
        <div className="h-6 w-20 animate-pulse rounded bg-surface-raised" />
      </div>
    );
  }

  return (
    <div
      role="tablist"
      aria-label="Dashboards"
      className="relative flex items-center gap-1 bg-surface px-2 sm:px-3 py-1.5 shadow-[0_1px_3px_-1px_rgba(0,0,0,0.22)]"
    >
      {isMobile && (
        <button
          type="button"
          onClick={openPalette}
          aria-label="Open menu"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          <Menu size={18} />
        </button>
      )}
      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto scrollbar-thin">
        {list.map((d) => {
          const active = d.slug === activeSlug;
          return (
            <Link
              key={d.slug}
              to={`/widgets/${encodeURIComponent(d.slug)}`}
              role="tab"
              aria-selected={active}
              title={d.name}
              className={cn(
                "group relative inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                active
                  ? "bg-accent/[0.12] text-accent font-semibold"
                  : "text-text-muted font-medium hover:bg-surface-overlay hover:text-text",
              )}
            >
              {d.icon && (
                <LucideIconByName
                  name={d.icon}
                  size={13}
                  className={active ? "text-accent" : "text-text-muted group-hover:text-text"}
                />
              )}
              <span className="whitespace-nowrap">{d.name}</span>
              {active && (
                <span
                  aria-hidden
                  className="absolute -bottom-px left-2 right-2 h-[2px] rounded-full bg-accent"
                />
              )}
            </Link>
          );
        })}
        <div className="flex shrink-0 items-center gap-0.5 pl-0.5">
          <button
            type="button"
            onClick={onOpenCreate}
            title="New dashboard"
            aria-label="Create new dashboard"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <Plus size={13} />
          </button>
          <button
            type="button"
            onClick={onOpenManage}
            title="Edit this dashboard"
            aria-label="Edit this dashboard"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <Settings size={13} />
          </button>
        </div>
      </div>
      {right && (
        <div className="flex shrink-0 items-center gap-2 pl-3 ml-1">
          {right}
        </div>
      )}
    </div>
  );
}
