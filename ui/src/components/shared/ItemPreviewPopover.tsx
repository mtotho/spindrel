/**
 * Lightweight hover popover for previewing capabilities, skills, and tools
 * inline without navigating away. Shows key details + link to admin page.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { ExternalLink } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "../../theme/tokens";

interface PopoverProps {
  children: React.ReactNode;
  content: React.ReactNode;
}

/**
 * Generic hover popover wrapper. Wraps `children` and shows `content`
 * in a floating card on hover (with a small delay to avoid flicker).
 */
export function HoverPopover({ children, content }: PopoverProps) {
  const t = useThemeTokens();
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<"below" | "above">("below");
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);

  const show = useCallback(() => {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      // Decide if popover should go above or below
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        setPosition(spaceBelow < 220 ? "above" : "below");
      }
      setVisible(true);
    }, 200);
  }, []);

  const hide = useCallback(() => {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setVisible(false), 150);
  }, []);

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  return (
    <div
      ref={containerRef}
      onMouseEnter={show}
      onMouseLeave={hide}
      style={{ position: "relative", display: "inline-flex" }}
    >
      {children}
      {visible && (
        <div
          onMouseEnter={show}
          onMouseLeave={hide}
          style={{
            position: "absolute",
            left: 0,
            ...(position === "below"
              ? { top: "calc(100% + 4px)" }
              : { bottom: "calc(100% + 4px)" }),
            zIndex: 9999,
            minWidth: 280,
            maxWidth: 360,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 8,
            boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {content}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Capability preview content
// ---------------------------------------------------------------------------

export interface CapabilityPreviewData {
  id: string;
  name: string;
  description?: string | null;
  skills: { id: string; mode?: string }[];
  local_tools: string[];
  mcp_tools: string[];
  pinned_tools: string[];
  includes: string[];
  source_type: string;
}

export function CapabilityPreview({ data }: { data: CapabilityPreviewData }) {
  const t = useThemeTokens();
  const router = useRouter();
  const totalTools = data.local_tools.length + data.mcp_tools.length + data.pinned_tools.length;
  const adminPath = `/admin/carapaces/${data.id.replaceAll("/", "--")}`;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text, flex: 1 }}>{data.name}</span>
        <span style={{
          fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
          background: t.surfaceOverlay, color: t.textDim,
        }}>
          {data.source_type}
        </span>
      </div>

      {data.description && (
        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.4" }}>
          {data.description}
        </div>
      )}

      {/* Stats */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {totalTools > 0 && (
          <Stat label="tools" value={totalTools} />
        )}
        {data.skills.length > 0 && (
          <Stat label="skills" value={data.skills.length} />
        )}
        {data.includes.length > 0 && (
          <Stat label="includes" value={data.includes.length} />
        )}
      </div>

      {/* Tool list (first few) */}
      {totalTools > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 3 }}>
            Tools
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            {[...data.local_tools, ...data.pinned_tools].slice(0, 8).map((name) => (
              <span key={name} style={{
                fontSize: 9, fontFamily: "monospace",
                padding: "1px 5px", borderRadius: 3,
                background: t.surfaceOverlay, color: t.textMuted,
              }}>
                {name}
              </span>
            ))}
            {totalTools > 8 && (
              <span style={{ fontSize: 9, color: t.textDim }}>
                +{totalTools - 8} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Skills list */}
      {data.skills.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 3 }}>
            Skills
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {data.skills.slice(0, 5).map((s) => (
              <span key={s.id} style={{ fontSize: 10, color: t.accent }}>
                {s.id}
                {s.mode && <span style={{ fontSize: 8, color: t.textDim, marginLeft: 4 }}>{s.mode}</span>}
              </span>
            ))}
            {data.skills.length > 5 && (
              <span style={{ fontSize: 9, color: t.textDim }}>+{data.skills.length - 5} more</span>
            )}
          </div>
        </div>
      )}

      {/* Link to detail page */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          router.push(adminPath as any);
        }}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: "none", border: "none", cursor: "pointer",
          fontSize: 11, color: t.accent, fontWeight: 500,
          padding: 0, marginTop: 2,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
        onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
      >
        View details
        <ExternalLink size={10} />
      </button>
    </>
  );
}

// ---------------------------------------------------------------------------
// Skill preview content
// ---------------------------------------------------------------------------

export interface SkillPreviewData {
  id: string;
  name: string;
  description?: string | null;
  source_type?: string;
  chunk_count?: number;
  mode?: string;
}

export function SkillPreview({ data }: { data: SkillPreviewData }) {
  const t = useThemeTokens();
  const router = useRouter();
  const adminPath = `/admin/skills/${data.id}`;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text, flex: 1 }}>{data.name || data.id}</span>
        {data.source_type && (
          <span style={{
            fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
            background: t.surfaceOverlay, color: t.textDim,
          }}>
            {data.source_type}
          </span>
        )}
      </div>

      {data.description && (
        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.4" }}>
          {data.description.length > 200 ? data.description.slice(0, 200) + "..." : data.description
          }
        </div>
      )}

      {data.chunk_count != null && data.chunk_count > 0 && (
        <div style={{ display: "flex", gap: 8 }}>
          <Stat label="chunks" value={data.chunk_count} />
        </div>
      )}

      <button
        onClick={(e) => {
          e.stopPropagation();
          router.push(adminPath as any);
        }}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: "none", border: "none", cursor: "pointer",
          fontSize: 11, color: t.accent, fontWeight: 500,
          padding: 0, marginTop: 2,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
        onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
      >
        View details
        <ExternalLink size={10} />
      </button>
    </>
  );
}

// ---------------------------------------------------------------------------
// Tool preview content
// ---------------------------------------------------------------------------

export interface ToolPreviewData {
  name: string;
  description?: string | null;
  source_integration?: string | null;
  /** The capability that contributed this tool, if any */
  fromCapability?: string;
}

export function ToolPreview({ data }: { data: ToolPreviewData }) {
  const t = useThemeTokens();
  const router = useRouter();
  const adminPath = `/admin/tools/${data.name}`;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>{data.name}</span>
      </div>

      {data.description && (
        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.4" }}>
          {data.description.length > 200 ? data.description.slice(0, 200) + "..." : data.description}
        </div>
      )}

      {(data.source_integration || data.fromCapability) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {data.source_integration && (
            <span style={{
              fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
              background: t.surfaceOverlay, color: t.textDim,
            }}>
              {data.source_integration}
            </span>
          )}
          {data.fromCapability && (
            <span style={{
              fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
              background: t.purpleSubtle, color: t.purple,
            }}>
              via {data.fromCapability}
            </span>
          )}
        </div>
      )}

      <button
        onClick={(e) => {
          e.stopPropagation();
          router.push(adminPath as any);
        }}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: "none", border: "none", cursor: "pointer",
          fontSize: 11, color: t.accent, fontWeight: 500,
          padding: 0, marginTop: 2,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
        onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
      >
        View details
        <ExternalLink size={10} />
      </button>
    </>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Stat({ label, value }: { label: string; value: number }) {
  const t = useThemeTokens();
  return (
    <span style={{
      fontSize: 10, color: t.textMuted,
      background: t.surfaceOverlay, borderRadius: 4,
      padding: "1px 6px",
    }}>
      <span style={{ fontWeight: 700, color: t.text }}>{value}</span> {label}
    </span>
  );
}
