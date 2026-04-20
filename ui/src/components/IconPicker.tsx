import { useMemo, useState } from "react";
import { LayoutDashboard } from "lucide-react";
import { DynamicIcon, iconNames } from "lucide-react/dynamic";
import { cn } from "../lib/cn";

interface Props {
  value: string | null;
  onChange: (iconName: string | null) => void;
  /** Optional label displayed above the grid. */
  label?: string;
}

/** Lucide's canonical icon name is kebab-case (e.g. `layout-dashboard`). The
 *  full catalog (~1900 icons + aliases) is exposed via `iconNames`. Legacy
 *  stored names are PascalCase (e.g. `LayoutDashboard`) — `normalizeIconName`
 *  converts both forms to the canonical kebab-case that `DynamicIcon` expects. */
const ICON_SET: Set<string> = new Set(iconNames);

function pascalToKebab(name: string): string {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1-$2")
    .toLowerCase();
}

export function normalizeIconName(name: string | null | undefined): string | null {
  if (!name) return null;
  if (ICON_SET.has(name)) return name;
  const kebab = pascalToKebab(name);
  return ICON_SET.has(kebab) ? kebab : null;
}

/** Sorted canonical name list — source of truth for the picker. */
const SORTED_NAMES = [...iconNames].sort();

/** Render cap so we don't spin up thousands of lazy icons at once. Typing
 *  into the search narrows the list; "Show more" bumps the cap in chunks. */
const INITIAL_LIMIT = 240;
const MORE_STEP = 240;

export function IconPicker({ value, onChange, label }: Props) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(INITIAL_LIMIT);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SORTED_NAMES;
    return SORTED_NAMES.filter((name) => name.includes(q));
  }, [query]);

  const visible = filtered.slice(0, limit);
  const hasMore = filtered.length > limit;
  const canonicalValue = normalizeIconName(value);

  return (
    <div className="flex flex-col gap-2">
      {label && (
        <span className="text-[12px] font-medium text-text-muted">{label}</span>
      )}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setLimit(INITIAL_LIMIT);
          }}
          placeholder={`Search ${SORTED_NAMES.length} icons…`}
          className="flex-1 rounded-md border border-surface-border bg-surface-raised px-2.5 py-1.5 text-[12px] text-text outline-none focus:border-accent/60"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="rounded-md border border-surface-border px-2 py-1 text-[11px] text-text-muted hover:bg-surface-overlay"
            title="Clear icon"
          >
            Clear
          </button>
        )}
      </div>
      {canonicalValue && (
        <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-[11px] text-text-muted">
          <DynamicIcon name={canonicalValue as never} size={14} />
          <span className="font-mono text-text">{canonicalValue}</span>
          <span className="text-text-dim">· current</span>
        </div>
      )}
      <div className="grid max-h-72 grid-cols-6 gap-1 overflow-auto rounded-md border border-surface-border bg-surface p-2">
        {visible.map((name) => {
          const active = canonicalValue === name;
          return (
            <button
              key={name}
              type="button"
              onClick={() => onChange(name)}
              title={name}
              className={cn(
                "flex flex-col items-center justify-start gap-1 rounded-md border px-1 py-1.5 transition-colors",
                active
                  ? "border-accent/60 bg-accent/10 text-accent"
                  : "border-transparent text-text-muted hover:bg-surface-overlay",
              )}
            >
              <DynamicIcon name={name as never} size={18} />
              <span className="w-full truncate text-center font-mono text-[9.5px] leading-tight text-text-dim">
                {name}
              </span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="col-span-6 py-4 text-center text-[12px] text-text-muted">
            No icons match "{query}"
          </div>
        )}
        {hasMore && (
          <button
            type="button"
            onClick={() => setLimit((l) => l + MORE_STEP)}
            className="col-span-6 mt-1 rounded-md border border-surface-border bg-surface-raised py-1.5 text-[11px] text-text-muted hover:bg-surface-overlay"
          >
            Show more ({filtered.length - limit} remaining)
          </button>
        )}
      </div>
    </div>
  );
}

/** Render a Lucide icon by stored name. Accepts both legacy PascalCase
 *  (`LayoutDashboard`) and canonical kebab-case (`layout-dashboard`); falls
 *  back to LayoutDashboard for unknown names. */
export function LucideIconByName({
  name,
  size = 18,
  className,
}: {
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const canonical = normalizeIconName(name);
  if (!canonical) return <LayoutDashboard size={size} className={className} />;
  return (
    <DynamicIcon
      name={canonical as never}
      size={size}
      className={className}
    />
  );
}
