import { AlertCircle, Check, Copy, Edit3, GitFork, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useActivateWidgetPackage,
  useDeleteWidgetPackage,
  useForkWidgetPackage,
  type WidgetPackageListItem,
} from "@/src/api/hooks/useWidgetPackages";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { ManifestSignatureBadge } from "@/src/components/shared/ManifestSignatureBadge";

interface Props {
  pkg: WidgetPackageListItem;
  variant?: "default" | "compact";
  seedFallbackName?: string | null;
}

export function PackageCard({ pkg, variant = "default", seedFallbackName }: Props) {
  const navigate = useNavigate();
  const activateMut = useActivateWidgetPackage();
  const forkMut = useForkWidgetPackage();
  const deleteMut = useDeleteWidgetPackage();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [busy, setBusy] = useState<null | "activate" | "fork" | "delete">(null);

  const isActive = pkg.is_active;
  const isSeed = pkg.source === "seed";

  const cardClass =
    "group rounded-lg border p-4 transition-colors " +
    (isActive
      ? "border-accent ring-1 ring-accent/30 bg-accent/5"
      : "border-surface-border bg-surface-raised hover:border-surface-overlay hover:bg-surface-overlay/40");

  const handleActivate = async () => {
    if (isActive || busy || pkg.is_invalid) return;
    setBusy("activate");
    try {
      await activateMut.mutateAsync(pkg.id);
    } finally {
      setBusy(null);
    }
  };

  const handleFork = async () => {
    if (busy) return;
    const ok = await confirm(
      `Forking creates an editable copy of "${pkg.name}". The original ${
        isSeed ? "seed" : "package"
      } stays unchanged so you can always reset.`,
      { title: "Fork package", confirmLabel: "Fork" },
    );
    if (!ok) return;
    setBusy("fork");
    try {
      const forked = await forkMut.mutateAsync({ id: pkg.id });
      navigate(`/widgets/dev?id=${forked.id}#templates`);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (busy || isSeed) return;
    const msg = isActive && seedFallbackName
      ? `"${pkg.name}" is the active template. Deleting it will fall back to the seed "${seedFallbackName}".`
      : `Delete "${pkg.name}"? This cannot be undone.`;
    const ok = await confirm(msg, {
      title: "Delete package",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    setBusy("delete");
    try {
      await deleteMut.mutateAsync(pkg.id);
    } finally {
      setBusy(null);
    }
  };

  const openEditor = () => navigate(`/widgets/dev?id=${pkg.id}#templates`);

  const sourceChip = isSeed ? (
    <span className="inline-flex items-center rounded bg-surface-overlay text-[10px] font-semibold uppercase tracking-wide text-text-muted px-1.5 py-0.5">
      Default
    </span>
  ) : (
    <span className="inline-flex items-center rounded bg-purple/10 text-[10px] font-semibold uppercase tracking-wide text-purple px-1.5 py-0.5">
      User
    </span>
  );

  return (
    <>
      <ConfirmDialogSlot />
      <div className={cardClass}>
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={openEditor}
                className="text-[13px] font-semibold text-text hover:underline text-left truncate"
              >
                {pkg.name}
              </button>
              {sourceChip}
              {isActive && (
                <span className="inline-flex items-center gap-1 rounded bg-accent/15 text-accent text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5">
                  <Check size={10} /> Active
                </span>
              )}
              {pkg.is_invalid && (
                <span className="inline-flex items-center gap-1 rounded bg-danger/15 text-danger text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5">
                  <AlertCircle size={10} /> Invalid
                </span>
              )}
              <ManifestSignatureBadge state={pkg.signature_state} />
              {pkg.has_python_code && (
                <span className="inline-flex items-center rounded bg-accent/10 text-accent text-[10px] font-mono px-1.5 py-0.5">
                  +python
                </span>
              )}
            </div>
            {variant === "default" && pkg.description && (
              <div className="mt-1 text-[12px] text-text-muted line-clamp-2">
                {pkg.description}
              </div>
            )}
            <div className="mt-1 text-[11px] text-text-dim">
              v{pkg.version}
              {pkg.source_integration && ` · ${pkg.source_integration}`}
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {!isActive && (
            <button
              onClick={handleActivate}
              disabled={!!busy || pkg.is_invalid}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-2.5 py-1.5 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
              title={pkg.is_invalid ? "Fix errors before activating" : "Make this the active template for the tool"}
            >
              {busy === "activate" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Activate
            </button>
          )}
          <button
            onClick={openEditor}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay transition-colors"
          >
            <Edit3 size={12} />
            {isSeed ? "View" : "Edit"}
          </button>
          <button
            onClick={handleFork}
            disabled={!!busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text-muted text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay transition-colors disabled:opacity-50"
            title={isSeed ? "Create an editable copy" : "Duplicate this package"}
          >
            {busy === "fork" ? <Loader2 size={12} className="animate-spin" /> : isSeed ? <GitFork size={12} /> : <Copy size={12} />}
            {isSeed ? "Fork" : "Duplicate"}
          </button>
          {!isSeed && (
            <button
              onClick={handleDelete}
              disabled={!!busy}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-surface-border text-danger text-[12px] font-medium px-2.5 py-1.5 hover:bg-danger/10 transition-colors disabled:opacity-50"
            >
              {busy === "delete" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
              Delete
            </button>
          )}
        </div>
      </div>
    </>
  );
}
