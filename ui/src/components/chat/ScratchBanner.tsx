import { useNavigate } from "react-router-dom";
import { Minimize2, NotebookPen } from "lucide-react";
import { useScratchReturnStore } from "@/src/stores/scratchReturn";

interface ScratchBannerProps {
  channelId: string;
  channelName?: string | null;
  archive?: boolean;
}

/** Signature affordance of the full-page scratch view. Explains what the
 *  scratch pad is so a user who landed here via Maximize doesn't think
 *  they've navigated away from the channel. The single action is a
 *  "minimize" back to the parent channel (word chosen over X so the user
 *  doesn't read it as wiping their scratch work). */
export function ScratchBanner({ channelId, channelName, archive }: ScratchBannerProps) {
  const navigate = useNavigate();
  const clearScratchReturn = useScratchReturnStore((s) => s.clearScratchReturn);
  const label = channelName ? `#${channelName}` : "channel";

  const handleMinimize = () => {
    clearScratchReturn(channelId);
    navigate(`/channels/${channelId}`);
  };

  return (
    <div className="mx-3 mt-2 rounded-md bg-surface-raised border border-surface-border px-3 py-1.5 flex items-center gap-2 text-[12px]">
      <NotebookPen size={13} className="text-accent shrink-0" />
      <span className="font-semibold text-text shrink-0">
        {archive ? "Archived scratch" : "Scratch pad"}
      </span>
      <span className="text-text-dim truncate hidden md:inline">
        {archive
          ? "— read-only view of a previous scratch session."
          : "— messages here don't join the channel's history."}
      </span>
      <button
        type="button"
        onClick={handleMinimize}
        title={`Back to ${label}`}
        aria-label={`Minimize scratch and return to ${label}`}
        className="ml-auto shrink-0 p-1 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
      >
        <Minimize2 size={13} />
      </button>
    </div>
  );
}
