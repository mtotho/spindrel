import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useWidgetPackages, type WidgetPackageListItem } from "@/src/api/hooks/useWidgetPackages";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";

import { LibraryHero } from "./LibraryHero";
import { LibraryFilterBar, type LibraryFilters } from "./LibraryFilterBar";
import { ToolGroup } from "./ToolGroup";

interface Props {
  initialToolFilter?: string;
}

export function WidgetLibraryTab({ initialToolFilter = "" }: Props) {
  const t = useThemeTokens();
  const { data: packages, isLoading } = useWidgetPackages();
  const [filters, setFilters] = useState<LibraryFilters>({
    search: "",
    source: "all",
    hasCode: false,
  });

  const grouped = useMemo(() => {
    if (!packages) return new Map<string, WidgetPackageListItem[]>();
    const q = filters.search.trim().toLowerCase();
    const filtered = packages.filter((p) => {
      if (filters.source !== "all" && p.source !== filters.source) return false;
      if (filters.hasCode && !p.has_python_code) return false;
      if (!q) return true;
      return (
        p.tool_name.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q) ||
        (p.description ?? "").toLowerCase().includes(q)
      );
    });
    const map = new Map<string, WidgetPackageListItem[]>();
    for (const pkg of filtered) {
      const list = map.get(pkg.tool_name);
      if (list) list.push(pkg);
      else map.set(pkg.tool_name, [pkg]);
    }
    return map;
  }, [packages, filters]);

  const toolNames = useMemo(() => [...grouped.keys()].sort(), [grouped]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <LibraryHero />
      <LibraryFilterBar filters={filters} onChange={setFilters} />

      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {toolNames.length === 0 && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-10 text-center text-text-dim">
            <div className="text-[13px] mb-2 text-text-muted">
              {packages && packages.length === 0
                ? "No widget packages discovered yet"
                : "No packages match your filters"}
            </div>
            <div className="text-[12px]">
              {packages && packages.length === 0 ? (
                <>
                  Widget packages are loaded from integration manifests on server start, or{" "}
                  <Link to="/widgets/dev#templates" className="text-accent hover:underline">
                    create your first template →
                  </Link>
                </>
              ) : (
                "Try clearing filters or changing the source facet."
              )}
            </div>
          </div>
        )}

        {toolNames.map((toolName) => (
          <ToolGroup
            key={toolName}
            toolName={toolName}
            packages={grouped.get(toolName)!}
            defaultOpen={
              initialToolFilter === toolName ||
              grouped.get(toolName)!.some((p) => p.source === "user")
            }
          />
        ))}
      </div>
    </div>
  );
}
