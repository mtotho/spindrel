import { useMemo, useState } from "react";
import { LayoutDashboard, icons as LucideIcons } from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  value: string | null;
  onChange: (iconName: string | null) => void;
  /** Optional label displayed above the grid. */
  label?: string;
}

type IconComponent = React.ComponentType<{ size?: number; className?: string }>;

/** The `icons` namespace from `lucide-react` exports every icon as a PascalCase
 *  default — e.g. `icons.LayoutDashboard`. That's the full ~1900-icon catalog.
 *  We use `lucide-react/dynamic` elsewhere would be nicer for lazy loading, but
 *  v1.0.1 ships a broken `dynamicIconImports` map that points at .ts source
 *  paths. Static bundle is the reliable option. */
const RAW_ICONS = LucideIcons as unknown as Record<string, IconComponent>;

/** Dedupe aliases (several PascalCase names point to the same component) and
 *  filter to a stable canonical list. Canonical = the first name (alphabetical)
 *  that resolves to a given component identity. */
const CANONICAL_ICONS: Record<string, IconComponent> = (() => {
  const out: Record<string, IconComponent> = {};
  const seen = new Set<IconComponent>();
  for (const name of Object.keys(RAW_ICONS).sort()) {
    const cmp = RAW_ICONS[name];
    if (!cmp || seen.has(cmp)) continue;
    // Skip the lowercase duplicates + `Lucide*` prefixed aliases.
    if (/^Lucide/.test(name)) continue;
    if (/Icon$/.test(name) && RAW_ICONS[name.replace(/Icon$/, "")]) continue;
    seen.add(cmp);
    out[name] = cmp;
  }
  return out;
})();

const ICON_NAMES = Object.keys(CANONICAL_ICONS).sort();
const ICON_SET = new Set(ICON_NAMES);

/** Resolve a stored name to a canonical icon component. Supports legacy
 *  PascalCase directly and also accepts kebab-case by converting on the fly. */
export function resolveIcon(name: string | null | undefined): IconComponent | null {
  if (!name) return null;
  if (ICON_SET.has(name)) return CANONICAL_ICONS[name];
  // Any alias that resolves to a canonical component also works.
  if (RAW_ICONS[name]) return RAW_ICONS[name];
  // kebab-case → PascalCase fallback (e.g. "layout-dashboard")
  const pascal = name
    .split("-")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");
  return RAW_ICONS[pascal] ?? null;
}

const INITIAL_LIMIT = 240;
const MORE_STEP = 240;

export function IconPicker({ value, onChange, label }: Props) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(INITIAL_LIMIT);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ICON_NAMES;
    return ICON_NAMES.filter((name) => name.toLowerCase().includes(q));
  }, [query]);

  const visible = filtered.slice(0, limit);
  const hasMore = filtered.length > limit;
  const activeName =
    value && ICON_SET.has(value)
      ? value
      : value
        ? Object.keys(CANONICAL_ICONS).find(
            (n) => CANONICAL_ICONS[n] === resolveIcon(value),
          ) ?? null
        : null;

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
          placeholder={`Search ${ICON_NAMES.length} icons…`}
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
      {activeName && (
        <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-[11px] text-text-muted">
          <LucideIconByName name={activeName} size={14} />
          <span className="font-mono text-text">{activeName}</span>
          <span className="text-text-dim">· current</span>
        </div>
      )}
      <div className="grid max-h-72 grid-cols-6 gap-1 overflow-auto rounded-md border border-surface-border bg-surface p-2">
        {visible.map((name) => {
          const Icon = CANONICAL_ICONS[name];
          if (!Icon) return null;
          const active = activeName === name;
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
              <Icon size={18} />
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

/** Render a Lucide icon by stored name. Accepts PascalCase canonical names,
 *  PascalCase aliases, or kebab-case. Falls back to LayoutDashboard for
 *  unknown names. */
export function LucideIconByName({
  name,
  size = 18,
  className,
}: {
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const Icon = resolveIcon(name) ?? LayoutDashboard;
  return <Icon size={size} className={className} />;
}
