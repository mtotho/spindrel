import { useState, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { X, ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotEditorData, ChannelSettings } from "@/src/types/api";

interface Props {
  editorData: BotEditorData;
  settings: ChannelSettings;
  filter: string;
  onSave: (patch: Partial<ChannelSettings>) => void;
}

export function EffectiveToolsList({ editorData, settings, filter, onSave }: Props) {
  const t = useThemeTokens();
  const q = filter.toLowerCase();

  const [localExpanded, setLocalExpanded] = useState(false);
  const [mcpExpanded, setMcpExpanded] = useState(false);
  const [clientExpanded, setClientExpanded] = useState(false);

  const localDisabled = settings.local_tools_disabled || [];
  const mcpDisabled = settings.mcp_servers_disabled || [];
  const clientDisabled = settings.client_tools_disabled || [];

  const localDisabledSet = new Set(localDisabled);
  const mcpDisabledSet = new Set(mcpDisabled);
  const clientDisabledSet = new Set(clientDisabled);

  // Bot's configured tools
  const botLocalTools = new Set(editorData.bot.local_tools || []);
  const botMcpServers = new Set(editorData.bot.mcp_servers || []);
  const botClientTools = new Set(editorData.bot.client_tools || []);

  // All available tools from editor data
  const allLocalTools = editorData.tool_groups.flatMap((g) =>
    g.packs.flatMap((p) => p.tools.map((t) => t.name)),
  );

  const disableLocal = useCallback((name: string) => {
    const next = [...localDisabled, name];
    onSave({ local_tools_disabled: next } as any);
  }, [localDisabled, onSave]);

  const enableLocal = useCallback((name: string) => {
    const next = localDisabled.filter((t) => t !== name);
    onSave({ local_tools_disabled: next.length ? next : null } as any);
  }, [localDisabled, onSave]);

  const disableMcp = useCallback((name: string) => {
    const next = [...mcpDisabled, name];
    onSave({ mcp_servers_disabled: next } as any);
  }, [mcpDisabled, onSave]);

  const enableMcp = useCallback((name: string) => {
    const next = mcpDisabled.filter((t) => t !== name);
    onSave({ mcp_servers_disabled: next.length ? next : null } as any);
  }, [mcpDisabled, onSave]);

  const disableClient = useCallback((name: string) => {
    const next = [...clientDisabled, name];
    onSave({ client_tools_disabled: next } as any);
  }, [clientDisabled, onSave]);

  const enableClient = useCallback((name: string) => {
    const next = clientDisabled.filter((t) => t !== name);
    onSave({ client_tools_disabled: next.length ? next : null } as any);
  }, [clientDisabled, onSave]);

  const hasAnyDisabled = localDisabled.length > 0 || mcpDisabled.length > 0 || clientDisabled.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Disable specific tools for this channel. The bot's tools are inherited by default — only overrides are shown here.
      </div>

      {/* Currently disabled tools */}
      {hasAnyDisabled && (
        <div style={{
          padding: 8, borderRadius: 6,
          background: "rgba(239,68,68,0.04)",
          border: "1px solid rgba(239,68,68,0.12)",
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.danger, marginBottom: 6 }}>
            Disabled for this channel
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {localDisabled.map((name) => (
              <DisabledChip key={`l-${name}`} name={name} category="local" onRemove={() => enableLocal(name)} />
            ))}
            {mcpDisabled.map((name) => (
              <DisabledChip key={`m-${name}`} name={name} category="mcp" onRemove={() => enableMcp(name)} />
            ))}
            {clientDisabled.map((name) => (
              <DisabledChip key={`c-${name}`} name={name} category="client" onRemove={() => enableClient(name)} />
            ))}
          </div>
        </div>
      )}

      {!hasAnyDisabled && (
        <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
          No tools disabled — using bot defaults.
        </div>
      )}

      {/* Local tools picker */}
      <ToolDisablePicker
        title={`Local Tools (${allLocalTools.length})`}
        expanded={localExpanded}
        onToggle={() => setLocalExpanded(!localExpanded)}

      >
        {editorData.tool_groups.map((group) => {
          const filteredPacks = group.packs
            .map((pack) => ({
              ...pack,
              tools: q ? pack.tools.filter((t) => t.name.toLowerCase().includes(q)) : pack.tools,
            }))
            .filter((p) => p.tools.length > 0);
          if (filteredPacks.length === 0) return null;

          return (
            <div key={group.integration} style={{ marginBottom: 6 }}>
              <div style={{
                fontSize: 10, fontWeight: 600, color: t.textDim, marginBottom: 3,
                textTransform: "uppercase",
              }}>
                {group.is_core ? "Core" : group.integration}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                {filteredPacks.flatMap((pack) =>
                  pack.tools.map((tool) => {
                    const dis = localDisabledSet.has(tool.name);
                    const onBot = botLocalTools.has(tool.name);
                    return (
                      <ToolChip
                        key={tool.name}
                        name={tool.name}
                        disabled={dis}
                        onBot={onBot}
                        onToggle={() => dis ? enableLocal(tool.name) : disableLocal(tool.name)}
                      />
                    );
                  }),
                )}
              </div>
            </div>
          );
        })}
      </ToolDisablePicker>

      {/* MCP servers picker */}
      {editorData.mcp_servers.length > 0 && (
        <ToolDisablePicker
          title={`MCP Servers (${editorData.mcp_servers.length})`}
          expanded={mcpExpanded}
          onToggle={() => setMcpExpanded(!mcpExpanded)}
  
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
            {editorData.mcp_servers
              .filter((s) => !q || s.toLowerCase().includes(q))
              .map((srv) => {
                const dis = mcpDisabledSet.has(srv);
                const onBot = botMcpServers.has(srv);
                return (
                  <ToolChip
                    key={srv}
                    name={srv}
                    disabled={dis}
                    onBot={onBot}
                    onToggle={() => dis ? enableMcp(srv) : disableMcp(srv)}
                  />
                );
              })}
          </div>
        </ToolDisablePicker>
      )}

      {/* Client tools picker */}
      {editorData.client_tools.length > 0 && (
        <ToolDisablePicker
          title={`Client Tools (${editorData.client_tools.length})`}
          expanded={clientExpanded}
          onToggle={() => setClientExpanded(!clientExpanded)}
  
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
            {editorData.client_tools
              .filter((ct) => !q || ct.toLowerCase().includes(q))
              .map((tool) => {
                const dis = clientDisabledSet.has(tool);
                const onBot = botClientTools.has(tool);
                return (
                  <ToolChip
                    key={tool}
                    name={tool}
                    disabled={dis}
                    onBot={onBot}
                    onToggle={() => dis ? enableClient(tool) : disableClient(tool)}
                  />
                );
              })}
          </div>
        </ToolDisablePicker>
      )}
    </div>
  );
}


