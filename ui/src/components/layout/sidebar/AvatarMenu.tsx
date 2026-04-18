import { useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import { Link } from "react-router-dom";
import { User } from "lucide-react";
import { useAuthStore } from "../../../stores/auth";

interface Props {
  anchorRef: React.RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  version?: string;
}

export function AvatarMenu({ anchorRef, open, onClose, version }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!ref.current) return;
      if (ref.current.contains(e.target as Node)) return;
      if (anchorRef.current?.contains(e.target as Node)) return;
      onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  const anchorRect = anchorRef.current?.getBoundingClientRect();
  const bottom = anchorRect ? window.innerHeight - anchorRect.top + 6 : 60;
  const left = anchorRect ? anchorRect.right + 6 : 54;

  const initial = user?.display_name?.charAt(0)?.toUpperCase() || "?";

  return ReactDOM.createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label="Account menu"
      className="fixed z-[10020] w-[240px] rounded-xl border border-surface-border bg-surface-raised shadow-2xl overflow-hidden"
      style={{ bottom, left }}
    >
      <div className="px-4 py-3 border-b border-surface-border flex flex-row items-center gap-3">
        <div className="w-9 h-9 rounded-md flex flex-row items-center justify-center bg-indigo-500/20">
          <span className="text-sm font-bold text-indigo-500">{initial}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] text-text font-medium truncate">
            {user?.display_name || "Profile"}
          </div>
          {user?.email && (
            <div className="text-[11px] text-text-dim truncate">{user.email}</div>
          )}
        </div>
      </div>

      <div className="py-1">
        <Link
          to="/profile"
          onClick={onClose}
          className="flex flex-row items-center gap-2.5 px-4 py-2 text-[13px] text-text-muted hover:bg-surface-overlay/60 hover:text-text transition-colors"
        >
          <User size={14} className="text-text-dim" />
          Profile
        </Link>
      </div>

      {version && (
        <div className="px-4 py-2 border-t border-surface-border text-[10px] text-text-dim/60 text-center">
          v{version}
        </div>
      )}
    </div>,
    document.body,
  );
}
