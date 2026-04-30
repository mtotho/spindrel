// Unified "+" button for the composer. Consolidates attach + skills behind
// one trigger so the main toolbar row isn't cluttered with separate icons.
//
// Click + → popover with:
//   • Attach files or photos  → opens the OS file picker (hidden <input>)
//   • Skills ›                → expands inline into the shared SkillsInContextPanel
//
// Purple count badge appears on the trigger when any skills are loaded or queued.

import { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Plus, Paperclip, Sparkles, ChevronRight, ArrowLeft, Wrench, Gauge, AlertCircle, CheckCircle2 } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";
import { useAgentCapabilities } from "../../api/hooks/useAgentCapabilities";
import { AgentReadinessPanel } from "../shared/AgentReadinessPanel";
import { SkillsInContextPanel, useSkillsInContext } from "./SkillsInContextPanel";
import { ToolsInContextPanel, useToolsPosture } from "./ToolsInContextPanel";

const FILE_ACCEPT =
  "image/*,.pdf,.txt,.csv,.json,.md,.yaml,.yml,.xml,.html,.log,.py,.js,.ts,.sh,.doc,.docx,.xlsx,.xls,.pptx";

interface ComposerAddMenuProps {
  channelId?: string;
  botId?: string;
  composerText: string;
  onInsertSkillTag: (skillId: string) => void;
  onInsertToolTag?: (toolName: string) => void;
  onAttachFiles: (files: FileList) => void;
  disabled?: boolean;
  isMobile?: boolean;
}

type View = "root" | "skills" | "tools" | "readiness";

