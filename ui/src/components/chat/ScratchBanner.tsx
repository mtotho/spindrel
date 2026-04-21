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
    <div className="mx-3 mt-3 rounded-lg bg-surface-raised border border-surface-border px-3 py-2 flex items-start gap-3">
      <div className="flex items-center justify-center w-7 h-7 rounded-md bg-accent/10 text-accent shrink-0 mt-0.5">
        <NotebookPen size={14} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-semibold text-text">
          {archive ? "Archived scratch session" : "Scratch pad — clean-slate session"}
        </div>
        <div className="text-[12px] text-text-dim leading-snug">
          {archive
            ? "Read-only view of a previous scratch session. Return to the current scratch to keep writing, or minimize to go back to the channel."
            : "Messages here don't join the channel's history. Iterate on prompts or try ideas without polluting the main chat."}
        </div>
      </div>
      <button
        type="button"
        onClick={handleMinimize}
        title={`Back to ${label}`}
        aria-label={`Minimize scratch and return to ${label}`}
        className="shrink-0 p-1.5 rounded text-text-dim hover:text-text hover:bg-white/5 transition-colors"
      >
        <Minimize2 size={14} />
      </button>
    </div>
  );
}
