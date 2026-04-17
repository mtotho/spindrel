import { Edit3, ExternalLink, Plus, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Section } from "@/src/components/shared/FormControls";
import {
  useActivateWidgetPackage,
  useWidgetPackages,
  type WidgetPackageListItem,
} from "@/src/api/hooks/useWidgetPackages";

interface Props {
  toolName: string;
  bareToolName: string;
}

export function ToolWidgetSection({ toolName, bareToolName }: Props) {
  const navigate = useNavigate();
  const { data: allPackages } = useWidgetPackages({ tool_name: bareToolName });
  const [pickerOpen, setPickerOpen] = useState(false);

  const packages = useMemo(() => allPackages ?? [], [allPackages]);
  const active = packages.find((p) => p.is_active);

  return (
    <Section title="Widget">
      {packages.length === 0 ? (
        <div className="rounded-lg border border-dashed border-surface-border p-4 text-center">
          <div className="text-[13px] text-text-muted mb-1">No widget template</div>
          <div className="text-[11px] text-text-dim mb-3">
            This tool will render with the default JSON tree view.
          </div>
          <button
            onClick={() => navigate(`/admin/widget-packages/new?tool=${encodeURIComponent(bareToolName)}`)}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90"
          >
            <Plus size={12} /> Create one
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          {active ? (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => navigate(`/admin/widget-packages/${active.id}`)}
                  className="text-[13px] font-semibold text-text hover:underline"
                >
                  {active.name}
                </button>
                {active.source === "user" ? (
                  <span className="rounded bg-purple/10 text-[10px] font-semibold uppercase tracking-wide text-purple px-1.5 py-0.5">
                    User
                  </span>
                ) : (
                  <span className="rounded bg-surface-overlay text-[10px] font-semibold uppercase tracking-wide text-text-muted px-1.5 py-0.5">
                    Default
                  </span>
                )}
                <span className="text-[11px] text-text-dim">
                  v{active.version}
                </span>
              </div>
              {active.description && (
                <div className="mt-1 text-[12px] text-text-muted">{active.description}</div>
              )}
            </>
          ) : (
            <div className="text-[12px] text-text-muted">No active template for this tool.</div>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            {active && (
              <button
                onClick={() => navigate(`/admin/widget-packages/${active.id}`)}
                className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay transition-colors"
              >
                <Edit3 size={12} /> Edit template
              </button>
            )}
            {packages.length > 1 && (
              <button
                onClick={() => setPickerOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay transition-colors"
              >
                <RefreshCw size={12} /> Change template
              </button>
            )}
            <button
              onClick={() => navigate(`/admin/widget-packages/new?tool=${encodeURIComponent(bareToolName)}`)}
              className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay transition-colors"
            >
              <Plus size={12} /> New variant
            </button>
            <button
              onClick={() => navigate(`/admin/tools?tab=library&tool=${encodeURIComponent(bareToolName)}`)}
              className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-accent hover:underline"
            >
              Browse library <ExternalLink size={11} />
            </button>
          </div>
        </div>
      )}

      {pickerOpen && (
        <ChangeTemplateModal
          toolName={toolName}
          packages={packages}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </Section>
  );
}

function ChangeTemplateModal({
  toolName, packages, onClose,
}: {
  toolName: string;
  packages: WidgetPackageListItem[];
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const activateMut = useActivateWidgetPackage();
  const [busyId, setBusyId] = useState<string | null>(null);

  const handleActivate = async (id: string) => {
    setBusyId(id);
    try {
      await activateMut.mutateAsync(id);
      onClose();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/50 z-[1000]"
      />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[1001] w-[520px] max-w-[92vw] max-h-[80vh] bg-surface-raised border border-surface-border rounded-xl shadow-2xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-surface-border p-4">
          <span className="text-[14px] font-bold text-text">
            Change template for {toolName}
          </span>
          <button onClick={onClose} className="text-text-dim hover:text-text text-[13px]">
            Close
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {packages.map((pkg) => (
            <div
              key={pkg.id}
              className={
                "rounded-lg border p-3 " +
                (pkg.is_active
                  ? "border-accent bg-accent/5"
                  : "border-surface-border bg-surface hover:bg-surface-overlay/30 transition-colors")
              }
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[13px] font-semibold text-text">{pkg.name}</span>
                {pkg.source === "user" ? (
                  <span className="rounded bg-purple/10 text-[10px] font-semibold uppercase tracking-wide text-purple px-1.5 py-0.5">
                    User
                  </span>
                ) : (
                  <span className="rounded bg-surface-overlay text-[10px] font-semibold uppercase tracking-wide text-text-muted px-1.5 py-0.5">
                    Default
                  </span>
                )}
                {pkg.is_active && (
                  <span className="rounded bg-accent/15 text-[10px] font-semibold uppercase tracking-wide text-accent px-1.5 py-0.5">
                    Active
                  </span>
                )}
              </div>
              {pkg.description && (
                <div className="mt-1 text-[12px] text-text-muted line-clamp-2">{pkg.description}</div>
              )}
              <div className="mt-2 flex gap-2">
                {!pkg.is_active && (
                  <button
                    onClick={() => handleActivate(pkg.id)}
                    disabled={busyId !== null}
                    className="rounded-md bg-accent text-white text-[12px] font-semibold px-2.5 py-1 hover:opacity-90 disabled:opacity-50"
                  >
                    {busyId === pkg.id ? "Activating…" : "Activate"}
                  </button>
                )}
                <button
                  onClick={() => navigate(`/admin/widget-packages/${pkg.id}`)}
                  className="rounded-md border border-surface-border text-text text-[12px] font-medium px-2.5 py-1 hover:bg-surface-overlay"
                >
                  Open
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
