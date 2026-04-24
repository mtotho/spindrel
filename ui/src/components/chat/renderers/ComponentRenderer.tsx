/**
 * ComponentRenderer — declarative component vocabulary for tool output rendering.
 *
 * Content type: `application/vnd.spindrel.components+json`
 *
 * Body schema:
 *   { v: 1, components: ComponentNode[] }
 *
 * Integrations compose rich output from ~15 typed primitives (heading, properties,
 * table, links, code, image, status, divider, section, text, toggle, button,
 * select, input, form) without needing custom React renderers.
 * Inspired by Slack Block Kit / Discord Components v2.
 *
 * Interactive primitives (toggle, button, select, input, form) carry a WidgetAction
 * that fires via the WidgetActionContext provided by the parent RichToolResult.
 *
 * Unknown component types render as a muted JSON dump (forward-compatible).
 * Unknown schema versions fall back to plain_body via the parent.
 */
import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import {
  ChevronRight,
  ChevronDown,
  ExternalLink,
  GitBranch,
  Globe,
  Mail,
  FileText,
  Link as LinkIcon,
  Loader2,
} from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";
import type { WidgetAction } from "../../../types/api";
import { MarkdownContent } from "../MarkdownContent";
import type { HostSurface, WidgetLayout } from "./InteractiveHtmlRenderer";
import type { PresentationFamily } from "@/src/lib/widgetHostPolicy";
import { getAuthToken, useAuthStore } from "../../../stores/auth";

// ── Widget action context ──

import type { WidgetActionResult } from "../../../api/hooks/useWidgetAction";

export interface WidgetActionDispatcher {
  dispatchAction: (action: WidgetAction, value: unknown) => Promise<WidgetActionResult>;
}

export const WidgetActionContext = createContext<WidgetActionDispatcher | null>(null);

// ── Schema types ──

interface ComponentBody {
  v: number;
  components: ComponentNode[];
}

type ComponentPriority = "primary" | "secondary" | "metadata";
type ComponentDensity = "compact" | "standard" | "expanded";

interface ComponentBase {
  priority?: ComponentPriority;
}

interface ComponentRenderContext {
  density: ComponentDensity;
  layout?: WidgetLayout;
  hostSurface?: HostSurface;
  presentationFamily?: PresentationFamily;
  gridDimensions?: { width: number; height: number };
}

type ComponentNode =
  | TextNode
  | HeadingNode
  | PropertiesNode
  | TableNode
  | LinksNode
  | CodeNode
  | ImageNode
  | StatusNode
  | DividerNode
  | SectionNode
  | ToggleNode
  | ButtonNode
  | TilesNode
  | TimelineNode
  | SelectNode
  | InputNode
  | FormNode
  | SliderNode
  | { type: string; [key: string]: unknown }; // forward-compat catch-all

interface TextNode extends ComponentBase {
  type: "text";
  content: string;
  style?: "default" | "muted" | "bold" | "code";
  markdown?: boolean;
}

interface HeadingNode extends ComponentBase {
  type: "heading";
  text: string;
  level?: 1 | 2 | 3;
}

interface PropertiesNode extends ComponentBase {
  type: "properties";
  items: { label: string; value: string; color?: SemanticSlot }[];
  layout?: "vertical" | "inline";
  variant?: "default" | "metadata";
}

interface TableNode extends ComponentBase {
  type: "table";
  columns: string[];
  rows: string[][];
  compact?: boolean;
}

interface LinksNode extends ComponentBase {
  type: "links";
  items: {
    url: string;
    title: string;
    subtitle?: string;
    icon?: "github" | "web" | "email" | "file" | "link";
  }[];
}

interface CodeNode extends ComponentBase {
  type: "code";
  content: string;
  language?: string;
}

interface ImageOverlayRect {
  x: number | string;
  y: number | string;
  w: number | string;
  h: number | string;
  label?: string;
  color?: SemanticSlot;
}

interface ImageNode extends ComponentBase {
  type: "image";
  url: string;
  alt?: string;
  height?: number;
  /** CSS `aspect-ratio` string, e.g. `"16 / 9"`. When set, the wrapper reserves
   *  the aspect-ratio box and avoids layout shift during blob fetches. */
  aspect_ratio?: string;
  /** `"none"` (default) renders the URL as a plain `<img src>`. `"bearer"`
   *  fetches the URL with the viewer's bearer token and renders the blob. */
  auth?: "none" | "bearer";
  /** When true, clicking the image opens a full-viewport lightbox. */
  lightbox?: boolean;
  /** Detection/annotation rectangles drawn over the image. Coords are
   *  normalized (0..1) so overlays survive resolution changes. */
  overlays?: ImageOverlayRect[];
}

interface StatusNode extends ComponentBase {
  type: "status";
  text: string;
  color?: SemanticSlot;
}

interface DividerNode extends ComponentBase {
  type: "divider";
  label?: string;
}

interface SectionNode extends ComponentBase {
  type: "section";
  children: ComponentNode[];
  label?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
}

interface ToggleNode extends ComponentBase {
  type: "toggle";
  label: string;
  value: boolean;
  action: WidgetAction;
  color?: SemanticSlot;
  description?: string;
  on_label?: string;
  off_label?: string;
}

interface ButtonNode extends ComponentBase {
  type: "button";
  label: string;
  action: WidgetAction;
  variant?: "default" | "primary" | "danger";
  disabled?: boolean;
  /** Render almost invisible (low opacity) until the enclosing `group` element
   *  is hovered. Used for progressive-disclosure affordances inside pinned
   *  widgets, e.g. a "Show forecast" toggle that doesn't compete with content. */
  subtle?: boolean;
}

interface TileItem {
  label?: string;
  value?: string;
  caption?: string;
  /** Presence of `image_url` flips the tile into image-first mode — image
   *  fills the tile, `label` overlays on a bottom gradient, `value` /
   *  `caption` are suppressed. Same vocabulary as the `image` primitive. */
  image_url?: string;
  image_aspect_ratio?: string;
  image_auth?: "none" | "bearer";
  /** Optional corner chip (SemanticSlot). */
  status?: SemanticSlot;
  /** Optional on-click dispatch. Entire tile becomes a button. */
  action?: WidgetAction;
}

interface TilesNode extends ComponentBase {
  type: "tiles";
  /** Array of tile items. Typically produced via the template engine's
   *  `each:` expansion over a result array. One primitive, two render
   *  modes: text-first (default) and image-first (when `image_url` is set
   *  on an item). Mixed modes in the same `items[]` are supported. */
  items: TileItem[];
  /** Minimum tile width in px — drives `grid-template-columns: repeat(auto-fill, minmax(Xpx, 1fr))`. */
  min_width?: number;
  /** Gap between tiles in px (default 6). */
  gap?: number;
}

