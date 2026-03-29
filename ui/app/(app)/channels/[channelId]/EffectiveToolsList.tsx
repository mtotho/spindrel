import { useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotEditorData, ChannelSettings, EffectiveTools } from "@/src/types/api";

interface Props {
  editorData: BotEditorData;
  settings: ChannelSettings;
  effective: EffectiveTools;
  filter: string;
  onSave: (patch: Partial<ChannelSettings>) => void;
}

export function EffectiveToolsList({ editorData, settings, effective, filter, onSave }: Props) {
  const t = useThemeTokens();
  const q = filter.toLowerCase();

  const localDisabled = new Set(settings.local_tools_disabled || []);
  const mcpDisabled = new Set(settings.mcp_servers_disabled || []);
  const clientDisabled = new Set(settings.client_tools_disabled || []);

  const toggleLocal = useCallback((name: string) => {
    const current = settings.local_tools_disabled || [];
    const next = current.includes(name)
      ? current.filter((t) => t !== name)
      : [...current, name];
    onSave({ local_tools_disabled: next.length ? next : null } as any);
  }, [settings, onSave]);

  const toggleMcp = useCallback((name: string) => {
    const current = settings.mcp_servers_disabled || [];
    const next = current.includes(name)
      ? current.filter((t) => t !== name)
      : [...current, name];
    onSave({ mcp_servers_disabled: next.length ? next : null } as any);
  }, [settings, onSave]);

  const toggleClient = useCallback((name: string) => {
    const current = settings.client_tools_disabled || [];
    const next = current.includes(name)
      ? current.filter((t) => t !== name)
      : [...current, name];
    onSave({ client_tools_disabled: next.length ? next : null } as any);
  }, [settings, onSave]);

  return (
    <>
      {/* Local Tools */}
      {editorData.tool_groups.map((group) => {
        const filteredPacks = group.packs
          .map((pack) => ({
            ...pack,
            tools: q ? pack.tools.filter((t) => t.name.toLowerCase().includes(q)) : pack.tools,
          }))
          .filter((p) => p.tools.length > 0);
        if (filteredPacks.length === 0) return null;

        const groupTools = group.packs.flatMap((p) => p.tools.map((t) => t.name));
        const disabledInGroup = groupTools.filter((n) => localDisabled.has(n)).length;

        return (
          <View
            key={group.integration}
            style={{
              borderWidth: 1,
              borderColor: t.surfaceRaised,
              borderRadius: 8,
              overflow: "hidden",
              marginBottom: 8,
            }}
          >
            {/* Group header */}
            <View
              style={{
                padding: 6,
                paddingHorizontal: 10,
                backgroundColor: t.surface,
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
              }}
            >
              {group.is_core ? (
                <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>Core</Text>
              ) : (
                <Text
                  style={{
                    fontSize: 9,
                    fontWeight: "700",
                    paddingHorizontal: 5,
                    paddingVertical: 1,
                    borderRadius: 3,
                    backgroundColor: t.warningSubtle,
                    color: t.warningMuted,
                    textTransform: "uppercase",
                  }}
                >
                  {group.integration}
                </Text>
              )}
              <Text style={{ fontSize: 9, color: t.textDim, marginLeft: "auto" }}>
                {disabledInGroup > 0 ? `${disabledInGroup} disabled` : `${groupTools.length} tools`}
              </Text>
            </View>

            {/* Tools grid */}
            <View style={{ flexDirection: "row", flexWrap: "wrap", padding: 4, gap: 1 }}>
              {filteredPacks.flatMap((pack) =>
                pack.tools.map((tool) => {
                  const disabled = localDisabled.has(tool.name);
                  return (
                    <Pressable
                      key={tool.name}
                      onPress={() => toggleLocal(tool.name)}
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 4,
                        padding: 3,
                        paddingHorizontal: 6,
                        borderRadius: 3,
                        width: "49%",
                        backgroundColor: disabled ? "rgba(239,68,68,0.06)" : "transparent",
                        borderWidth: 1,
                        borderColor: disabled ? "rgba(239,68,68,0.15)" : "transparent",
                        opacity: disabled ? 0.6 : 1,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!disabled}
                        readOnly
                        style={{ accentColor: disabled ? t.danger : t.accent }}
                      />
                      <Text
                        style={{
                          fontFamily: "monospace",
                          fontSize: 11,
                          color: disabled ? t.danger : t.textMuted,
                          textDecorationLine: disabled ? "line-through" : "none",
                        }}
                        numberOfLines={1}
                      >
                        {tool.name}
                      </Text>
                    </Pressable>
                  );
                }),
              )}
            </View>
          </View>
        );
      })}

      {/* MCP Servers */}
      {editorData.mcp_servers.length > 0 && (
        <View
          style={{
            borderWidth: 1,
            borderColor: t.surfaceRaised,
            borderRadius: 8,
            overflow: "hidden",
            marginBottom: 8,
          }}
        >
          <View
            style={{
              padding: 6,
              paddingHorizontal: 10,
              backgroundColor: t.surface,
              flexDirection: "row",
              alignItems: "center",
            }}
          >
            <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>MCP Servers</Text>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", padding: 4, gap: 2 }}>
            {editorData.mcp_servers
              .filter((s) => !q || s.toLowerCase().includes(q))
              .map((srv) => {
                const disabled = mcpDisabled.has(srv);
                return (
                  <Pressable
                    key={srv}
                    onPress={() => toggleMcp(srv)}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 6,
                      padding: 4,
                      paddingHorizontal: 8,
                      borderRadius: 4,
                      width: "49%",
                      backgroundColor: disabled ? "rgba(239,68,68,0.06)" : "transparent",
                      borderWidth: 1,
                      borderColor: disabled ? "rgba(239,68,68,0.15)" : "transparent",
                      opacity: disabled ? 0.6 : 1,
                    }}
                  >
                    <input type="checkbox" checked={!disabled} readOnly style={{ accentColor: disabled ? t.danger : t.accent }} />
                    <Text
                      style={{
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: disabled ? t.danger : t.textMuted,
                        textDecorationLine: disabled ? "line-through" : "none",
                      }}
                    >
                      {srv}
                    </Text>
                  </Pressable>
                );
              })}
          </View>
        </View>
      )}

      {/* Client Tools */}
      {editorData.client_tools.length > 0 && (
        <View
          style={{
            borderWidth: 1,
            borderColor: t.surfaceRaised,
            borderRadius: 8,
            overflow: "hidden",
            marginBottom: 8,
          }}
        >
          <View
            style={{
              padding: 6,
              paddingHorizontal: 10,
              backgroundColor: t.surface,
              flexDirection: "row",
              alignItems: "center",
            }}
          >
            <Text style={{ fontSize: 11, fontWeight: "600", color: t.textMuted }}>Client Tools</Text>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", padding: 4, gap: 2 }}>
            {editorData.client_tools
              .filter((ct) => !q || ct.toLowerCase().includes(q))
              .map((tool) => {
                const disabled = clientDisabled.has(tool);
                return (
                  <Pressable
                    key={tool}
                    onPress={() => toggleClient(tool)}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 6,
                      padding: 4,
                      paddingHorizontal: 8,
                      borderRadius: 4,
                      width: "49%",
                      backgroundColor: disabled ? "rgba(239,68,68,0.06)" : "transparent",
                      borderWidth: 1,
                      borderColor: disabled ? "rgba(239,68,68,0.15)" : "transparent",
                      opacity: disabled ? 0.6 : 1,
                    }}
                  >
                    <input type="checkbox" checked={!disabled} readOnly style={{ accentColor: disabled ? t.danger : t.accent }} />
                    <Text
                      style={{
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: disabled ? t.danger : t.textMuted,
                        textDecorationLine: disabled ? "line-through" : "none",
                      }}
                    >
                      {tool}
                    </Text>
                  </Pressable>
                );
              })}
          </View>
        </View>
      )}
    </>
  );
}
