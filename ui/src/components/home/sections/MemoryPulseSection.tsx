import { Brain, ChevronRight, FileText } from "lucide-react";
import { Link } from "react-router-dom";

import { useMemoryObservatory } from "../../../api/hooks/useLearningOverview";
import { MEMORY_CENTER_HREF } from "../../../lib/hubRoutes";
import { SectionHeading } from "./SectionHeading";

const MAX_FILES = 3;
const MAX_BOTS = 3;

/**
 * Mobile slice of the Memory Observatory: most-active bots and the
 * hottest memory files in the recent window. Renders nothing when no
 * activity is recorded.
 */
export function MemoryPulseSection() {
  const { data } = useMemoryObservatory(2);
  const activeBots = (data?.bots ?? []).slice(0, MAX_BOTS);
  const hotFiles = (data?.hot_files ?? []).slice(0, MAX_FILES);

  if (activeBots.length === 0 && hotFiles.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Brain size={14} />} label="Memory pulse" />
      <div className="flex flex-col gap-1">
        {activeBots.map((bot) => (
          <Link
            key={`bot-${bot.bot_id}`}
            to={MEMORY_CENTER_HREF}
            className="group flex min-h-[56px] items-center gap-3 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-text">{bot.bot_name}</div>
              <div className="truncate text-xs text-text-dim">
                {bot.write_count} write{bot.write_count === 1 ? "" : "s"}
                {bot.hot_files.length > 0
                  ? ` · ${bot.hot_files.length} hot file${bot.hot_files.length === 1 ? "" : "s"}`
                  : ""}
              </div>
            </div>
            <ChevronRight
              size={14}
              className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
            />
          </Link>
        ))}
        {hotFiles.map((file) => (
          <Link
            key={`file-${file.id}`}
            to={MEMORY_CENTER_HREF}
            className="group flex min-h-[56px] items-center gap-3 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45"
          >
            <FileText size={14} className="shrink-0 text-text-dim" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-text">{file.file_path}</div>
              <div className="truncate text-xs text-text-dim">
                {file.bot_name} · {file.write_count} write{file.write_count === 1 ? "" : "s"}
              </div>
            </div>
            <ChevronRight
              size={14}
              className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
            />
          </Link>
        ))}
      </div>
    </section>
  );
}
