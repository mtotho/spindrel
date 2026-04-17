import { useEffect, useRef, useState } from "react";
import { PauseCircle, X } from "lucide-react";
import { useFindings } from "./FindingsPanel";
import { cn } from "@/src/lib/cn";

// ---------------------------------------------------------------------------
// Sticky in-chat chip that appears when a pipeline on this channel is paused
// for user input AND the corresponding anchor card isn't visible in the scroll
// viewport. Click scrolls to the newest awaiting anchor; dismiss hides it
// until the next new finding arrives.
//
// Rides on the `data-task-id` / `data-awaiting-review` attributes the
// TaskRunEnvelope stamps on its outer container. An IntersectionObserver
// tracks which awaiting anchors are in view; when none are, the chip shows.
// ---------------------------------------------------------------------------

interface Props {
  channelId: string;
  /** The scrollable chat region. Observer is scoped to this root so the chip
   *  responds to scroll position, not viewport position. */
  scrollRootRef?: React.RefObject<HTMLElement | null>;
}

export function ReviewNeededChip({ channelId, scrollRootRef }: Props) {
  const { findings, count } = useFindings(channelId);
  const [dismissedKey, setDismissedKey] = useState<string>("");
  const [anyAwaitingVisible, setAnyAwaitingVisible] = useState(false);

  // Key that changes when the set of awaiting task_ids changes — dismissing
  // the chip only hides it until a NEW finding arrives.
  const key = findings
    .map((f) => `${f.task.id}:${f.stepIndex}`)
    .sort()
    .join(",");

  // Track whether any awaiting anchor is in the viewport. Re-observe whenever
  // the set of findings changes (new anchors may have streamed in).
  const mutationRef = useRef<MutationObserver | null>(null);
  useEffect(() => {
    if (count === 0) {
      setAnyAwaitingVisible(false);
      return;
    }

    const root = scrollRootRef?.current ?? null;
    const findAnchors = () =>
      (root ?? document).querySelectorAll<HTMLElement>(
        '[data-task-id][data-awaiting-review="true"]',
      );

    const visible = new Set<Element>();
    const intersectionObserver = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target);
          else visible.delete(e.target);
        }
        setAnyAwaitingVisible(visible.size > 0);
      },
      { root, threshold: 0.1 },
    );

    const observeAll = () => {
      visible.clear();
      intersectionObserver.disconnect();
      findAnchors().forEach((el) => intersectionObserver.observe(el));
    };
    observeAll();

    // React re-renders the message list when new anchors stream in — watch
    // the DOM for added/removed anchor nodes and re-observe.
    const target = root ?? document.body;
    mutationRef.current = new MutationObserver(() => observeAll());
    mutationRef.current.observe(target, { childList: true, subtree: true });

    return () => {
      intersectionObserver.disconnect();
      mutationRef.current?.disconnect();
    };
  }, [count, key, scrollRootRef]);

  if (count === 0) return null;
  if (dismissedKey === key) return null;
  if (anyAwaitingVisible) return null;

  const handleScroll = () => {
    const root = scrollRootRef?.current ?? document;
    const anchor = (root as ParentNode).querySelector<HTMLElement>(
      '[data-task-id][data-awaiting-review="true"]',
    );
    if (anchor) {
      anchor.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <div
      className={cn(
        "absolute top-2 left-1/2 -translate-x-1/2 z-20",
        "inline-flex items-center gap-2 px-3 py-1.5 rounded-full",
        "bg-accent/15 border border-accent/50 backdrop-blur-sm",
        "shadow-[0_6px_20px_rgba(0,0,0,0.2)]",
      )}
    >
      <button
        onClick={handleScroll}
        className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-accent
                   hover:underline"
      >
        <PauseCircle size={12} className="animate-pulse" />
        Review needed
        <span className="opacity-80">↓</span>
      </button>
      <button
        onClick={() => setDismissedKey(key)}
        className="p-0.5 text-accent/70 hover:text-accent"
        aria-label="Dismiss"
      >
        <X size={11} />
      </button>
    </div>
  );
}
