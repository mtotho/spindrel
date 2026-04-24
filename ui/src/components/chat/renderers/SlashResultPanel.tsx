import type { ReactNode } from "react";

/** Shared chrome for any slash-command result renderer.
 *
 * Every result panel (/help, /find, /context, future commands) should wrap its
 * body in this so chat-mode styling stays consistent. Terminal mode = sharp
 * corners + monospace; default = rounded + system font. The header handles the
 * `/cmd` eyebrow + right-aligned meta string.
 */
interface Props {
  chatMode?: "default" | "terminal";
  commandLabel: string;
  meta?: ReactNode;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

export function SlashResultPanel({
  chatMode = "default",
  commandLabel,
  meta,
  title,
  children,
  footer,
}: Props) {
  const isTerminal = chatMode === "terminal";
  const shell = isTerminal
    ? "my-2 rounded-none border border-surface-border/60 bg-surface-raised font-mono text-[13px]"
    : "my-2 rounded-md border border-surface-border bg-surface-raised";
  const headerBase =
    "flex items-baseline justify-between gap-3 px-3 py-2 border-b border-surface-border/60";
  const eyebrowBase = isTerminal
    ? "text-[11px] uppercase tracking-wider text-text-dim"
    : "text-[10px] uppercase tracking-[0.08em] text-text-dim/70";
  return (
    <div className={shell}>
      <div className={headerBase}>
        <div className="flex items-baseline gap-2 min-w-0">
          <span className={eyebrowBase}>{commandLabel}</span>
          {title !== undefined && (
            <span className="text-sm text-text truncate">{title}</span>
          )}
        </div>
        {meta !== undefined && (
          <span className="text-[11px] text-text-dim shrink-0">{meta}</span>
        )}
      </div>
      {children}
      {footer !== undefined && (
        <div className="px-3 py-2 text-[11px] text-text-dim border-t border-surface-border/60">
          {footer}
        </div>
      )}
    </div>
  );
}