interface TimelineLane {
  id: string;
  label?: string;
}

interface TimelineRange {
  start: string;
  end: string;
}

interface TimelineEvent {
  /** Required — stable selection across re-renders depends on event ids. */
  id: string;
  /** ISO 8601 timestamp. */
  start: string;
  /** ISO 8601 timestamp. Defaults to `start + 2s` when omitted. */
  end?: string;
  /** Required when `lanes` is non-empty; must be absent otherwise. */
  lane_id?: string;
  label?: string;
  color?: SemanticSlot;
  subtitle?: string;
}

interface TimelineNode extends ComponentBase {
  type: "timeline";
  events: TimelineEvent[];
  /** Explicit window. Omit for auto-fit (span spanned by events). */
  range?: TimelineRange;
  /** Omit for a flat (single-lane) timeline. */
  lanes?: TimelineLane[];
  on_event_click?: WidgetAction;
  /** Optional author-controlled selection. Typically bound to
   *  `widget_config.selected_event` so round-trip dispatch + state works. */
  selected_event_id?: string;
}

interface SelectNode extends ComponentBase {
  type: "select";
  label?: string;
  value: string;
  options: { value: string; label: string }[];
  action: WidgetAction;
}

interface InputNode extends ComponentBase {
  type: "input";
  label?: string;
  value: string;
  placeholder?: string;
  action: WidgetAction;
}

interface FormNode extends ComponentBase {
  type: "form";
  children: ComponentNode[];
  submit_action: WidgetAction;
  submit_label?: string;
}

interface SliderNode extends ComponentBase {
  type: "slider";
  label?: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  action: WidgetAction;
  color?: SemanticSlot;
}

type SemanticSlot =
  | "default"
  | "muted"
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info";

// ── Color mapping ──

function slotColor(slot: SemanticSlot | undefined, t: ThemeTokens): string {
  switch (slot) {
    case "muted":
      return t.textMuted;
    case "accent":
      return t.accent;
    case "success":
      return t.success;
    case "warning":
      return t.warningMuted;
    case "danger":
      return t.danger;
    case "info":
      return t.purple;
    default:
      return t.contentText;
  }
}

function slotBg(slot: SemanticSlot | undefined, t: ThemeTokens): string {
  switch (slot) {
    case "accent":
      return t.accentSubtle;
    case "success":
      return t.successSubtle;
    case "warning":
      return t.warningSubtle;
    case "danger":
      return t.dangerSubtle;
    case "info":
      return t.purpleSubtle;
    default:
      return t.overlayLight;
  }
}

// ── Icon mapping ──

const LINK_ICONS = {
  github: GitBranch,
  web: Globe,
  email: Mail,
  file: FileText,
  link: LinkIcon,
} as const;

// ── Max nesting depth ──

const MAX_DEPTH = 2;

// ── Top-level renderer ──

interface Props {
  body: string;
  t: ThemeTokens;
  layout?: WidgetLayout;
  hostSurface?: HostSurface;
  presentationFamily?: PresentationFamily;
  gridDimensions?: { width: number; height: number };
}

function deriveDensity(
  layout: WidgetLayout | undefined,
  presentationFamily: PresentationFamily | undefined,
  gridDimensions: { width: number; height: number } | undefined,
): ComponentDensity {
  const width = gridDimensions?.width ?? 0;
  const height = gridDimensions?.height ?? 0;
  if (presentationFamily === "chip") return "compact";
  if (layout === "rail" || layout === "header") return "compact";
  if ((width > 0 && width < 280) || (height > 0 && height < 150)) return "compact";
  if (width >= 520 && height >= 360) return "expanded";
  return "standard";
}

export function ComponentRenderer({ body, t, layout, hostSurface, presentationFamily, gridDimensions }: Props) {
  let parsed: ComponentBody;
  try {
    // body may already be a parsed object (e.g. from JSONB metadata)
    parsed = typeof body === "object" && body !== null ? (body as unknown as ComponentBody) : JSON.parse(body);
  } catch {
    return (
      <pre
        style={{
          fontSize: 12,
          color: t.textMuted,
          whiteSpace: "pre-wrap",
          fontFamily: "'Menlo', monospace",
        }}
      >
        {typeof body === "string" ? body : JSON.stringify(body, null, 2)}
      </pre>
    );
  }

  // Unknown schema version — fall back to raw text
  if (parsed.v !== 1 || !Array.isArray(parsed.components)) {
    return (
      <pre
        style={{
          fontSize: 12,
          color: t.textMuted,
          whiteSpace: "pre-wrap",
          fontFamily: "'Menlo', monospace",
        }}
      >
        {body}
      </pre>
    );
  }

  const ctx: ComponentRenderContext = {
    density: deriveDensity(layout, presentationFamily, gridDimensions),
    layout,
    hostSurface,
    presentationFamily,
    gridDimensions,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ctx.density === "compact" ? 5 : 7 }}>
      {parsed.components.map((node, i) => (
        <RenderNode key={i} node={node} t={t} depth={0} ctx={ctx} />
      ))}
    </div>
  );
}

// ── Recursive dispatch ──

function RenderNode({
  node,
  t,
  depth,
  ctx,
}: {
  node: ComponentNode;
  t: ThemeTokens;
  depth: number;
  ctx: ComponentRenderContext;
}) {
  if (ctx.density === "compact" && "priority" in node && node.priority === "metadata") {
    return null;
  }

  switch (node.type) {
    case "text":
      return <TextBlock node={node as TextNode} t={t} />;
    case "heading":
      return <HeadingBlock node={node as HeadingNode} t={t} />;
    case "properties":
      return <PropertiesBlock node={node as PropertiesNode} t={t} ctx={ctx} />;
    case "table":
      return <TableBlock node={node as TableNode} t={t} ctx={ctx} />;
    case "links":
      return <LinksBlock node={node as LinksNode} t={t} />;
    case "code":
      return <CodeBlock node={node as CodeNode} t={t} />;
    case "image":
      return <ImageBlock node={node as ImageNode} t={t} />;
    case "status":
      return <StatusBadge node={node as StatusNode} t={t} ctx={ctx} />;
    case "divider":
      return <DividerBlock node={node as DividerNode} t={t} />;
    case "section":
      return <SectionBlock node={node as SectionNode} t={t} depth={depth} ctx={ctx} />;
    case "toggle":
      return <ToggleBlock node={node as ToggleNode} t={t} ctx={ctx} />;
    case "button":
      return <ButtonBlock node={node as ButtonNode} t={t} />;
    case "tiles":
      return <TilesBlock node={node as TilesNode} t={t} ctx={ctx} />;
    case "timeline":
      return <TimelineBlock node={node as TimelineNode} t={t} />;
    case "select":
      return <SelectBlock node={node as SelectNode} t={t} />;
    case "input":
      return <InputBlock node={node as InputNode} t={t} />;
    case "form":
      return <FormBlock node={node as FormNode} t={t} depth={depth} ctx={ctx} />;
    case "slider":
      return <SliderBlock node={node as SliderNode} t={t} />;
    default:
      return <UnknownBlock node={node as Record<string, unknown> & { type: string }} t={t} />;
  }
}

