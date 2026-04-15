/**
 * ComponentRenderer — declarative component vocabulary for tool output rendering.
 *
 * Content type: `application/vnd.spindrel.components+json`
 *
 * Body schema:
 *   { v: 1, components: ComponentNode[] }
 *
 * Integrations compose rich output from ~10 typed primitives (heading, properties,
 * table, links, code, image, status, divider, section, text) without needing
 * custom React renderers. Inspired by Slack Block Kit / Discord Components v2.
 *
 * Unknown component types render as a muted JSON dump (forward-compatible).
 * Unknown schema versions fall back to plain_body via the parent.
 */
import { useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  ExternalLink,
  GitBranch,
  Globe,
  Mail,
  FileText,
  Link as LinkIcon,
} from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";
import { MarkdownContent } from "../MarkdownContent";

// ── Schema types ──

interface ComponentBody {
  v: number;
  components: ComponentNode[];
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
  | { type: string; [key: string]: unknown }; // forward-compat catch-all

interface TextNode {
  type: "text";
  content: string;
  style?: "default" | "muted" | "bold" | "code";
  markdown?: boolean;
}

interface HeadingNode {
  type: "heading";
  text: string;
  level?: 1 | 2 | 3;
}

interface PropertiesNode {
  type: "properties";
  items: { label: string; value: string; color?: SemanticSlot }[];
  layout?: "vertical" | "inline";
}

interface TableNode {
  type: "table";
  columns: string[];
  rows: string[][];
  compact?: boolean;
}

interface LinksNode {
  type: "links";
  items: {
    url: string;
    title: string;
    subtitle?: string;
    icon?: "github" | "web" | "email" | "file" | "link";
  }[];
}

interface CodeNode {
  type: "code";
  content: string;
  language?: string;
}

interface ImageNode {
  type: "image";
  url: string;
  alt?: string;
  height?: number;
}

interface StatusNode {
  type: "status";
  text: string;
  color?: SemanticSlot;
}

interface DividerNode {
  type: "divider";
  label?: string;
}

interface SectionNode {
  type: "section";
  children: ComponentNode[];
  label?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
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
}

export function ComponentRenderer({ body, t }: Props) {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {parsed.components.map((node, i) => (
        <RenderNode key={i} node={node} t={t} depth={0} />
      ))}
    </div>
  );
}

// ── Recursive dispatch ──

function RenderNode({
  node,
  t,
  depth,
}: {
  node: ComponentNode;
  t: ThemeTokens;
  depth: number;
}) {
  switch (node.type) {
    case "text":
      return <TextBlock node={node as TextNode} t={t} />;
    case "heading":
      return <HeadingBlock node={node as HeadingNode} t={t} />;
    case "properties":
      return <PropertiesBlock node={node as PropertiesNode} t={t} />;
    case "table":
      return <TableBlock node={node as TableNode} t={t} />;
    case "links":
      return <LinksBlock node={node as LinksNode} t={t} />;
    case "code":
      return <CodeBlock node={node as CodeNode} t={t} />;
    case "image":
      return <ImageBlock node={node as ImageNode} t={t} />;
    case "status":
      return <StatusBadge node={node as StatusNode} t={t} />;
    case "divider":
      return <DividerBlock node={node as DividerNode} t={t} />;
    case "section":
      return <SectionBlock node={node as SectionNode} t={t} depth={depth} />;
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
}: {
  node: PropertiesNode;
  t: ThemeTokens;
}) {
  const isInline = node.layout === "inline";

  if (isInline) {
    return (
      <div
        style={{
          display: "flex", flexDirection: "row",
          flexWrap: "wrap",
          gap: "4px 12px",
          fontSize: 12,
        }}
      >
        {node.items.map((item, i) => (
          <span key={i}>
            <span style={{ color: t.textMuted }}>{item.label}: </span>
            <span style={{ color: slotColor(item.color, t) }}>
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
        gap: "3px 12px",
        fontSize: 12,
      }}
    >
      {node.items.map((item, i) => (
        <div key={i} style={{ display: "contents" }}>
          <span style={{ color: t.textMuted, whiteSpace: "nowrap" }}>
            {item.label}
          </span>
          <span style={{ color: slotColor(item.color, t) }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}

function TableBlock({ node, t }: { node: TableNode; t: ThemeTokens }) {
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        overflow: "hidden",
        maxHeight: 360,
        overflowY: "auto",
      }}
    >
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: node.compact ? 11 : 12,
          fontFamily: "'Menlo', monospace",
        }}
      >
        <thead>
          <tr style={{ background: t.codeBg }}>
            {node.columns.map((col, i) => (
              <th
                key={i}
                style={{
                  padding: node.compact ? "4px 8px" : "6px 10px",
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
          {node.rows.map((row, ri) => (
            <tr
              key={ri}
              style={{
                borderBottom:
                  ri < node.rows.length - 1
                    ? `1px solid ${t.surfaceBorder}`
                    : undefined,
              }}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  style={{
                    padding: node.compact ? "3px 8px" : "5px 10px",
                    color: t.contentText,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
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
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {node.items.map((item, i) => {
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
  return (
    <div
      style={{
        borderRadius: 6,
        overflow: "hidden",
        border: `1px solid ${t.surfaceBorder}`,
        background: t.codeBg,
      }}
    >
      <img
        src={node.url}
        alt={node.alt ?? ""}
        style={{
          display: "block",
          maxWidth: "100%",
          maxHeight: node.height ?? 400,
          objectFit: "contain",
        }}
      />
    </div>
  );
}

function StatusBadge({ node, t }: { node: StatusNode; t: ThemeTokens }) {
  const color = slotColor(node.color, t);
  const bg = slotBg(node.color, t);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        color,
        background: bg,
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
}: {
  node: SectionNode;
  t: ThemeTokens;
  depth: number;
}) {
  const [open, setOpen] = useState(node.defaultOpen !== false);

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
          <RenderNode key={i} node={child} t={t} depth={depth + 1} />
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
            <RenderNode key={i} node={child} t={t} depth={depth + 1} />
          ))}
        </div>
      )}
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
