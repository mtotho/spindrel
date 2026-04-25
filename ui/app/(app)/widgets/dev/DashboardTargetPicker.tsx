/**
 * DashboardTargetPicker — explicit selector for the dashboard that dev-panel
 * Pin actions target. Seeded from ``?from=<slug>`` (the Developer panel link
 * carries the dashboard the user came from), falls back to localStorage, then
 * to ``"default"``.
 *
 * Writes the chosen slug to ``useDashboardPinsStore.currentSlug`` via
 * ``hydrate`` — every pin flow (Tools, Recent, Templates) already consumes
 * ``currentSlug`` inside ``pinWidget``, so switching the picker reroutes all
 * three without further plumbing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, Hash, LayoutDashboard } from "lucide-react";
import { useChannels } from "@/src/api/hooks/useChannels";
import {
  useDashboards,
  channelIdFromSlug,
  isChannelSlug,
  isReservedListingSlug,
} from "@/src/stores/dashboards";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";

const STORAGE_KEY = "spindrel:widgets:dev:dashboard-slug";

function loadStoredSlug(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistSlug(slug: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, slug);
  } catch {
    // private mode etc. — harmless
  }
}

export function DashboardTargetPicker() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { allDashboards, isLoading } = useDashboards();
  const { data: channels } = useChannels();
  const currentSlug = useDashboardPinsStore((s) => s.currentSlug);
  const hydrate = useDashboardPinsStore((s) => s.hydrate);
  const seedDone = useRef(false);
  const [open, setOpen] = useState(false);

  // One-time seed: if the URL carries ``?from=<slug>`` use it, otherwise fall
  // back to localStorage. Either way, reconcile against currentSlug so we
  // don't clobber a slug the caller already loaded via the /widgets page.
  useEffect(() => {
    if (seedDone.current) return;
    const fromParam = searchParams.get("from");
    const stored = loadStoredSlug();
    const seed = fromParam ?? stored;
    if (seed && seed !== currentSlug) {
      void hydrate(seed);
    }
    if (fromParam) {
      // Clean the param so refreshes fall through to localStorage.
      const next = new URLSearchParams(searchParams);
      next.delete("from");
      setSearchParams(next, { replace: true });
    }
    seedDone.current = true;
  }, [searchParams, currentSlug, hydrate, setSearchParams]);

  // Keep localStorage in sync with whatever the rest of the app sets.
  useEffect(() => {
    persistSlug(currentSlug);
  }, [currentSlug]);

  const channelNameBySlug = useMemo(() => {
    const map = new Map<string, string>();
    if (!channels) return map;
    for (const d of allDashboards) {
      if (!isChannelSlug(d.slug)) continue;
      const chId = channelIdFromSlug(d.slug);
      if (!chId) continue;
      const ch = channels.find((c) => c.id === chId);
      if (ch) map.set(d.slug, ch.name);
    }
    return map;
  }, [channels, allDashboards]);

  const userDashboards = allDashboards.filter((d) => !isReservedListingSlug(d.slug));
  const channelDashboards = allDashboards.filter((d) => isChannelSlug(d.slug));

  const active = allDashboards.find((d) => d.slug === currentSlug);
  const activeIsChannel = isChannelSlug(currentSlug);
  const activeLabel = active
    ? activeIsChannel
      ? channelNameBySlug.get(currentSlug) ?? active.name
      : active.name
    : currentSlug;

  const menuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const choose = (slug: string) => {
    if (slug === currentSlug) {
      setOpen(false);
      return;
    }
    void hydrate(slug);
    setOpen(false);
  };

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-[12px] font-medium text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Dashboard that Pin actions target"
      >
        {activeIsChannel ? (
          <Hash size={12} className="text-accent" />
        ) : (
          <LayoutDashboard size={12} />
        )}
        <span className="max-w-[140px] truncate">
          {isLoading ? "Loading…" : activeLabel}
        </span>
        <ChevronDown size={12} className="text-text-dim" />
      </button>
      {open && (
        <div
          className="absolute right-0 z-20 mt-1 min-w-[220px] rounded-md bg-surface-raised shadow-lg border border-surface-border py-1 max-h-[60vh] overflow-auto"
          role="listbox"
        >
          <div className="px-2.5 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-text-dim">
            Pin to dashboard
          </div>
          {userDashboards.length === 0 && channelDashboards.length === 0 && (
            <div className="px-3 py-2 text-[11px] text-text-dim">
              No dashboards yet.
            </div>
          )}
          {userDashboards.length > 0 && (
            <ul className="py-0.5">
              {userDashboards.map((d) => (
                <li key={d.slug}>
                  <button
                    type="button"
                    onClick={() => choose(d.slug)}
                    className={
                      "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors " +
                      (d.slug === currentSlug
                        ? "bg-accent/10 text-accent"
                        : "text-text hover:bg-surface-overlay")
                    }
                    role="option"
                    aria-selected={d.slug === currentSlug}
                  >
                    <LayoutDashboard size={12} className="text-text-dim" />
                    <span className="flex-1 truncate">{d.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {channelDashboards.length > 0 && (
            <>
              <div className="mx-2 my-1 h-px bg-surface-border/60" />
              <div className="px-2.5 pt-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-dim">
                Channels
              </div>
              <ul className="py-0.5">
                {channelDashboards.map((d) => {
                  const name = channelNameBySlug.get(d.slug) ?? d.name;
                  return (
                    <li key={d.slug}>
                      <button
                        type="button"
                        onClick={() => choose(d.slug)}
                        className={
                          "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors " +
                          (d.slug === currentSlug
                            ? "bg-accent/10 text-accent"
                            : "text-text hover:bg-surface-overlay")
                        }
                        role="option"
                        aria-selected={d.slug === currentSlug}
                      >
                        <Hash size={12} className="text-accent" />
                        <span className="flex-1 truncate">{name}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