// ── Primitives ──

function TextBlock({ node, t }: { node: TextNode; t: ThemeTokens }) {
  if (node.markdown) {
    return (
      <div style={{ padding: "2px 0" }}>
        <MarkdownContent text={node.content} t={t} />
      </div>
    );
  }

  const styleMap: Record<string, React.CSSProperties> = {
    default: { color: t.contentText },
    muted: { color: t.textMuted },
    bold: { color: t.contentText, fontWeight: 600 },
    code: {
      color: t.codeText,
      fontFamily: "'Menlo', monospace",
      background: t.codeBg,
      padding: "1px 4px",
      borderRadius: 3,
    },
  };

  return (
    <span
      style={{
        fontSize: 12,
        lineHeight: 1.5,
        ...styleMap[node.style ?? "default"],
      }}
    >
      {node.content}
    </span>
  );
}

function HeadingBlock({ node, t }: { node: HeadingNode; t: ThemeTokens }) {
  const sizes = { 1: 15, 2: 13, 3: 12 } as const;
  const level = node.level ?? 2;
  return (
    <div
      style={{
        fontSize: sizes[level] ?? 13,
        fontWeight: 600,
        color: level === 3 ? t.textMuted : t.text,
        lineHeight: 1.4,
      }}
    >
      {node.text}
    </div>
  );
}

