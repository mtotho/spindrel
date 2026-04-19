import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Trash2, X } from "lucide-react";
import {
  useDashboardsStore,
  isChannelSlug,
  type Dashboard,
} from "@/src/stores/dashboards";
import { apiFetch } from "@/src/api/client";
import { IconPicker } from "@/src/components/IconPicker";
import {
  GRID_PRESETS,
  resolvePreset,
  type GridPresetId,
} from "@/src/lib/dashboardGrid";
import { useIsAdmin } from "@/src/hooks/useScope";
import { RailScopePicker, type RailChoice, resolveRailChoice } from "./RailScopePicker";
import { DashboardShareWarning } from "./DashboardShareWarning";

interface Props {
  slug: string | null;
  onClose: () => void;
}

export function EditDashboardDrawer({ slug, onClose }: Props) {
  const navigate = useNavigate();
  const list = useDashboardsStore((s) => s.list);
  const update = useDashboardsStore((s) => s.update);
  const remove = useDashboardsStore((s) => s.remove);
  const isChannel = slug ? isChannelSlug(slug) : false;

  // Channel dashboards aren't in the user-scope list that hydrate() fetches —
  // they lazy-create on first read. If we can't find the row in the store,
  // fetch it directly for channel slugs so the drawer can still open.
  const [fetchedChannel, setFetchedChannel] = useState<Dashboard | null>(null);
  const [channelFetchError, setChannelFetchError] = useState<string | null>(null);
  useEffect(() => {
    if (!slug || !isChannel) return;
    const inList = list.find((d) => d.slug === slug);
    if (inList) {
      setFetchedChannel(inList);
      return;
    }
    let cancelled = false;
    apiFetch<Dashboard>(`/api/v1/widgets/dashboards/${encodeURIComponent(slug)}`)
      .then((row) => {
        if (!cancelled) setFetchedChannel(row);
      })
      .catch((err) => {
        if (!cancelled) {
          setChannelFetchError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug, isChannel, list]);

  const dashboard: Dashboard | null = useMemo(() => {
    if (!slug) return null;
    const fromList = list.find((d) => d.slug === slug);
    return fromList ?? fetchedChannel;
  }, [slug, list, fetchedChannel]);

  const isAdmin = useIsAdmin();
  const setRailPin = useDashboardsStore((s) => s.setRailPin);
  const unsetRailPin = useDashboardsStore((s) => s.unsetRailPin);

  const [name, setName] = useState("");
  const [icon, setIcon] = useState<string | null>(null);
  const [railChoice, setRailChoice] = useState<RailChoice>("off");
  const [presetId, setPresetId] = useState<GridPresetId>("standard");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!dashboard) return;
    setName(dashboard.name);
    setIcon(dashboard.icon);
    setRailChoice(resolveRailChoice(dashboard.rail));
    setPresetId(resolvePreset(dashboard.grid_config ?? null).id);
    setError(null);
    setDeleteConfirm("");
  }, [dashboard?.slug]);

  const currentPresetId = dashboard
    ? resolvePreset(dashboard.grid_config ?? null).id
    : "standard";

  useEffect(() => {
    if (!slug) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [slug, onClose]);

  if (!slug) return null;
  if (!dashboard) {
    const msg = channelFetchError
      ? `Couldn't load dashboard: ${channelFetchError}`
      : isChannel
        ? "Loading dashboard…"
        : "Dashboard not found.";
    return (
      <>
        <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]" onClick={onClose} />
        <div className="fixed right-0 top-0 bottom-0 z-50 flex w-full flex-col border-l border-surface-border bg-surface-raised shadow-2xl sm:w-[440px]">
          <div className="p-6 text-center text-[12px] text-text-muted">{msg}</div>
        </div>
      </>
    );
  }

  const isDefault = dashboard.slug === "default";
  const initialRailChoice = resolveRailChoice(dashboard.rail);
  // Channel dashboards: name is tied to the channel so it's readonly here,
  // and delete isn't allowed (lifecycle is owned by the channel). Rail
  // scoping is supported for any dashboard — see RailScopePicker for the
  // admin-gated "For everyone" option.
  const dirty = isChannel
    ? (icon ?? null) !== (dashboard.icon ?? null)
      || railChoice !== initialRailChoice
      || presetId !== currentPresetId
    : name.trim() !== dashboard.name
      || (icon ?? null) !== (dashboard.icon ?? null)
      || railChoice !== initialRailChoice
      || presetId !== currentPresetId;
  const canSave = (isChannel || !!name.trim()) && dirty && !saving;
  const canDelete =
    !isChannel && !isDefault && deleteConfirm === dashboard.slug && !deleting;

  const persistRailChoice = async (next: RailChoice) => {
    if (next === initialRailChoice) return;
    // Transition from the previous choice to the next. Each scope owns its
    // own row, so clearing one never touches the other.
    if (initialRailChoice === "everyone" && next !== "everyone") {
      await unsetRailPin(dashboard.slug, "everyone");
    }
    if (initialRailChoice === "me" && next !== "me") {
      await unsetRailPin(dashboard.slug, "me");
    }
    if (next === "everyone") {
      await setRailPin(dashboard.slug, "everyone");
    } else if (next === "me") {
      await setRailPin(dashboard.slug, "me");
    }
  };

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const patch = isChannel
        ? {
            icon: icon ?? null,
            grid_config:
              presetId === "standard"
                ? null
                : { layout_type: "grid", preset: presetId },
          }
        : {
            name: name.trim(),
            icon: icon ?? null,
            grid_config:
              presetId === "standard"
                ? null
                : { layout_type: "grid", preset: presetId },
          };
      const updated = await update(dashboard.slug, patch);
      await persistRailChoice(railChoice);
      if (isChannel) setFetchedChannel(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!canDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await remove(dashboard.slug);
      onClose();
      navigate("/widgets/default", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDeleting(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
        role="presentation"
      />
      <div
        className="fixed right-0 top-0 bottom-0 z-50 flex w-full flex-col border-l border-surface-border bg-surface-raised shadow-2xl sm:w-[440px]"
        role="dialog"
        aria-label={`Edit dashboard ${dashboard.slug}`}
      >
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              Edit dashboard
            </span>
            <span className="truncate font-mono text-[13px] text-text">
              /widgets/{dashboard.slug}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
            title="Close"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-text-muted">
              Name
              {isChannel && (
                <span className="ml-2 text-[11px] font-normal text-text-dim">
                  (tied to the channel)
                </span>
              )}
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              readOnly={isChannel}
              disabled={isChannel}
              className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/60 disabled:opacity-60 disabled:cursor-not-allowed"
            />
          </label>

          <IconPicker value={icon} onChange={setIcon} label="Icon" />

          <RailScopePicker
            value={railChoice}
            onChange={setRailChoice}
            isAdmin={isAdmin}
          />

          {isAdmin && (
            <DashboardShareWarning slug={dashboard.slug} railChoice={railChoice} />
          )}

          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-text-muted">Grid layout</span>
            <div className="flex flex-col gap-1.5">
              {(Object.values(GRID_PRESETS)).map((p) => {
                const checked = presetId === p.id;
                return (
                  <label
                    key={p.id}
                    className={
                      "flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors " +
                      (checked
                        ? "border-accent/60 bg-accent/[0.08]"
                        : "border-surface-border hover:bg-surface-overlay")
                    }
                  >
                    <input
                      type="radio"
                      name="grid-preset"
                      checked={checked}
                      onChange={() => setPresetId(p.id)}
                      className="mt-0.5 h-3.5 w-3.5 accent-accent"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-[12.5px] font-medium text-text">
                        {p.label}
                      </div>
                      <div className="mt-0.5 text-[11px] text-text-dim leading-snug">
                        {p.description}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
            {presetId !== currentPresetId && (
              <p className="text-[11px] text-text-muted">
                Changing the grid rescales every pin's position proportionally —
                your arrangement carries over.
              </p>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}

          {!isDefault && !isChannel && (
            <div className="mt-2 border-t border-surface-border pt-4">
              <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-danger">
                <Trash2 size={13} />
                Delete dashboard
              </div>
              <p className="mb-2 text-[11px] text-text-muted">
                This permanently removes <code className="font-mono">{dashboard.slug}</code>{" "}
                and all of its pinned widgets. Type the slug to confirm.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={deleteConfirm}
                  onChange={(e) => setDeleteConfirm(e.target.value)}
                  placeholder={dashboard.slug}
                  className="flex-1 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 font-mono text-[12px] text-text outline-none focus:border-danger/60"
                />
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={!canDelete}
                  className="inline-flex items-center gap-1.5 rounded-md bg-danger px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {deleting && <Loader2 size={13} className="animate-spin" />}
                  Delete
                </button>
              </div>
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
            onClick={handleSave}
            disabled={!canSave}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            Save
          </button>
        </footer>
      </div>
    </>
  );
}