function DisabledChip({ name, category, onRemove }: { name: string; category: string; onRemove: () => void }) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 6px 2px 8px", borderRadius: 4,
      background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
    }}>
      <span style={{ fontSize: 10, color: t.danger, fontFamily: "monospace", textDecoration: "line-through" }}>
        {name}
      </span>
      <span style={{ fontSize: 8, color: t.textDim }}>{category}</span>
      <Pressable onPress={onRemove} style={{ padding: 2, marginLeft: 2 }}>
        <X size={10} color={t.danger} />
      </Pressable>
    </div>
  );
}


function ToolDisablePicker({
  title, expanded, onToggle, children,
}: {
  title: string; expanded: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      borderRadius: 6,
      border: `1px solid ${t.surfaceRaised}`,
      overflow: "hidden",
    }}>
      <Pressable
        onPress={onToggle}
        style={{
          flexDirection: "row", alignItems: "center", gap: 6,
          padding: "6px 10px", backgroundColor: t.surface,
        } as any}
      >
        {expanded
          ? <ChevronDown size={12} color={t.textDim} />
          : <ChevronRight size={12} color={t.textDim} />}
        <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>{title}</Text>
        <Text style={{ fontSize: 10, color: t.textDim, marginLeft: "auto" }}>
          click tool to disable
        </Text>
      </Pressable>
      {expanded && (
        <div style={{ padding: 8 }}>
          {children}
        </div>
      )}
    </div>
  );
}


function ToolChip({
  name, disabled, onBot, onToggle,
}: {
  name: string; disabled: boolean; onBot: boolean; onToggle: () => void;
}) {
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={onToggle}
      style={{
        flexDirection: "row", alignItems: "center", gap: 3,
        padding: "2px 6px", borderRadius: 3,
        backgroundColor: disabled ? "rgba(239,68,68,0.06)" : "transparent",
        borderWidth: 1,
        borderColor: disabled ? "rgba(239,68,68,0.15)" : "transparent",
      } as any}
    >
      <Text style={{
        fontFamily: "monospace", fontSize: 10,
        color: disabled ? t.danger : t.textDim,
        textDecorationLine: disabled ? "line-through" : "none",
      }} numberOfLines={1}>{name}</Text>
      {onBot && !disabled && (
        <View style={{
          width: 4, height: 4, borderRadius: 2,
          backgroundColor: "#16a34a",
        }} />
      )}
    </Pressable>
  );
}