function PropertiesBlock({
  node,
  t,
  ctx,
}: {
  node: PropertiesNode;
  t: ThemeTokens;
  ctx: ComponentRenderContext;
}) {
  const isInline = node.layout === "inline";
  const isMetadata = node.variant === "metadata" || node.priority === "metadata";
  const items = Array.isArray(node.items) ? node.items : [];
  if (items.length === 0) return null;
  if (isMetadata && ctx.density === "compact") return null;

  const fontSize = isMetadata ? 10 : ctx.density === "compact" ? 11 : 12;
  const labelColor = isMetadata ? t.textDim : t.textMuted;
  const valueOpacity = isMetadata ? 0.72 : 1;

  if (isInline) {
    return (
      <div
        style={{
          display: "flex", flexDirection: "row",
          flexWrap: "wrap",
          gap: isMetadata ? "2px 10px" : "4px 12px",
          fontSize,
          lineHeight: 1.35,
          opacity: isMetadata ? 0.8 : 1,
        }}
      >
        {items.map((item, i) => (
          <span key={i}>
            <span style={{ color: labelColor }}>{item.label}: </span>
            <span style={{ color: slotColor(item.color, t), opacity: valueOpacity }}>
              {item.value}
            </span>
          </span>
        ))}
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: isMetadata ? "2px 10px" : "3px 12px",
        fontSize,
        lineHeight: 1.35,
        opacity: isMetadata ? 0.8 : 1,
      }}
    >
      {items.map((item, i) => (
        <div key={i} style={{ display: "contents" }}>
          <span style={{ color: labelColor, whiteSpace: "nowrap" }}>
            {item.label}
          </span>
          <span style={{ color: slotColor(item.color, t), opacity: valueOpacity }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}

function TableBlock({ node, t, ctx }: { node: TableNode; t: ThemeTokens; ctx: ComponentRenderContext }) {
  const columns = Array.isArray(node.columns) ? node.columns : [];
  const rows = Array.isArray(node.rows) ? node.rows : [];
  if (columns.length === 0 && rows.length === 0) return null;
  const compact = node.compact || ctx.density === "compact";
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        maxHeight: ctx.density === "expanded" ? 460 : ctx.density === "compact" ? 220 : 360,
        overflow: "auto",
      }}
    >
      <table
        style={{
          // Intrinsic column sizing (narrow cells stay narrow, wide cells
          // get room). ``minWidth: 100%`` keeps the table filling the
          // container when content is short; horizontal scroll kicks in on
          // the wrapper when the summed content width overflows.
          width: "max-content",
          minWidth: "100%",
          borderCollapse: "collapse",
          fontSize: compact ? 11 : 12,
          fontFamily: "'Menlo', monospace",
        }}
      >
        <thead>
          <tr style={{ background: t.codeBg }}>
            {columns.map((col, i) => (
              <th
                key={i}
                style={{
                  padding: compact ? "4px 8px" : "6px 10px",
                  textAlign: "left",
                  color: t.textMuted,
                  fontWeight: 600,
                  fontSize: 11,
                  borderBottom: `1px solid ${t.surfaceBorder}`,
                  whiteSpace: "nowrap",
                }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              style={{
                borderBottom:
                  ri < rows.length - 1
                    ? `1px solid ${t.surfaceBorder}`
                    : undefined,
              }}
            >
              {(Array.isArray(row) ? row : []).map((cell, ci) => (
                <td
                  key={ci}
                  style={{
                    padding: compact ? "3px 8px" : "5px 10px",
                    color: t.contentText,
                    // Wrap at word boundaries only — no mid-word breaks that
                    // shatter ISO dates / IDs into vertical column mess.
                    whiteSpace: "normal",
                    wordBreak: "normal",
                    // Single unbreakable string longer than this will force
                    // horizontal scroll rather than eating the column.
                    overflowWrap: "break-word",
                    // Cap runaway prose cells so one long ``notes`` field
                    // can't stretch the whole table.
                    maxWidth: 360,
                    verticalAlign: "top",
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LinksBlock({ node, t }: { node: LinksNode; t: ThemeTokens }) {
  const items = Array.isArray(node.items) ? node.items : [];
  if (items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {items.map((item, i) => {
        const Icon = LINK_ICONS[item.icon ?? "link"] ?? LinkIcon;
        return (
          <a
            key={i}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "flex-start",
              gap: 8,
              padding: "6px 8px",
              borderRadius: 6,
              textDecoration: "none",
              transition: "background-color 0.1s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = t.overlayLight;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "transparent";
            }}
          >
            <Icon
              size={14}
              color={t.textDim}
              style={{ marginTop: 2, flexShrink: 0 }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 12,
                  color: t.linkColor,
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {item.title}
                </span>
                <ExternalLink size={10} color={t.textDim} style={{ flexShrink: 0 }} />
              </div>
              {item.subtitle && (
                <div
                  style={{
                    fontSize: 11,
                    color: t.textMuted,
                    lineHeight: 1.4,
                    marginTop: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                  }}
                >
                  {item.subtitle}
                </div>
              )}
            </div>
          </a>
        );
      })}
    </div>
  );
}

function CodeBlock({ node, t }: { node: CodeNode; t: ThemeTokens }) {
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        overflow: "hidden",
        background: t.codeBg,
      }}
    >
      {node.language && (
        <div
          style={{
            padding: "4px 10px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            fontSize: 10,
            color: t.textDim,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {node.language}
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: "8px 10px",
          fontSize: 12,
          fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
          color: t.contentText,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.5,
          maxHeight: 300,
          overflowY: "auto",
        }}
      >
        {node.content}
      </pre>
    </div>
  );
}

function ImageBlock({ node, t }: { node: ImageNode; t: ThemeTokens }) {
  const authMode = node.auth ?? "none";
  const resolvedUrl = useAuthedImageUrl(node.url, authMode);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  const canLightbox = node.lightbox === true;
  const hasAspectRatio = typeof node.aspect_ratio === "string" && node.aspect_ratio.length > 0;

  const overlays = Array.isArray(node.overlays)
    ? node.overlays.filter((o) => o && typeof o === "object")
    : [];

  return (
    <>
      <div
        style={{
          borderRadius: 6,
          overflow: "hidden",
          border: `1px solid ${t.surfaceBorder}`,
          background: t.codeBg,
          position: "relative",
          aspectRatio: hasAspectRatio ? node.aspect_ratio : undefined,
          cursor: canLightbox ? "zoom-in" : undefined,
        }}
        onClick={canLightbox ? () => setLightboxOpen(true) : undefined}
        role={canLightbox ? "button" : undefined}
        tabIndex={canLightbox ? 0 : undefined}
        onKeyDown={
          canLightbox
            ? (ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  setLightboxOpen(true);
                }
              }
            : undefined
        }
      >
        {resolvedUrl ? (
          <img
            src={resolvedUrl}
            alt={node.alt ?? ""}
            style={{
              display: "block",
              width: hasAspectRatio ? "100%" : undefined,
              height: hasAspectRatio ? "100%" : undefined,
              maxWidth: "100%",
              maxHeight: hasAspectRatio ? undefined : node.height ?? 400,
              objectFit: hasAspectRatio ? "cover" : "contain",
            }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              height: hasAspectRatio ? "100%" : node.height ?? 200,
              background: t.codeBg,
            }}
          />
        )}

        {overlays.length > 0 && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              pointerEvents: "none",
            }}
          >
            {overlays.map((o, i) => (
              <OverlayRect key={i} overlay={o} t={t} />
            ))}
          </div>
        )}
      </div>

      {lightboxOpen && resolvedUrl && (
        <Lightbox url={resolvedUrl} alt={node.alt ?? ""} onClose={() => setLightboxOpen(false)} t={t} />
      )}
    </>
  );
}

function clampUnit(v: number | string | undefined): number {
  const n = typeof v === "number" ? v : typeof v === "string" ? parseFloat(v) : NaN;
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

function OverlayRect({ overlay, t }: { overlay: ImageOverlayRect; t: ThemeTokens }) {
  const x = clampUnit(overlay.x);
  const y = clampUnit(overlay.y);
  const w = clampUnit(overlay.w);
  const h = clampUnit(overlay.h);
  if (w === 0 || h === 0) return null;
  const strokeColor = slotColor(overlay.color, t);

  return (
    <div
      style={{
        position: "absolute",
        left: `${x * 100}%`,
        top: `${y * 100}%`,
        width: `${w * 100}%`,
        height: `${h * 100}%`,
        border: `2px solid ${strokeColor}`,
        borderRadius: 3,
        boxSizing: "border-box",
        background: `${strokeColor}14`,
      }}
    >
      {overlay.label && (
        <span
          style={{
            position: "absolute",
            top: -2,
            left: 0,
            transform: "translateY(-100%)",
            background: strokeColor,
            color: t.surface,
            fontSize: 10,
            fontWeight: 600,
            padding: "1px 5px",
            borderRadius: 3,
            whiteSpace: "nowrap",
          }}
        >
          {overlay.label}
        </span>
      )}
    </div>
  );
}

function Lightbox({
  url,
  alt,
  onClose,
  t,
}: {
  url: string;
  alt: string;
  onClose: () => void;
  t: ThemeTokens;
}) {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.9)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        cursor: "zoom-out",
      }}
    >
      <img
        src={url}
        alt={alt}
        style={{
          maxWidth: "100%",
          maxHeight: "92vh",
          borderRadius: 6,
          objectFit: "contain",
          boxShadow: `0 6px 20px rgba(0,0,0,0.4)`,
          background: t.surface,
        }}
      />
    </div>
  );
}

/** Resolve an image URL to a renderable src.
 *
 *  - `auth: "none"`: passes through unchanged — the browser renders directly.
 *  - `auth: "bearer"`: fetches with the viewer's bearer token, converts the
 *    response to an object URL. Revokes the object URL on unmount / url change
 *    so long-lived dashboards don't leak blob memory.
 */
function useAuthedImageUrl(url: string, authMode: "none" | "bearer"): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (authMode !== "bearer") {
      setBlobUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;

    async function load() {
      const token = getAuthToken();
      const { serverUrl } = useAuthStore.getState();
      const base = serverUrl ?? "";
      const absolute = /^https?:\/\//i.test(url) ? url : `${base}${url}`;
      try {
        const res = await fetch(absolute, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch {
        if (!cancelled) setBlobUrl(null);
      }
    }

    load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, authMode]);

  return authMode === "bearer" ? blobUrl : url;
}

function StatusBadge({ node, t, ctx }: { node: StatusNode; t: ThemeTokens; ctx: ComponentRenderContext }) {
  const color = slotColor(node.color, t);
  const bg = slotBg(node.color, t);
  return (
    <span
      style={{
        display: "inline-flex", flexDirection: "row",
        alignItems: "center",
        gap: 5,
        padding: ctx.density === "compact" ? "1px 6px" : "2px 7px",
        borderRadius: 10,
        fontSize: ctx.density === "compact" ? 10 : 11,
        fontWeight: 600,
        color,
        background: bg,
        border: `1px solid ${color}22`,
        alignSelf: "flex-start",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
        }}
      />
      {node.text}
    </span>
  );
}

function DividerBlock({ node, t }: { node: DividerNode; t: ThemeTokens }) {
  if (node.label) {
    return (
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
          margin: "4px 0",
        }}
      >
        <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
        <span style={{ fontSize: 10, color: t.textDim, whiteSpace: "nowrap" }}>
          {node.label}
        </span>
        <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
      </div>
    );
  }
  return (
    <div
      style={{ height: 1, background: t.surfaceBorder, margin: "4px 0" }}
    />
  );
}

