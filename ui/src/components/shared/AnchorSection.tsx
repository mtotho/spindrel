import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type AnchorSectionEmphasis = "primary" | "secondary" | "quiet";

export function AnchorSection({
  icon,
  eyebrow,
  title,
  meta,
  action,
  children,
  emphasis = "secondary",
  className,
  bodyClassName,
  testId,
}: {
  icon?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  emphasis?: AnchorSectionEmphasis;
  className?: string;
  bodyClassName?: string;
  testId?: string;
}) {
  const shellClass =
    emphasis === "quiet"
      ? "space-y-2"
      : emphasis === "primary"
        ? "relative rounded-md bg-surface-raised/80 p-3 before:absolute before:left-3 before:top-0 before:h-[2px] before:w-10 before:rounded-full before:bg-emphasis/70"
        : "rounded-md bg-surface-raised/60 p-3";

  const bodyClass =
    emphasis === "quiet"
      ? ""
      : emphasis === "primary"
        ? "mt-3"
        : "mt-2.5";

  return (
    <section data-testid={testId} className={cn(shellClass, className)}>
      <div className="flex min-h-[28px] items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          {icon ? (
            <span
              className={cn(
                "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
                emphasis === "primary" ? "bg-emphasis/10 text-emphasis" : "bg-surface-overlay/45 text-text-dim",
              )}
            >
              {icon}
            </span>
          ) : null}
          <div className="min-w-0">
            {eyebrow ? (
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                {eyebrow}
              </div>
            ) : null}
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <h2 className="min-w-0 truncate text-[15px] font-semibold leading-5 text-text">{title}</h2>
              {meta ? <div className="shrink-0 text-xs text-text-dim">{meta}</div> : null}
            </div>
          </div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className={cn(bodyClass, bodyClassName)}>{children}</div>
    </section>
  );
}