export function ComposerAddMenu({
  channelId,
  botId,
  composerText,
  onInsertSkillTag,
  onInsertToolTag,
  onAttachFiles,
  disabled = false,
  isMobile = false,
}: ComposerAddMenuProps) {
  const t = useThemeTokens();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("root");
  const [pos, setPos] = useState<{ bottom: number; left: number }>({ bottom: 0, left: 0 });

  const { count } = useSkillsInContext({ channelId, composerText });
  const empty = count === 0;

  const { pinnedCount } = useToolsPosture({ channelId, botId });
  const toolsEmpty = pinnedCount === 0;
  const { data: readiness } = useAgentCapabilities({
    botId,
    channelId,
    includeEndpoints: false,
    includeSchemas: false,
    maxTools: 12,
    enabled: Boolean(botId || channelId),
  });

  // Outside click dismiss.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Escape — back up a view, or close from root.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (view !== "root") {
        setView("root");
      } else {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, view]);

  // Reset view every time the popover opens.
  useEffect(() => {
    if (open) setView("root");
  }, [open]);

  const togglePopover = () => {
    if (!triggerRef.current) {
      setOpen((v) => !v);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const width = isMobile ? Math.min(window.innerWidth - 16, 360) : 320;
    const left = isMobile
      ? Math.max(8, (window.innerWidth - width) / 2)
      : Math.max(12, rect.left);
    setPos({ bottom: window.innerHeight - rect.top + 8, left });
    setOpen((v) => !v);
  };

  const handleAttachClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onAttachFiles(e.target.files);
      setOpen(false);
    }
    e.target.value = "";
  };

  const width = isMobile ? Math.min(window.innerWidth - 16, 360) : 320;
  // Sub-views (tools/skills) need a DEFINITE height so inner `flex-1 min-h-0`
  // children can distribute space + the list's `overflow-y-auto` engages.
  // `maxHeight` alone lets content grow past the visible area and clips the
  // top (header + search become unreachable). Root view stays auto-sized.
  const inSubView = view === "skills" || view === "tools" || view === "readiness";
  const sizedHeight = inSubView ? "min(60vh, 520px)" : undefined;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="input-action-btn"
        onClick={togglePopover}
        disabled={disabled}
        aria-label="Add"
        aria-expanded={open}
        title="Add"
        style={{
          width: 44,
          height: 44,
          flexShrink: 0,
          position: "relative",
          opacity: disabled ? 0.4 : 1,
        }}
      >
        <Plus size={isMobile ? 20 : 22} color={t.textDim} />
        {!empty && (
          <span
            style={{
              position: "absolute",
              top: 4,
              right: 4,
              minWidth: 14,
              height: 14,
              padding: "0 3px",
              borderRadius: 7,
              background: t.purple,
              color: "#fff",
              fontSize: 9,
              fontWeight: 700,
              lineHeight: "14px",
              textAlign: "center",
              pointerEvents: "none",
            }}
          >
            {count}
          </span>
        )}
      </button>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={FILE_ACCEPT}
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      {open &&
        ReactDOM.createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            aria-label="Add to message"
            className="fixed z-[10000] flex flex-col rounded-lg border shadow-xl overflow-hidden"
            style={{
              bottom: pos.bottom,
              left: pos.left,
              width,
              height: sizedHeight,
              backgroundColor: t.surfaceRaised,
              borderColor: t.surfaceBorder,
            }}
          >
            {view === "root" ? (
              <div className="flex flex-col py-1">
                <ReadinessMenuRow
                  status={readiness?.doctor.status}
                  message={readiness?.doctor.findings?.[0]?.message}
                  onClick={() => setView("readiness")}
                />
                <MenuRow
                  icon={<Paperclip size={14} color={t.textMuted} />}
                  label="Attach files or photos"
                  onClick={handleAttachClick}
                />
                <MenuRow
                  icon={<Sparkles size={14} color={empty ? t.textMuted : t.purple} />}
                  label="Skills"
                  badge={empty ? undefined : String(count)}
                  trailing={<ChevronRight size={12} color={t.textDim} />}
                  onClick={() => setView("skills")}
                />
                <MenuRow
                  icon={<Wrench size={14} color={toolsEmpty ? t.textMuted : t.purple} />}
                  label="Tools"
                  badge={toolsEmpty ? undefined : String(pinnedCount)}
                  trailing={<ChevronRight size={12} color={t.textDim} />}
                  onClick={() => setView("tools")}
                />
              </div>
            ) : (
              <div className="flex flex-col flex-1 min-h-0">
                <button
                  onClick={() => setView("root")}
                  className="flex flex-row items-center gap-1.5 px-3 py-1.5 text-[11px] text-text-dim hover:text-text bg-transparent border-none cursor-pointer text-left shrink-0"
                  style={{ borderBottom: `1px solid ${t.surfaceBorder}55` }}
                  aria-label="Back"
                >
                  <ArrowLeft size={11} />
                  Back
                </button>
                <div className="flex-1 min-h-0 flex flex-col">
                  {view === "skills" ? (
                    <SkillsInContextPanel
                      channelId={channelId}
                      composerText={composerText}
                      botId={botId}
                      onInsertSkillTag={(skillId) => {
                        onInsertSkillTag(skillId);
                        setOpen(false);
                      }}
                      onClose={() => setOpen(false)}
                    />
                  ) : view === "tools" ? (
                    <ToolsInContextPanel
                      channelId={channelId}
                      botId={botId}
                      onInsertToolTag={(toolName) => {
                        onInsertToolTag?.(toolName);
                        setOpen(false);
                      }}
                      onClose={() => setOpen(false)}
                    />
                  ) : (
                    <div className="overflow-y-auto p-3">
                      <AgentReadinessPanel botId={botId} channelId={channelId} compact={false} maxTools={12} />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

function ReadinessMenuRow({
  status,
  message,
  onClick,
}: {
  status?: string;
  message?: string;
  onClick: () => void;
}) {
  const t = useThemeTokens();
  const ok = status === "ok";
  const error = status === "error";
  const icon = ok
    ? <CheckCircle2 size={14} color={t.success} />
    : error
      ? <AlertCircle size={14} color={t.danger} />
      : <Gauge size={14} color={t.warning} />;
  const label = status ? status.replace(/_/g, " ") : "checking";
  const badgeColor = ok ? t.success : error ? t.danger : t.warning;
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full flex-row items-start gap-2.5 border-none bg-transparent px-3 py-2 text-left transition-colors hover:bg-white/[0.04]"
    >
      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-text">Agent readiness</span>
        <span className="mt-0.5 block truncate text-[10px] text-text-dim">
          {message || (ok ? "Ready to act with current grants" : "Inspect available tools, skills, and grants")}
        </span>
      </span>
      <span
        className="mt-px shrink-0 rounded px-1.5 py-px text-[9px] font-semibold uppercase"
        style={{ color: badgeColor, background: `${badgeColor}1A` }}
      >
        {label}
      </span>
      <ChevronRight size={12} color={t.textDim} className="mt-1 shrink-0" />
    </button>
  );
}

interface MenuRowProps {
  icon: React.ReactNode;
  label: string;
  badge?: string;
  trailing?: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}

function MenuRow({ icon, label, badge, trailing, onClick, disabled }: MenuRowProps) {
  const t = useThemeTokens();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex flex-row items-center gap-2.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-white/[0.04] disabled:opacity-40 disabled:cursor-default"
    >
      <span className="shrink-0 w-4 h-4 flex items-center justify-center">{icon}</span>
      <span className="flex-1 text-[13px] text-text truncate">{label}</span>
      {badge && (
        <span
          style={{
            padding: "1px 6px",
            borderRadius: 6,
            background: t.purpleSubtle,
            border: `1px solid ${t.purpleBorder}`,
            color: t.purple,
            fontSize: 10,
            fontWeight: 600,
            lineHeight: "14px",
          }}
        >
          {badge}
        </span>
      )}
      {trailing && <span className="shrink-0">{trailing}</span>}
    </button>
  );
}
