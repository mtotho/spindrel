import { Link } from "react-router-dom";
import { Plus, Settings } from "lucide-react";
import { cn } from "@/src/lib/cn";
import { useDashboards } from "@/src/stores/dashboards";
import { LucideIconByName } from "@/src/components/IconPicker";

interface Props {
  activeSlug: string;
  onOpenCreate: () => void;
  onOpenManage: () => void;
}

/** Tab bar across the top of the dashboard page. Active tab highlights using
 *  the same accent-bar language as the sidebar rail. A + opens the create
 *  sheet; a gear edits the currently active dashboard. */
export function DashboardTabs({ activeSlug, onOpenCreate, onOpenManage }: Props) {
  const { list, isLoading } = useDashboards();

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
      className="flex items-center gap-1 border-b border-surface-border bg-surface px-3"
    >
      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto py-1 scrollbar-thin">
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
      </div>
      <div className="flex shrink-0 items-center gap-1 py-1 pl-1">
        <button
          type="button"
          onClick={onOpenCreate}
          title="New dashboard"
          aria-label="Create new dashboard"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 before:absolute before:inset-[-4px] before:content-['']"
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          onClick={onOpenManage}
          title="Edit this dashboard"
          aria-label="Edit this dashboard"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 before:absolute before:inset-[-4px] before:content-['']"
        >
          <Settings size={14} />
        </button>
      </div>
    </div>
  );
}
