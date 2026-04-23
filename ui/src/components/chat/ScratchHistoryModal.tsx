import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import { useScratchHistory } from "@/src/api/hooks/useEphemeralSession";

interface ScratchHistoryModalProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "?";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** List of the caller's scratch sessions on a channel. Selecting a row
 *  navigates to the read-only scratch viewer route. */
export function ScratchHistoryModal({ open, onClose, channelId }: ScratchHistoryModalProps) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useScratchHistory(open ? channelId : null);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-[9995] bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Session history"
        className="fixed z-[9996] inset-x-4 top-16 bottom-16 md:inset-auto md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:w-[520px] md:max-h-[75vh] rounded-xl bg-surface-raised border border-surface-border shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col overflow-hidden"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
          <span className="text-sm font-semibold text-text">Session history</span>
          <button
            onClick={onClose}
            className="p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="p-6 text-sm text-text-dim">Loading…</div>
          )}
          {error && (
            <div className="p-6 text-sm text-red-400">
              {error instanceof Error ? error.message : "Failed to load history"}
            </div>
          )}
          {!isLoading && !error && data && data.length === 0 && (
            <div className="p-6 text-sm text-text-dim">
              No prior sessions yet.
            </div>
          )}
          {!isLoading && !error && data && data.length > 0 && (
            <ul className="divide-y divide-surface-border">
              {data.map((row) => (
                <li key={row.session_id}>
                  <button
                    onClick={() => {
                      onClose();
                      navigate(`/channels/${channelId}/session/${row.session_id}?scratch=true`);
                    }}
                    className="w-full text-left px-4 py-3 hover:bg-white/5 transition-colors flex flex-col gap-1"
                  >
                    <div className="flex items-center gap-2 text-xs text-text-dim">
                      <span>{formatTimestamp(row.created_at)}</span>
                      <span>·</span>
                      <span>{row.message_count} msg{row.message_count === 1 ? "" : "s"}</span>
                      {row.is_current && (
                        <span className="ml-auto px-1.5 py-0.5 rounded bg-accent/20 text-accent text-[10px] uppercase tracking-wider">
                          Current
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-text truncate">
                      {row.title?.trim() || row.preview || <em className="text-text-dim">(empty)</em>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
