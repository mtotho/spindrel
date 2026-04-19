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
    <div className="group/toolgroup rounded-lg border border-surface-border bg-surface overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface-overlay/50 transition-colors focus:outline-none focus-visible:bg-surface-overlay/40"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={14} className="text-text-dim" /> : <ChevronRight size={14} className="text-text-dim" />}
        <span className="font-mono text-[11px] uppercase tracking-wider text-text-muted font-medium">
          {toolName}
        </span>
        <span className="text-[11px] text-text-dim tabular-nums">
          ({packages.length})
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
            navigate(`/widgets/dev?tool=${encodeURIComponent(toolName)}#templates`);
          }}
          className="relative ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-text-muted opacity-0 group-hover/toolgroup:opacity-100 focus-visible:opacity-100 hover:bg-surface-overlay hover:text-text transition-opacity transition-colors before:absolute before:inset-[-6px] before:content-['']"
          type="button"
          aria-label={`New template for ${toolName}`}
          title={`New template for ${toolName}`}
        >
          <Plus size={14} />
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
