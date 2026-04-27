import type { ReactNode } from "react";

/**
 * Compact eyebrow for a mobile hub section. Sits above the section's
 * tonal block. Optional count chip mirrors `SettingsGroupLabel`.
 */
export function SectionHeading({
  icon,
  label,
  count,
  action,
}: {
  icon?: ReactNode;
  label: string;
  count?: number;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[20px] items-center gap-1.5 px-1">
      {icon ? <span className="text-text-dim">{icon}</span> : null}
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {label}
      </span>
      {count != null ? (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
          {count}
        </span>
      ) : null}
      {action ? <div className="ml-auto shrink-0">{action}</div> : null}
    </div>
  );
}
