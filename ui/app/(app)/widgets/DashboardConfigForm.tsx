import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, RotateCcw, Trash2 } from "lucide-react";
import {
  useDashboardsStore,
  isChannelSlug,
  type Dashboard,
} from "@/src/stores/dashboards";
import { apiFetch } from "@/src/api/client";
import { IconPicker } from "@/src/components/IconPicker";
import {
  GRID_PRESETS,
  resolveChrome,
  resolvePreset,
  type GridPresetId,
} from "@/src/lib/dashboardGrid";
import { useIsAdmin } from "@/src/hooks/useScope";
import { ActionButton, SettingsGroupLabel } from "@/src/components/shared/SettingsControls";
import { RailScopePicker, type RailChoice, resolveRailChoice } from "./RailScopePicker";
import { DashboardShareWarning } from "./DashboardShareWarning";

type Variant = "drawer" | "tab";

interface Props {
  slug: string;
  variant: Variant;
  onClose?: () => void;
  onResetLayout?: () => void;
}

export function DashboardConfigForm({
  slug,
  variant,
  onClose,
  onResetLayout,
}: Props) {
  const navigate = useNavigate();
  const list = useDashboardsStore((s) => s.list);
  const update = useDashboardsStore((s) => s.update);
  const remove = useDashboardsStore((s) => s.remove);
  const isChannel = isChannelSlug(slug);

  const [fetchedChannel, setFetchedChannel] = useState<Dashboard | null>(null);
  const [channelFetchError, setChannelFetchError] = useState<string | null>(null);
  useEffect(() => {
    if (!isChannel) return;
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
  const [borderless, setBorderless] = useState(false);
  const [hoverScrollbars, setHoverScrollbars] = useState(true);
  const [hideTitles, setHideTitles] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [resetArmed, setResetArmed] = useState(false);

  useEffect(() => {
    if (!dashboard) return;
    setName(dashboard.name);
    setIcon(dashboard.icon);
    setRailChoice(resolveRailChoice(dashboard.rail));
    setPresetId(resolvePreset(dashboard.grid_config ?? null).id);
    const chrome = resolveChrome(dashboard.grid_config ?? null);
    setBorderless(chrome.borderless);
    setHoverScrollbars(chrome.hoverScrollbars);
    setHideTitles(chrome.hideTitles);
    setError(null);
    setDeleteConfirm("");
    setResetArmed(false);
  }, [dashboard?.slug]);

  if (!dashboard) {
    const msg = channelFetchError
      ? `Couldn't load dashboard: ${channelFetchError}`
      : isChannel
        ? "Loading dashboard…"
        : "Dashboard not found.";
    return (
      <div className="p-6 text-center text-[12px] text-text-muted">{msg}</div>
    );
  }

  const isDefault = dashboard.slug === "default";
  const initialRailChoice = resolveRailChoice(dashboard.rail);
  const currentPresetId = resolvePreset(dashboard.grid_config ?? null).id;
  const currentChrome = resolveChrome(dashboard.grid_config ?? null);
  const chromeDirty =
    borderless !== currentChrome.borderless
    || hoverScrollbars !== currentChrome.hoverScrollbars
    || hideTitles !== currentChrome.hideTitles;
  const dirty = isChannel
    ? (icon ?? null) !== (dashboard.icon ?? null)
      || railChoice !== initialRailChoice
      || presetId !== currentPresetId
      || chromeDirty
    : name.trim() !== dashboard.name
      || (icon ?? null) !== (dashboard.icon ?? null)
      || railChoice !== initialRailChoice
      || presetId !== currentPresetId
      || chromeDirty;
  const canSave = (isChannel || !!name.trim()) && dirty && !saving;
  const canDelete =
    !isChannel && !isDefault && deleteConfirm === dashboard.slug && !deleting;
  const showResetLayout = !!onResetLayout;
  const showDrawerChannelCallout = variant === "drawer" && isChannel;

  const handleResetLayout = () => {
    if (!showResetLayout) return;
    if (!resetArmed) {
      setResetArmed(true);
      return;
    }
    setResetArmed(false);
    onResetLayout?.();
    onClose?.();
  };

  const persistRailChoice = async (next: RailChoice) => {
    if (next === initialRailChoice) return;
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
      const chromeDefault = !borderless && hoverScrollbars && !hideTitles;
      const preservedConfig =
        dashboard.grid_config && typeof dashboard.grid_config === "object"
          ? { ...(dashboard.grid_config as Record<string, unknown>) }
          : {};
      delete preservedConfig.layout_type;
      delete preservedConfig.preset;
      delete preservedConfig.borderless;
      delete preservedConfig.hover_scrollbars;
      delete preservedConfig.hide_titles;
      const gridConfig =
        presetId === "standard" && chromeDefault && Object.keys(preservedConfig).length === 0
          ? null
          : {
              ...preservedConfig,
              layout_type: "grid",
              preset: presetId,
              ...(borderless ? { borderless: true } : {}),
              ...(!hoverScrollbars ? { hover_scrollbars: false } : {}),
              ...(hideTitles ? { hide_titles: true } : {}),
            };
      const patch = isChannel
        ? { icon: icon ?? null, grid_config: gridConfig }
        : { name: name.trim(), icon: icon ?? null, grid_config: gridConfig };
      const updated = await update(dashboard.slug, patch);
      await persistRailChoice(railChoice);
      if (isChannel) setFetchedChannel(updated);
      if (variant === "drawer") onClose?.();
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
      onClose?.();
      navigate("/widgets/default", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {showDrawerChannelCallout && (
        <div className="flex flex-col gap-2 rounded-md bg-surface-raised/40 px-3 py-3">
          <div className="text-[12.5px] font-medium text-text">
            Channel-owned settings live in channel settings
          </div>
          <div className="text-[11px] leading-snug text-text-dim">
            Name, prompt, history, and presentation defaults are configured once for the channel. This drawer only keeps quick dashboard layout controls.
          </div>
          <div className="pt-1">
            <ActionButton
              label="Open channel settings"
              onPress={() => navigate(`/channels/${slug.replace(/^channel:/, "")}/settings?from=dashboard#dashboard`)}
              variant="secondary"
              size="small"
            />
          </div>
        </div>
      )}

      {!isChannel && (
        <>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-text-muted">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/60"
            />
          </label>

          <IconPicker value={icon} onChange={setIcon} label="Icon" />
        </>
      )}

      {/* Channel-scoped in tab mode: show the icon picker so users can still
          set a custom dashboard icon for this channel. Name stays channel-
          owned so it's hidden. */}
      {isChannel && variant === "tab" && (
        <IconPicker value={icon} onChange={setIcon} label="Icon" />
      )}

      <RailScopePicker
        value={railChoice}
        onChange={setRailChoice}
        isAdmin={isAdmin}
      />

      {isAdmin && (
        <DashboardShareWarning slug={dashboard.slug} railChoice={railChoice} />
      )}

      <div className="flex flex-col gap-1.5">
        <SettingsGroupLabel label="Grid layout" />
        <div className="flex flex-col gap-1.5">
          {Object.values(GRID_PRESETS).map((p) => {
            const checked = presetId === p.id;
            return (
              <label
                key={p.id}
                className={
                  "relative flex cursor-pointer items-start gap-2.5 rounded-md px-3 py-2 text-left transition-colors "
                  + (checked
                    ? "bg-accent/[0.06] before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
                    : "bg-surface-raised/40 hover:bg-surface-overlay/45")
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
            Changing the grid rescales every pin's position proportionally — your arrangement carries over.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Tile chrome" />
        <label className="flex cursor-pointer items-start gap-2.5 rounded-md bg-surface-raised/40 px-3 py-2 transition-colors hover:bg-surface-overlay/45">
          <input
            type="checkbox"
            checked={borderless}
            onChange={(e) => setBorderless(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 accent-accent"
          />
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-medium text-text">Borderless tiles</div>
            <div className="mt-0.5 text-[11px] text-text-dim leading-snug">
              Drops the 1px border around each widget card. Hover background stays.
            </div>
          </div>
        </label>
        <label className="flex cursor-pointer items-start gap-2.5 rounded-md bg-surface-raised/40 px-3 py-2 transition-colors hover:bg-surface-overlay/45">
          <input
            type="checkbox"
            checked={hoverScrollbars}
            onChange={(e) => setHoverScrollbars(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 accent-accent"
          />
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-medium text-text">Scrollbars on hover</div>
            <div className="mt-0.5 text-[11px] text-text-dim leading-snug">
              Widget scrollbars stay hidden until you hover over the tile.
            </div>
          </div>
        </label>
        <label className="flex cursor-pointer items-start gap-2.5 rounded-md bg-surface-raised/40 px-3 py-2 transition-colors hover:bg-surface-overlay/45">
          <input
            type="checkbox"
            checked={hideTitles}
            onChange={(e) => setHideTitles(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 accent-accent"
          />
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-medium text-text">Hide widget titles</div>
            <div className="mt-0.5 text-[11px] text-text-dim leading-snug">
              Tiles render without their uppercase title bar. Per-widget override lives in each pin&apos;s edit drawer. Edit mode always shows titles.
            </div>
          </div>
        </label>
      </div>

      {showResetLayout && (
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Layout maintenance" />
          <button
            type="button"
            onClick={handleResetLayout}
            className={
              "flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors "
              + (resetArmed
                ? "border-danger/60 bg-danger/10 text-danger"
                : "border-transparent bg-surface-raised/40 hover:bg-surface-overlay/45")
            }
            aria-pressed={resetArmed}
            aria-label={resetArmed ? "Confirm reset layout" : "Reset layout"}
            title={
              resetArmed
                ? "Click again to repack every pin into default positions"
                : "Auto-pack every pin into default positions"
            }
          >
            <RotateCcw size={14} className="mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="text-[12.5px] font-medium">
                {resetArmed ? "Confirm reset layout?" : "Reset layout"}
              </div>
              <div className="mt-0.5 text-[11px] leading-snug text-text-dim">
                Repack every widget into the default auto-layout. Useful if the layout gets messy.
              </div>
            </div>
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
          {error}
        </div>
      )}

      {!isDefault && !isChannel && (
        <div className="mt-2 flex flex-col gap-2 pt-2">
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
              className="inline-flex items-center gap-1.5 rounded-md bg-transparent px-3 py-1.5 text-[12px] font-semibold text-danger transition-colors hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {deleting && <Loader2 size={13} className="animate-spin" />}
              Delete
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2">
        <ActionButton
          label={saving ? "Saving…" : "Save"}
          onPress={handleSave}
          disabled={!canSave}
          size="small"
          icon={saving ? <Loader2 size={13} className="animate-spin" /> : undefined}
        />
      </div>
    </div>
  );
}

export type { Variant as DashboardConfigFormVariant };
