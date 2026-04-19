import { Link } from "react-router-dom";
import { Lock, Home } from "lucide-react";

interface Props {
  title?: string;
  message?: string;
}

export function UnauthorizedCard({
  title = "Admin only",
  message = "This page is restricted to administrators. If you think you should have access, ask an admin to grant you the relevant scopes.",
}: Props) {
  return (
    <div className="flex-1 flex flex-row items-center justify-center p-6 bg-surface">
      <div className="max-w-md w-full rounded-xl border border-surface-border bg-surface-raised p-8 text-center flex flex-col items-center gap-4">
        <div className="w-12 h-12 rounded-full bg-surface-overlay flex flex-row items-center justify-center">
          <Lock size={22} className="text-text-dim" />
        </div>
        <div className="flex flex-col gap-2">
          <div className="text-[15px] font-semibold text-text">{title}</div>
          <div className="text-[12px] text-text-muted leading-relaxed">{message}</div>
        </div>
        <Link
          to="/"
          className="inline-flex flex-row items-center gap-1.5 px-4 py-2 rounded-md bg-accent text-white text-[12px] font-semibold no-underline"
        >
          <Home size={13} />
          Back to home
        </Link>
      </div>
    </div>
  );
}
