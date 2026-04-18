import { Check, GitFork, Loader2, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useActivateWidgetPackage,
  useDeleteWidgetPackage,
  useForkWidgetPackage,
  type WidgetPackage,
} from "@/src/api/hooks/useWidgetPackages";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

interface Draft {
  name: string;
  tool_name: string;
}

interface Props {
  pkg: WidgetPackage | undefined;
  draft: Draft;
  dirty: boolean;
  saving: boolean;
  canSave: boolean;
  onSave: () => void;
  isNew: boolean;
}

export function WidgetPackageHeader({
  pkg, dirty, saving, canSave, onSave, isNew,
}: Props) {
  const navigate = useNavigate();
  const activateMut = useActivateWidgetPackage();
  const forkMut = useForkWidgetPackage();
  const deleteMut = useDeleteWidgetPackage();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [busy, setBusy] = useState<null | "activate" | "fork" | "delete">(null);

  const isSeed = pkg?.source === "seed";
  const isActive = pkg?.is_active;

  const handleActivate = async () => {
    if (!pkg || isActive || busy || pkg.is_invalid) return;
    setBusy("activate");
    try {
      await activateMut.mutateAsync(pkg.id);
    } finally {
      setBusy(null);
    }
  };

  const handleFork = async () => {
    if (!pkg || busy) return;
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
    if (!pkg || busy || isSeed) return;
    const msg = isActive
      ? `"${pkg.name}" is the active template. Deleting it will fall back to the seed.`
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
      navigate("/widgets/dev#library");
    } finally {
      setBusy(null);
    }
  };

  const saveLabel = isNew ? "Save to library" : "Save";

  return (
    <>
      <ConfirmDialogSlot />
      <div className="flex items-center gap-2">
        {pkg && (
          <div className="hidden md:flex items-center gap-1.5 pr-2 border-r border-surface-border">
            {isSeed ? (
              <span className="rounded bg-surface-overlay text-[10px] font-semibold uppercase tracking-wide text-text-muted px-1.5 py-0.5">
                Default
              </span>
            ) : (
              <span className="rounded bg-purple/10 text-[10px] font-semibold uppercase tracking-wide text-purple px-1.5 py-0.5">
                User
              </span>
            )}
            {isActive && (
              <span className="inline-flex items-center gap-1 rounded bg-accent/15 text-[10px] font-semibold uppercase tracking-wide text-accent px-1.5 py-0.5">
                <Check size={10} /> Active
              </span>
            )}
          </div>
        )}

        {dirty && !saving && (
          <span className="hidden md:inline-flex items-center rounded bg-warning/15 text-warning text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5">
            Unsaved
          </span>
        )}

        {pkg && !isSeed && !isActive && (
          <button
            onClick={handleActivate}
            disabled={!!busy || pkg.is_invalid || dirty}
            title={dirty ? "Save first" : pkg.is_invalid ? "Fix errors before activating" : "Activate"}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface-raised text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {busy === "activate" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            Activate
          </button>
        )}

        {pkg && isSeed && (
          <button
            onClick={handleFork}
            disabled={!!busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border bg-surface-raised text-text text-[12px] font-medium px-2.5 py-1.5 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
          >
            {busy === "fork" ? <Loader2 size={12} className="animate-spin" /> : <GitFork size={12} />}
            Fork to edit
          </button>
        )}

        {!isSeed && (
          <button
            onClick={onSave}
            disabled={!canSave || saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saveLabel}
          </button>
        )}

        {pkg && !isSeed && (
          <button
            onClick={handleDelete}
            disabled={!!busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-danger text-[12px] font-medium px-2.5 py-1.5 hover:bg-danger/10 disabled:opacity-50 transition-colors"
          >
            {busy === "delete" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
          </button>
        )}
      </div>
    </>
  );
}
