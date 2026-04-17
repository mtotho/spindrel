
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useParams } from "react-router-dom";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useTool } from "@/src/api/hooks/useTools";
import { Section } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";
import { ToolWidgetSection } from "./ToolWidgetSection";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
      <span style={{
        fontSize: 11, color: t.text, fontFamily: "monospace",
        maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right",
      }}>{value}</span>
    </div>
  );
}

function TypeBadge({ tool }: { tool: { server_name?: string | null; source_integration?: string | null } }) {
  const t = useThemeTokens();
  if (tool.server_name) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(249,115,22,0.15)", color: "#ea580c",
      }}>
        mcp:{tool.server_name}
      </span>
    );
  }
  if (tool.source_integration) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: t.purpleSubtle, color: t.purple,
      }}>
        integration:{tool.source_integration}
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: t.accentSubtle, color: t.accent,
    }}>
      local
    </span>
  );
}

function ParamRow({ name, param, required }: { name: string; param: any; required: boolean }) {
  const t = useThemeTokens();
  const type = param.type || (param.enum ? "enum" : "any");
  return (
    <div style={{
      display: "flex", flexDirection: "row", gap: 8, padding: "6px 0",
      borderBottom: `1px solid ${t.surfaceBorder}`,
      alignItems: "flex-start",
    }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, minWidth: 140, flexShrink: 0 }}>
        <span style={{ fontSize: 12, fontFamily: "monospace", color: t.text, fontWeight: 600 }}>
          {name}
        </span>
        {required && (
          <span style={{ fontSize: 9, color: t.dangerMuted, fontWeight: 700 }}>REQ</span>
        )}
      </div>
      <span style={{ fontSize: 11, color: t.accent, fontFamily: "monospace", flexShrink: 0 }}>
        {type}
        {param.enum && `: ${param.enum.join(" | ")}`}
      </span>
      {param.description && (
        <span style={{ fontSize: 11, color: t.textMuted, flex: 1 }}>
          {param.description}
        </span>
      )}
    </div>
  );
}

export default function ToolDetailScreen() {
  const t = useThemeTokens();
  const { toolId } = useParams<{ toolId: string }>();
  const { data: tool, isLoading } = useTool(toolId);
  const { width } = useWindowSize();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!tool) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <span style={{ color: t.textDim, fontSize: 13 }}>Tool not found</span>
      </div>
    );
  }

  const params = tool.parameters?.properties || {};
  const requiredParams = new Set<string>(tool.parameters?.required || []);
  const paramNames = Object.keys(params);
  const fullSchema = tool.schema_ || {};

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Tools"
        backTo="/admin/tools"
        title={tool.tool_name}
        right={<TypeBadge tool={tool} />}
      />

      {/* Body */}
      <div style={{ display: "flex", flex: 1, ...(isWide ? { flexDirection: "row" as const } : {}) }}>
        {/* Main content */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: `1px solid ${t.surfaceOverlay}` } : {}),
          display: "flex", flexDirection: "column", gap: 20,
          padding: isWide ? "16px 20px" : "12px 12px",
        }}>
          {/* Description */}
          {tool.description && (
            <Section title="Description">
              <div style={{
                fontSize: 13, color: t.text, lineHeight: 1.6,
                padding: "8px 12px", background: t.inputBg, borderRadius: 8,
                border: `1px solid ${t.surfaceOverlay}`,
              }}>
                {tool.description}
              </div>
            </Section>
          )}

          {/* Widget template */}
          <ToolWidgetSection
            toolName={tool.tool_name}
            bareToolName={
              tool.tool_name.includes("-")
                ? tool.tool_name.split("-").slice(1).join("-")
                : tool.tool_name
            }
          />

          {/* Parameters */}
          <Section title={`Parameters (${paramNames.length})`}>
            {paramNames.length === 0 ? (
              <div style={{ fontSize: 12, color: t.textDim, padding: "8px 0" }}>
                No parameters
              </div>
            ) : (
              <div style={{
                background: t.inputBg, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
                padding: "4px 12px",
              }}>
                {paramNames.map((name) => (
                  <ParamRow
                    key={name}
                    name={name}
                    param={params[name]}
                    required={requiredParams.has(name)}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* Full schema */}
          <Section title="Full Schema (JSON)">
            <pre style={{
              background: t.surface, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8,
              padding: 12, fontSize: 11, lineHeight: 1.5,
              color: t.textMuted, fontFamily: "monospace",
              overflow: "auto", maxHeight: 500,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>
              {JSON.stringify(fullSchema, null, 2)}
            </pre>
          </Section>
        </div>

        {/* Sidebar info */}
        <div style={{
          ...(isWide ? { flex: 1.2, minWidth: 240 } : {}),
          padding: isWide ? "16px 20px" : "12px 12px",
          borderTop: isWide ? "none" : `1px solid ${t.surfaceOverlay}`,
        }}>
          <Section title="Info">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <InfoRow label="Tool Key" value={tool.tool_key} />
              <InfoRow label="Type" value={tool.server_name ? "MCP" : tool.source_integration ? "Integration" : "Local"} />
              {tool.server_name && <InfoRow label="MCP Server" value={tool.server_name} />}
              {tool.source_integration && <InfoRow label="Integration" value={tool.source_integration} />}
              {tool.source_file && <InfoRow label="Source File" value={tool.source_file} />}
              {tool.source_dir && <InfoRow label="Source Dir" value={tool.source_dir} />}
              <InfoRow label="Indexed" value={fmtDate(tool.indexed_at)} />
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
