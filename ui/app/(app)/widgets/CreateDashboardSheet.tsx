import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, X } from "lucide-react";
import { useDashboardsStore } from "@/src/stores/dashboards";
import { IconPicker } from "@/src/components/IconPicker";

interface Props {
  open: boolean;
  onClose: () => void;
}

function slugify(input: string): string {
  return input
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,47}$/;

export function CreateDashboardSheet({ open, onClose }: Props) {
  const navigate = useNavigate();
  const create = useDashboardsStore((s) => s.create);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [icon, setIcon] = useState<string | null>("LayoutDashboard");
  const [pinToRail, setPinToRail] = useState(false);
  const [slugTouched, setSlugTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setName("");
      setSlug("");
      setIcon("LayoutDashboard");
      setPinToRail(false);
      setSlugTouched(false);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!slugTouched) setSlug(slugify(name));
  }, [name, slugTouched]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const slugError = useMemo(() => {
    if (!slug) return "Required";
    if (!SLUG_RE.test(slug)) return "Lowercase letters, digits, dashes (1-48 chars)";
    if (["default", "dev", "new"].includes(slug)) return "Reserved — choose another slug";
    return null;
  }, [slug]);

  const canSave = !!name.trim() && !slugError && !saving;

  if (!open) return null;

  const handleSubmit = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const created = await create({
        slug,
        name: name.trim(),
        icon,
        pin_to_rail: pinToRail,
      });
      onClose();
      navigate(`/widgets/${encodeURIComponent(created.slug)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
        role="presentation"
      />
      <div
        className="fixed right-0 top-0 bottom-0 z-50 flex w-full flex-col border-l border-surface-border bg-surface-raised shadow-2xl sm:w-[420px]"
        role="dialog"
        aria-label="Create dashboard"
      >
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              New dashboard
            </span>
            <span className="text-[13px] font-medium text-text">
              Pick a name, slug, and icon
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-surface-overlay"
            title="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-text-muted">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Home, Work, Morning…"
              className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/60"
              autoFocus
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="flex items-center justify-between text-[12px] font-medium text-text-muted">
              <span>URL slug</span>
              {slugError && (
                <span className="text-[11px] text-red-400">{slugError}</span>
              )}
            </span>
            <input
              type="text"
              value={slug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value);
              }}
              placeholder="home"
              className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 font-mono text-[12px] text-text outline-none focus:border-accent/60"
            />
            <span className="text-[11px] text-text-dim">
              Lives at <code className="font-mono">/widgets/{slug || "…"}</code>
            </span>
          </label>

          <IconPicker value={icon} onChange={setIcon} label="Icon" />

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={pinToRail}
              onChange={(e) => setPinToRail(e.target.checked)}
              className="h-4 w-4 accent-current text-accent"
            />
            <span className="text-[12px] text-text">Show in sidebar rail</span>
          </label>

          {error && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] text-red-400">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-surface-border px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-surface-border px-3 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSave}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            Create
          </button>
        </footer>
      </div>
    </>
  );
}
