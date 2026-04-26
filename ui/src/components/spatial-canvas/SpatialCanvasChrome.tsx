import { useEffect, useMemo, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { LENS_HINT_SEEN_KEY } from "./spatialGeometry";

export function AddWidgetButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onPointerDown={(e) => e.stopPropagation()}
      title="Add widget to canvas"
      aria-label="Add widget to canvas"
      className="flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-accent text-xs cursor-pointer"
    >
      <LayoutGrid size={13} />
      <span className="hidden sm:inline">Add</span>
    </button>
  );
}

export function CanvasStarfield() {
  const stars = useMemo(() => {
    let s = 0xc0ffee;
    function rand() {
      s |= 0;
      s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    const out: Array<{ x: number; y: number; r: number; o: number; phase: number; dur: number; warm: number }> = [];
    for (let i = 0; i < 220; i++) {
      const tier = rand();
      out.push({
        x: rand() * 100,
        y: rand() * 100,
        r: tier > 0.97 ? 1.4 : tier > 0.85 ? 0.9 : 0.5,
        o: tier > 0.97 ? 0.85 : tier > 0.85 ? 0.55 : 0.30,
        phase: rand() * 8,
        dur: 4 + rand() * 4,
        warm: rand(),
      });
    }
    return out;
  }, []);
  return (
    <div className="canvas-starfield absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
      >
        {stars.map((s, i) => {
          const fill =
            s.warm > 0.92 ? "var(--star-warm)" :
            s.warm > 0.6  ? "var(--star-blue-mid)" :
                            "var(--star-blue-deep)";
          return (
            <circle
              key={i}
              cx={s.x}
              cy={s.y}
              r={s.r * 0.05}
              fill={fill}
              opacity={s.o}
              style={{
                animation: `canvas-star-twinkle ${s.dur}s ease-in-out infinite`,
                animationDelay: `${s.phase}s`,
              }}
            />
          );
        })}
      </svg>
    </div>
  );
}

export function LensHint() {
  const [visible, setVisible] = useState(false);
  const [opacity, setOpacity] = useState(0);
  useEffect(() => {
    let seen = false;
    try {
      seen = localStorage.getItem(LENS_HINT_SEEN_KEY) === "1";
    } catch {
      /* storage disabled — show every time */
    }
    if (seen) return;
    setVisible(true);
    const inT = window.setTimeout(() => setOpacity(0.95), 30);
    const outT = window.setTimeout(() => setOpacity(0), 4500);
    const removeT = window.setTimeout(() => {
      setVisible(false);
      try {
        localStorage.setItem(LENS_HINT_SEEN_KEY, "1");
      } catch {
        /* ignore */
      }
    }, 6000);
    return () => {
      window.clearTimeout(inT);
      window.clearTimeout(outT);
      window.clearTimeout(removeT);
    };
  }, []);
  if (!visible) return null;
  return (
    <div
      className="absolute bottom-4 left-4 z-[2] flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-md backdrop-blur border bg-surface-raised/85 border-surface-border text-text-dim text-xs select-none pointer-events-none"
      style={{ opacity, transition: "opacity 600ms ease-out" }}
      aria-live="polite"
    >
      <kbd className="rounded px-1.5 py-0 font-mono text-[10px] leading-tight border border-surface-border bg-surface-overlay/70 text-text-muted">
        Space
      </kbd>
      <span>hold to focus</span>
    </div>
  );
}

export function ShortcutChip() {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="relative"
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label="Keyboard shortcuts"
        className="flex flex-row items-center gap-1 px-2 py-1.5 rounded-md bg-surface-raised/85 backdrop-blur border border-surface-border text-text-dim hover:text-text text-[11px] font-mono cursor-default"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <span>⌘</span>
        <span>Q</span>
      </button>
      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-[3] flex flex-col gap-1 px-3 py-2.5 rounded-md bg-surface-raised/95 backdrop-blur border border-surface-border text-[11px] text-text-dim min-w-[240px] shadow-lg">
          <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">
            Keyboard
          </div>
          <ShortcutRow keys={["Q"]} label="Open command menu" />
          <ShortcutRow keys={["Space"]} label="Focus lens (hold)" />
          <ShortcutRow keys={["F"]} label="Fit all to viewport" />
          <ShortcutRow keys={["+", "−"]} label="Zoom in / out" />
          <ShortcutRow keys={["Esc"]} label="Close overlay or menu" />
          <div className="text-[10px] uppercase tracking-wider text-text-muted mt-2 mb-1">
            Pointer
          </div>
          <ShortcutRow keys={["Right-click"]} label="Context menu on tile" />
          <ShortcutRow keys={["Long-press"]} label="Touch: command menu / drag tile" />
        </div>
      )}
    </div>
  );
}

function ShortcutRow({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex flex-row items-center gap-2">
      <div className="flex flex-row gap-1">
        {keys.map((k, i) => (
          <kbd
            key={i}
            className="rounded px-1.5 py-0 font-mono text-[10px] leading-tight border border-surface-border bg-surface-overlay/70 text-text-muted"
          >
            {k}
          </kbd>
        ))}
      </div>
      <span>{label}</span>
    </div>
  );
}
