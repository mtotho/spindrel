import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { WidgetPackageListItem } from "@/src/api/hooks/useWidgetPackages";

import { PackageCard } from "./PackageCard";

interface Props {
  toolName: string;
  packages: WidgetPackageListItem[];
  defaultOpen?: boolean;
}

export function ToolGroup({ toolName, packages, defaultOpen = false }: Props) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(defaultOpen);

  const seedFallback = packages.find((p) => p.source === "seed" && !p.is_orphaned);
  const seedIntegration = seedFallback?.source_integration;
  const userCount = packages.filter((p) => p.source === "user").length;

  return (
    <div className="rounded-lg border border-surface-border bg-surface overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface-overlay/50 transition-colors"
      >
        {open ? <ChevronDown size={14} className="text-text-dim" /> : <ChevronRight size={14} className="text-text-dim" />}
        <span className="font-mono text-[13px] text-text font-semibold">
          {toolName}
        </span>
        <span className="text-[11px] text-text-dim">
          ({packages.length} package{packages.length === 1 ? "" : "s"})
        </span>
        {seedIntegration && (
          <span className="ml-2 inline-flex items-center rounded bg-purple/10 text-purple text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5">
            {seedIntegration}
          </span>
        )}
        {userCount > 0 && (
          <span className="inline-flex items-center rounded bg-accent/10 text-accent text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5">
            {userCount} user
          </span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/admin/widget-packages/new?tool=${encodeURIComponent(toolName)}`);
          }}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-surface-border bg-surface-raised text-text-muted text-[11px] font-medium px-2 py-1 hover:bg-surface-overlay transition-colors"
          type="button"
        >
          <Plus size={11} />
          New
        </button>
      </button>

      {open && (
        <div className="space-y-3 border-t border-surface-border p-3">
          {packages.map((pkg) => (
            <PackageCard
              key={pkg.id}
              pkg={pkg}
              seedFallbackName={seedFallback?.name ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
}
