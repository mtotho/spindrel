import type { DashboardRail } from "@/src/stores/dashboards";

/**
 * Three mutually-exclusive rail-scope choices for a widget dashboard.
 * - `"off"`    no rail entry for me (everyone row is unaffected unless admin)
 * - `"everyone"` pinned for all users (admin-only write; see backend)
 * - `"me"`     pinned just for the current user
 */
export type RailChoice = "off" | "everyone" | "me";

/** Map a server-resolved ``rail`` block to the picker's selected choice. */
export function resolveRailChoice(rail: DashboardRail | undefined | null): RailChoice {
  if (!rail) return "off";
  if (rail.everyone_pinned) return "everyone";
  if (rail.me_pinned) return "me";
  return "off";
}

interface Props {
  value: RailChoice;
  onChange: (next: RailChoice) => void;
  isAdmin: boolean;
  disabled?: boolean;
}

const OPTIONS: { id: RailChoice; label: string; description: string }[] = [
  { id: "off", label: "Off", description: "Not in my sidebar rail." },
  {
    id: "everyone",
    label: "For everyone",
    description: "Show in every user's sidebar rail.",
  },
  {
    id: "me",
    label: "Just me",
    description: "Show only in my sidebar rail.",
  },
];

export function RailScopePicker({ value, onChange, isAdmin, disabled }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-text-muted">
        Show in sidebar rail
      </span>
      <div className="flex flex-col gap-1.5">
        {OPTIONS.map((opt) => {
          const checked = value === opt.id;
          const everyoneLocked = opt.id === "everyone" && !isAdmin;
          const rowDisabled = disabled || everyoneLocked;
          const title = everyoneLocked
            ? "Only admins can pin a dashboard for everyone"
            : undefined;
          return (
            <label
              key={opt.id}
              title={title}
              className={
                "flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors " +
                (rowDisabled
                  ? "border-surface-border opacity-60 cursor-not-allowed"
                  : checked
                    ? "border-accent/60 bg-accent/[0.08] cursor-pointer"
                    : "border-surface-border hover:bg-surface-overlay cursor-pointer")
              }
            >
              <input
                type="radio"
                name="rail-scope"
                checked={checked}
                onChange={() => {
                  if (!rowDisabled) onChange(opt.id);
                }}
                disabled={rowDisabled}
                className="mt-0.5 h-3.5 w-3.5 accent-accent"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[12.5px] font-medium text-text">
                    {opt.label}
                  </span>
                  {everyoneLocked && (
                    <span className="rounded-sm bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-dim">
                      Admins only
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-[11px] text-text-dim leading-snug">
                  {opt.description}
                </div>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}