function SectionBlock({
  node,
  t,
  depth,
  ctx,
}: {
  node: SectionNode;
  t: ThemeTokens;
  depth: number;
  ctx: ComponentRenderContext;
}) {
  const defaultOpen = ctx.density === "compact" ? false : node.defaultOpen !== false;
  const [open, setOpen] = useState(defaultOpen);

  // Depth guard — render children as flat text beyond MAX_DEPTH
  if (depth >= MAX_DEPTH) {
    return (
      <div style={{ fontSize: 11, color: t.textMuted, fontStyle: "italic" }}>
        {node.label ?? "Section"} ({node.children?.length ?? 0} items)
      </div>
    );
  }

  if (!node.collapsible) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          padding: depth > 0 ? "0 0 0 12px" : undefined,
          borderLeft: depth > 0 ? `2px solid ${t.surfaceBorder}` : undefined,
        }}
      >
        {node.label && (
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: t.textMuted,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            {node.label}
          </div>
        )}
        {node.children?.map((child, i) => (
          <RenderNode key={i} node={child} t={t} depth={depth + 1} ctx={ctx} />
        ))}
      </div>
    );
  }

  return (
    <div>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 4,
          cursor: "pointer",
          padding: "2px 0",
          userSelect: "none",
        }}
      >
        {open ? (
          <ChevronDown size={12} color={t.textDim} />
        ) : (
          <ChevronRight size={12} color={t.textDim} />
        )}
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: t.textMuted,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {node.label ?? "Details"}
        </span>
      </div>
      {open && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            padding: "4px 0 0 12px",
            borderLeft: `2px solid ${t.surfaceBorder}`,
          }}
        >
          {node.children?.map((child, i) => (
            <RenderNode key={i} node={child} t={t} depth={depth + 1} ctx={ctx} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Interactive primitives ──

function useAction() {
  const ctx = useContext(WidgetActionContext);
  return ctx?.dispatchAction ?? null;
}

function ToggleBlock({ node, t, ctx }: { node: ToggleNode; t: ThemeTokens; ctx: ComponentRenderContext }) {
  const dispatch = useAction();
  const [checked, setChecked] = useState(node.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync local state when envelope replacement changes node.value
  useEffect(() => {
    setChecked(node.value);
  }, [node.value]);

  const handleToggle = useCallback(async () => {
    if (!dispatch) {
      setError("Not connected");
      return;
    }
    setError(null);
    const next = !checked;
    if (node.action.optimistic) setChecked(next);
    setBusy(true);
    try {
      await dispatch(node.action, next);
      if (!node.action.optimistic) setChecked(next);
    } catch (e) {
      if (node.action.optimistic) setChecked(!next);
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }, [dispatch, checked, node.action]);

  const accentColor = slotColor(node.color ?? "success", t);
  const trackColor = checked ? accentColor : t.surfaceBorder;
  const stateText = node.description || (checked ? node.on_label ?? "On" : node.off_label ?? "Off");
  const isCompact = ctx.density === "compact";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 10,
          padding: isCompact ? "6px 7px" : "8px 9px",
          border: `1px solid ${t.surfaceBorder}80`,
          borderRadius: 6,
          background: t.overlayLight,
          minHeight: isCompact ? 38 : 44,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: isCompact ? 12 : 13,
              color: t.contentText,
              fontWeight: 550,
              lineHeight: 1.25,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              userSelect: "none",
            }}
          >
            {node.label}
          </div>
          {stateText && (
            <div
              style={{
                fontSize: isCompact ? 10 : 11,
                color: checked ? accentColor : t.textMuted,
                lineHeight: 1.25,
                marginTop: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {stateText}
            </div>
          )}
        </div>
        {busy && <Loader2 size={14} color={t.textMuted} className="animate-spin" />}
        {/* 44px touch target wrapping the visual switch */}
        <button
          type="button"
          onClick={handleToggle}
          disabled={busy}
          aria-label={`${node.label}: ${stateText || (checked ? "on" : "off")}`}
          aria-checked={checked}
          role="switch"
          style={{
            position: "relative",
            width: isCompact ? 38 : 42,
            height: isCompact ? 22 : 24,
            borderRadius: 12,
            border: `1.5px solid ${checked ? "transparent" : t.surfaceBorder}`,
            background: trackColor,
            cursor: busy ? "wait" : "pointer",
            transition: "background-color 0.2s ease-out, border-color 0.2s ease-out",
            flexShrink: 0,
            opacity: busy ? 0.5 : 1,
            padding: 0,
            outline: "none",
          }}
          onFocus={(e) => { e.currentTarget.style.boxShadow = `0 0 0 2px ${t.accentSubtle}`; }}
          onBlur={(e) => { e.currentTarget.style.boxShadow = "none"; }}
        >
          <span
            style={{
              position: "absolute",
              top: 2,
              left: checked ? (isCompact ? 18 : 20) : 2,
              width: isCompact ? 16 : 18,
              height: isCompact ? 16 : 18,
              borderRadius: "50%",
              background: "#fff",
              transition: "left 0.2s ease-out, box-shadow 0.2s ease-out",
              boxShadow: checked
                ? "0 1px 4px rgba(0,0,0,0.25)"
                : "0 1px 3px rgba(0,0,0,0.2)",
            }}
          />
        </button>
      </div>
      {error && (
        <span style={{ fontSize: 11, color: t.danger, paddingLeft: 2 }}>{error}</span>
      )}
    </div>
  );
}

function ButtonBlock({ node, t }: { node: ButtonNode; t: ThemeTokens }) {
  const dispatch = useAction();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const variantStyles: Record<string, { bg: string; color: string; border: string; hoverBg: string }> = {
    primary: { bg: t.accent, color: "#fff", border: t.accent, hoverBg: t.accentMuted },
    danger: { bg: t.danger, color: "#fff", border: t.danger, hoverBg: t.dangerMuted },
    default: { bg: t.overlayLight, color: t.contentText, border: t.surfaceBorder, hoverBg: t.surfaceBorder },
  };
  const v = variantStyles[node.variant ?? "default"] ?? variantStyles.default;
  const isDisabled = busy || node.disabled || !dispatch;

  // Subtle variant: small, almost invisible until the enclosing `group`
  // (e.g. PinnedToolWidget root) is hovered. Lets templates add optional
  // toggles without visual clutter when idle.
  const wrapperClass = node.subtle
    ? "opacity-25 group-hover:opacity-100 transition-opacity duration-150"
    : "";
  const padding = node.subtle ? "3px 10px" : "6px 16px";
  const minHeight = node.subtle ? 22 : 32;
  const fontSize = node.subtle ? 11 : 12;

  return (
    <div
      className={wrapperClass}
      style={{ display: "flex", flexDirection: "column", gap: 2, alignSelf: "flex-start" }}
    >
      <button
        type="button"
        onClick={async () => {
          if (!dispatch) { setError("Not connected"); return; }
          setError(null);
          setBusy(true);
          try {
            await dispatch(node.action, true);
          } catch (e) {
            setError(e instanceof Error ? e.message : "Action failed");
          } finally {
            setBusy(false);
          }
        }}
        disabled={isDisabled}
        style={{
          padding,
          borderRadius: 6,
          border: `1px solid ${v.border}`,
          background: v.bg,
          color: v.color,
          fontSize,
          fontWeight: 500,
          cursor: isDisabled ? "default" : "pointer",
          opacity: isDisabled ? 0.4 : 1,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          transition: "opacity 0.15s, background-color 0.15s",
          minHeight,
        }}
        onMouseEnter={(e) => { if (!isDisabled) e.currentTarget.style.backgroundColor = v.hoverBg; }}
        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = v.bg; }}
      >
        {busy && <Loader2 size={12} className="animate-spin" />}
        {node.label}
      </button>
      {error && <span style={{ fontSize: 11, color: t.danger }}>{error}</span>}
    </div>
  );
}

function TilesBlock({ node, t, ctx }: { node: TilesNode; t: ThemeTokens; ctx: ComponentRenderContext }) {
  const items = Array.isArray(node.items) ? node.items : [];
  if (items.length === 0) return null;

  const minWidth = ctx.density === "compact"
    ? Math.min(node.min_width ?? 84, 120)
    : node.min_width ?? 84;
  const gap = node.gap ?? (ctx.density === "compact" ? 5 : 6);
  const showCaption = ctx.density !== "compact";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))`,
        gap,
      }}
    >
      {items.map((item, i) =>
        item.image_url ? (
          <ImageTile key={i} item={item} t={t} />
        ) : (
          <TextTile key={i} item={item} t={t} ctx={ctx} showCaption={showCaption} />
        ),
      )}
    </div>
  );
}

function useTileAction(action: WidgetAction | undefined) {
  const dispatch = useAction();
  const [busy, setBusy] = useState(false);
  const onClick = action && dispatch
    ? async () => {
        if (busy) return;
        setBusy(true);
        try {
          await dispatch(action, true);
        } catch {
          // Per-tile error surface would crowd the grid; swallow.
        } finally {
          setBusy(false);
        }
      }
    : undefined;
  return { onClick, busy, interactive: Boolean(onClick) };
}

function StatusChip({ slot, t }: { slot: SemanticSlot; t: ThemeTokens }) {
  return (
    <span
      style={{
        position: "absolute",
        top: 4,
        right: 4,
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: slotColor(slot, t),
        boxShadow: `0 0 0 2px ${t.surface}`,
      }}
      aria-hidden
    />
  );
}

function TextTile({
  item,
  t,
  ctx,
  showCaption,
}: {
  item: TileItem;
  t: ThemeTokens;
  ctx: ComponentRenderContext;
  showCaption: boolean;
}) {
  const { onClick, busy, interactive } = useTileAction(item.action);

  return (
    <div
      onClick={onClick}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (ev) => {
              if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className="rounded-md border"
      style={{
        borderColor: `${t.surfaceBorder}80`,
        background: t.overlayLight,
        padding: ctx.density === "compact" ? "5px 7px" : "6px 8px",
        display: "flex",
        flexDirection: "column",
        gap: 1,
        minWidth: 0,
        position: "relative",
        cursor: interactive ? "pointer" : undefined,
        opacity: busy ? 0.6 : 1,
        transition: "opacity 0.15s",
      }}
    >
      {item.status && <StatusChip slot={item.status} t={t} />}
      {item.label && (
        <span
          style={{
            fontSize: 10,
            color: t.textMuted,
            textTransform: "uppercase",
            letterSpacing: "0.03em",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {item.label}
        </span>
      )}
      {item.value && (
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: t.contentText,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {item.value}
        </span>
      )}
      {showCaption && item.caption && (
        <span
          style={{
            fontSize: 10,
            color: t.textDim,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {item.caption}
        </span>
      )}
    </div>
  );
}

function ImageTile({ item, t }: { item: TileItem; t: ThemeTokens }) {
  const authMode: "none" | "bearer" = item.image_auth ?? "none";
  const resolvedUrl = useAuthedImageUrl(item.image_url ?? "", authMode);
  const { onClick, busy, interactive } = useTileAction(item.action);
  const hasAspect =
    typeof item.image_aspect_ratio === "string" && item.image_aspect_ratio.length > 0;

  return (
    <div
      onClick={onClick}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (ev) => {
              if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className="rounded-md border"
      style={{
        borderColor: `${t.surfaceBorder}80`,
        background: t.codeBg,
        position: "relative",
        overflow: "hidden",
        minWidth: 0,
        aspectRatio: hasAspect ? item.image_aspect_ratio : "16 / 9",
        cursor: interactive ? "pointer" : undefined,
        opacity: busy ? 0.6 : 1,
        transition: "opacity 0.15s",
      }}
    >
      {resolvedUrl ? (
        <img
          src={resolvedUrl}
          alt={item.label ?? ""}
          style={{
            display: "block",
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      ) : (
        <div style={{ width: "100%", height: "100%", background: t.codeBg }} />
      )}

      {item.status && <StatusChip slot={item.status} t={t} />}

      {item.label && (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            padding: "18px 8px 6px",
            background: "linear-gradient(to top, rgba(0,0,0,0.72), rgba(0,0,0,0))",
            pointerEvents: "none",
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "#fff",
              display: "block",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              textShadow: "0 1px 2px rgba(0,0,0,0.6)",
            }}
          >
            {item.label}
          </span>
          {item.caption && (
            <span
              style={{
                fontSize: 10,
                color: "rgba(255,255,255,0.82)",
                display: "block",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {item.caption}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Timeline ──

const TIMELINE_LANE_H = 22;
const TIMELINE_LANE_GAP = 4;
const TIMELINE_AXIS_H = 18;
const TIMELINE_PAD_X = 8;
const TIMELINE_DEFAULT_EVENT_MS = 2000;

function parseTimelineMs(iso: string | undefined): number | null {
  if (!iso) return null;
  const v = Date.parse(iso);
  return Number.isFinite(v) ? v : null;
}

function formatTimelineClock(ms: number): string {
  try {
    return new Date(ms).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function TimelineBlock({ node, t }: { node: TimelineNode; t: ThemeTokens }) {
  const events = Array.isArray(node.events) ? node.events : [];
  const lanes = Array.isArray(node.lanes) ? node.lanes : [];
  const hasLanes = lanes.length > 0;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(480);
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (w > 0) setWidth(w);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const dispatch = useAction();
  const [localSelected, setLocalSelected] = useState<string | null>(null);
  const selectedId = node.selected_event_id ?? localSelected;

  // Compute window: explicit range takes priority; otherwise auto-fit.
  let tMin: number | null = parseTimelineMs(node.range?.start);
  let tMax: number | null = parseTimelineMs(node.range?.end);
  if (tMin == null || tMax == null) {
    for (const ev of events) {
      const s = parseTimelineMs(ev.start);
      if (s == null) continue;
      const e = parseTimelineMs(ev.end) ?? s + TIMELINE_DEFAULT_EVENT_MS;
      if (tMin == null || s < tMin) tMin = s;
      if (tMax == null || e > tMax) tMax = e;
    }
  }

  if (tMin == null || tMax == null) {
    return (
      <div
        ref={containerRef}
        style={{ fontSize: 11, color: t.textDim, padding: "8px 0" }}
      >
        No events.
      </div>
    );
  }

  // Pad window so events at the very edge don't clip against the frame.
  let span = Math.max(tMax - tMin, 1000);
  if (!node.range) {
    const pad = span * 0.04;
    tMin -= pad;
    tMax += pad;
    span = tMax - tMin;
  }

  // Lane list — when no lanes declared, fall back to a single implicit flat lane.
  const renderLanes: TimelineLane[] = hasLanes
    ? lanes
    : [{ id: "__flat__", label: "" }];

  const laneIndex = new Map<string, number>();
  renderLanes.forEach((lane, i) => laneIndex.set(lane.id, i));

  const contentW = Math.max(120, width - TIMELINE_PAD_X * 2);
  const totalH = TIMELINE_AXIS_H + renderLanes.length * (TIMELINE_LANE_H + TIMELINE_LANE_GAP);
  const timeToX = (ms: number): number =>
    TIMELINE_PAD_X + ((ms - (tMin as number)) / span) * contentW;

  const tickCount = 4;
  const ticks: { x: number; label: string; anchor: "start" | "middle" | "end" }[] = [];
  for (let k = 0; k <= tickCount; k++) {
    const tms = (tMin as number) + (span * k) / tickCount;
    ticks.push({
      x: timeToX(tms),
      label: formatTimelineClock(tms),
      anchor: k === 0 ? "start" : k === tickCount ? "end" : "middle",
    });
  }

  async function onPillClick(ev: TimelineEvent) {
    if (node.selected_event_id == null) setLocalSelected(ev.id);
    if (node.on_event_click && dispatch) {
      try {
        await dispatch(node.on_event_click, ev.id);
      } catch {
        // Click-handler errors are swallowed — the pill reflects local selection regardless.
      }
    }
  }

  return (
    <div
      ref={containerRef}
      style={{
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.codeBg,
        padding: "4px 0",
      }}
    >
      <svg
        width="100%"
        height={totalH}
        viewBox={`0 0 ${width} ${totalH}`}
        preserveAspectRatio="none"
        style={{ display: "block" }}
        role="img"
        aria-label="timeline"
      >
        {renderLanes.map((lane, idx) => {
          const y = TIMELINE_AXIS_H + idx * (TIMELINE_LANE_H + TIMELINE_LANE_GAP);
          return (
            <g key={lane.id}>
              <rect
                x={TIMELINE_PAD_X}
                y={y}
                width={contentW}
                height={TIMELINE_LANE_H}
                rx={3}
                fill={t.overlayLight}
              />
              {lane.label && (
                <text
                  x={TIMELINE_PAD_X + 6}
                  y={y + TIMELINE_LANE_H / 2 + 3}
                  fill={t.textMuted}
                  fontSize={10}
                  pointerEvents="none"
                >
                  {lane.label}
                </text>
              )}
            </g>
          );
        })}

        {ticks.map((tick, i) => (
          <text
            key={i}
            x={tick.x}
            y={11}
            fill={t.textDim}
            fontSize={9}
            textAnchor={tick.anchor}
          >
            {tick.label}
          </text>
        ))}

        {events.map((ev) => {
          const s = parseTimelineMs(ev.start);
          if (s == null) return null;
          const e = parseTimelineMs(ev.end) ?? s + TIMELINE_DEFAULT_EVENT_MS;
          const laneKey = hasLanes ? ev.lane_id ?? "" : "__flat__";
          const idx = laneIndex.get(laneKey);
          if (idx == null) return null;
          const y = TIMELINE_AXIS_H + idx * (TIMELINE_LANE_H + TIMELINE_LANE_GAP) + 3;
          const h = TIMELINE_LANE_H - 6;
          const x1 = timeToX(s);
          const x2 = timeToX(e);
          const w = Math.max(4, x2 - x1);
          const isSelected = ev.id === selectedId;
          const fill = slotColor(ev.color, t);
          const title = [
            ev.label ?? "event",
            formatTimelineClock(s),
            ev.subtitle,
          ].filter(Boolean).join(" · ");

          return (
            <rect
              key={ev.id}
              x={x1}
              y={y}
              width={w}
              height={h}
              rx={3}
              fill={fill}
              fillOpacity={0.75}
              stroke={isSelected ? t.accent : undefined}
              strokeWidth={isSelected ? 2 : undefined}
              style={{ cursor: node.on_event_click ? "pointer" : "default" }}
              onClick={() => onPillClick(ev)}
            >
              <title>{title}</title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}

function SelectBlock({ node, t }: { node: SelectNode; t: ThemeTokens }) {
  const dispatch = useAction();
  const [value, setValue] = useState(node.value);
  const [busy, setBusy] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, padding: "4px 0" }}>
      {node.label && (
        <label style={{ fontSize: 12, color: t.textMuted, whiteSpace: "nowrap", fontWeight: 500 }}>{node.label}</label>
      )}
      <select
        value={value}
        disabled={busy || !dispatch}
        onChange={async (e) => {
          const next = e.target.value;
          setValue(next);
          if (!dispatch) return;
          setBusy(true);
          try {
            await dispatch(node.action, next);
          } catch {
            setValue(value);
          } finally {
            setBusy(false);
          }
        }}
        style={{
          padding: "5px 10px",
          borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.overlayLight,
          color: t.contentText,
          fontSize: 12,
          cursor: dispatch ? "pointer" : "default",
          opacity: busy ? 0.5 : 1,
          minHeight: 32,
          transition: "opacity 0.15s",
        }}
      >
        {(Array.isArray(node.options) ? node.options : []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {busy && <Loader2 size={14} color={t.textMuted} className="animate-spin" />}
    </div>
  );
}

function InputBlock({ node, t }: { node: InputNode; t: ThemeTokens }) {
  const dispatch = useAction();
  const [value, setValue] = useState(node.value);
  const [busy, setBusy] = useState(false);

  const submit = useCallback(async () => {
    if (!dispatch || !value) return;
    setBusy(true);
    try {
      await dispatch(node.action, value);
    } finally {
      setBusy(false);
    }
  }, [dispatch, value, node.action]);

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, padding: "4px 0" }}>
      {node.label && (
        <label style={{ fontSize: 12, color: t.textMuted, whiteSpace: "nowrap", fontWeight: 500 }}>{node.label}</label>
      )}
      <input
        type="text"
        value={value}
        placeholder={node.placeholder}
        disabled={busy || !dispatch}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        style={{
          padding: "5px 10px",
          borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.overlayLight,
          color: t.contentText,
          fontSize: 12,
          flex: 1,
          minWidth: 0,
          minHeight: 32,
          opacity: busy ? 0.5 : 1,
          transition: "border-color 0.15s, opacity 0.15s",
          outline: "none",
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = t.accent; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = t.surfaceBorder; }}
      />
      {busy && <Loader2 size={14} color={t.textMuted} className="animate-spin" />}
    </div>
  );
}

function FormBlock({
  node,
  t,
  depth,
  ctx,
}: {
  node: FormNode;
  t: ThemeTokens;
  depth: number;
  ctx: ComponentRenderContext;
}) {
  const dispatch = useAction();
  const [busy, setBusy] = useState(false);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 12px",
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        background: t.overlayLight,
      }}
    >
      {node.children?.map((child, i) => (
        <RenderNode key={i} node={child} t={t} depth={depth + 1} ctx={ctx} />
      ))}
      <button
        type="button"
        onClick={async () => {
          if (!dispatch) return;
          setBusy(true);
          try {
            await dispatch(node.submit_action, true);
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy || !dispatch}
        style={{
          padding: "6px 16px",
          borderRadius: 6,
          border: `1px solid ${t.accent}`,
          background: t.accent,
          color: "#fff",
          fontSize: 12,
          fontWeight: 500,
          cursor: busy ? "wait" : dispatch ? "pointer" : "default",
          opacity: busy ? 0.5 : 1,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          alignSelf: "flex-start",
          transition: "opacity 0.15s",
          marginTop: 4,
          minHeight: 32,
        }}
      >
        {busy && <Loader2 size={12} className="animate-spin" />}
        {node.submit_label ?? "Submit"}
      </button>
    </div>
  );
}

function SliderBlock({ node, t }: { node: SliderNode; t: ThemeTokens }) {
  const dispatch = useAction();
  const [value, setValue] = useState(node.value);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const min = node.min ?? 0;
  const max = node.max ?? 100;
  const step = node.step ?? 1;
  const pct = ((value - min) / (max - min)) * 100;
  const accentColor = slotColor(node.color ?? "accent", t);

  const debouncedDispatch = useCallback((v: number) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      if (!dispatch) return;
      setBusy(true);
      try {
        await dispatch(node.action, v);
      } catch {
        // error silently — slider stays at user's chosen position
      } finally {
        setBusy(false);
      }
    }, 300);
  }, [dispatch, node.action]);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "4px 0" }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        {node.label && (
          <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500 }}>{node.label}</span>
        )}
        <span style={{
          fontSize: 12,
          color: t.contentText,
          fontVariantNumeric: "tabular-nums",
          fontFamily: "'Menlo', monospace",
          minWidth: 36,
          textAlign: "right",
        }}>
          {value}{node.unit ?? ""}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => {
          const v = Number(e.target.value);
          setValue(v);
          debouncedDispatch(v);
        }}
        disabled={busy || !dispatch}
        style={{
          width: "100%",
          height: 4,
          cursor: dispatch ? "pointer" : "default",
          opacity: busy ? 0.5 : 1,
          accentColor,
          background: `linear-gradient(to right, ${accentColor} 0%, ${accentColor} ${pct}%, ${t.surfaceBorder} ${pct}%, ${t.surfaceBorder} 100%)`,
          borderRadius: 2,
          appearance: "none" as const,
          outline: "none",
          transition: "opacity 0.15s",
        }}
      />
    </div>
  );
}

function UnknownBlock({
  node,
  t,
}: {
  node: Record<string, unknown> & { type: string };
  t: ThemeTokens;
}) {
  return (
    <div
      style={{
        border: `1px dashed ${t.surfaceBorder}`,
        borderRadius: 6,
        padding: "6px 10px",
        background: t.overlayLight,
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: t.textDim,
          fontWeight: 600,
          marginBottom: 4,
        }}
      >
        Unknown: {node.type}
      </div>
      <pre
        style={{
          margin: 0,
          fontSize: 11,
          color: t.textMuted,
          fontFamily: "'Menlo', monospace",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {JSON.stringify(node, null, 2)}
      </pre>
    </div>
  );
}
