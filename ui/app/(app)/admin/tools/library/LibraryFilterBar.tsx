import { Search } from "lucide-react";

import { useThemeTokens } from "@/src/theme/tokens";

export interface LibraryFilters {
  search: string;
  source: "all" | "seed" | "user";
  hasCode: boolean;
}

interface Props {
  filters: LibraryFilters;
  onChange: (next: LibraryFilters) => void;
}

export function LibraryFilterBar({ filters, onChange }: Props) {
  const t = useThemeTokens();
  return (
    <div
      className="flex flex-wrap items-center gap-3 border-b border-surface-border px-4 py-2 md:px-6"
    >
      <div
        className="flex items-center gap-1.5 rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5"
        style={{ minWidth: 220, flex: 1, maxWidth: 360 }}
      >
        <Search size={13} color={t.textDim} />
        <input
          value={filters.search}
          onChange={(e) => onChange({ ...filters, search: e.target.value })}
          placeholder="Filter packages..."
          className="flex-1 bg-transparent text-[12px] text-text outline-none"
        />
      </div>

      <select
        value={filters.source}
        onChange={(e) =>
          onChange({ ...filters, source: e.target.value as LibraryFilters["source"] })
        }
        className="rounded-md border border-surface-border bg-input-bg px-2 py-1.5 text-[12px] text-text outline-none"
      >
        <option value="all">All sources</option>
        <option value="seed">Defaults only</option>
        <option value="user">User-created only</option>
      </select>

      <label className="inline-flex items-center gap-2 text-[12px] text-text-muted cursor-pointer">
        <input
          type="checkbox"
          checked={filters.hasCode}
          onChange={(e) => onChange({ ...filters, hasCode: e.target.checked })}
          className="accent-accent"
        />
        Has transform code
      </label>
    </div>
  );
}
