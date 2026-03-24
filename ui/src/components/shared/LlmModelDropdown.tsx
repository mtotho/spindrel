import { View, Text, Pressable, ScrollView } from "react-native";
import { useState, useRef, useEffect } from "react";
import { ChevronDown, X } from "lucide-react";
import { useModelGroups } from "../../api/hooks/useModels";

interface Props {
  value: string;
  onChange: (modelId: string) => void;
  placeholder?: string;
  label?: string;
  allowClear?: boolean;
}

export function LlmModelDropdown({
  value,
  onChange,
  placeholder = "Select model...",
  label,
  allowClear = true,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { data: groups, isLoading } = useModelGroups();

  // Close on outside click
  const containerRef = useRef<View>(null);

  const filteredGroups = groups
    ?.map((g) => ({
      ...g,
      models: g.models.filter(
        (m) =>
          !search ||
          m.id.toLowerCase().includes(search.toLowerCase()) ||
          m.display.toLowerCase().includes(search.toLowerCase())
      ),
    }))
    .filter((g) => g.models.length > 0);

  const selectedDisplay =
    groups
      ?.flatMap((g) => g.models)
      .find((m) => m.id === value)?.display ?? value;

  return (
    <View>
      {label && (
        <Text className="text-text-dim text-xs mb-1">{label}</Text>
      )}
      <View ref={containerRef} className="relative">
        {/* Trigger */}
        <Pressable
          onPress={() => setOpen(!open)}
          className="flex-row items-center bg-surface border border-surface-border rounded-lg px-3 py-2"
        >
          <Text
            className={`flex-1 text-sm ${value ? "text-text" : "text-text-dim"}`}
            numberOfLines={1}
          >
            {value || placeholder}
          </Text>
          {allowClear && value ? (
            <Pressable
              onPress={(e) => {
                e.stopPropagation?.();
                onChange("");
                setOpen(false);
              }}
              className="p-0.5"
            >
              <X size={14} color="#999999" />
            </Pressable>
          ) : (
            <ChevronDown size={14} color="#999999" />
          )}
        </Pressable>

        {/* Dropdown */}
        {open && (
          <View className="absolute top-full left-0 right-0 z-50 mt-1 bg-surface-raised border border-surface-border rounded-lg shadow-lg overflow-hidden"
            style={{ maxHeight: 280 }}>
            {/* Search input */}
            <View className="border-b border-surface-border px-3 py-2">
              <input
                type="text"
                value={search}
                onChange={(e: any) => setSearch(e.target?.value ?? e.nativeEvent?.text ?? "")}
                placeholder="Search models..."
                autoFocus
                style={{
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "#e5e5e5",
                  fontSize: 13,
                  width: "100%",
                }}
              />
            </View>

            <ScrollView style={{ maxHeight: 240 }}>
              {isLoading ? (
                <Text className="text-text-dim text-xs p-3">Loading models...</Text>
              ) : (
                filteredGroups?.map((group) => (
                  <View key={group.provider_name}>
                    <View className="px-3 py-1.5 bg-surface-overlay">
                      <Text className="text-text-dim text-[10px] font-semibold tracking-wider">
                        {group.provider_name}
                      </Text>
                    </View>
                    {group.models.map((model) => (
                      <Pressable
                        key={model.id}
                        onPress={() => {
                          onChange(model.id);
                          setOpen(false);
                          setSearch("");
                        }}
                        className={`px-3 py-2 hover:bg-surface-overlay ${
                          model.id === value ? "bg-accent/10" : ""
                        }`}
                      >
                        <Text className="text-text text-xs" numberOfLines={1}>
                          {model.id}
                        </Text>
                        {model.display !== model.id && (
                          <Text className="text-text-dim text-[10px]" numberOfLines={1}>
                            {model.display}
                          </Text>
                        )}
                      </Pressable>
                    ))}
                  </View>
                ))
              )}
              {filteredGroups?.length === 0 && (
                <Text className="text-text-dim text-xs p-3 text-center">No models found</Text>
              )}
            </ScrollView>
          </View>
        )}
      </View>

      {/* Click-away overlay */}
      {open && (
        <Pressable
          onPress={() => {
            setOpen(false);
            setSearch("");
          }}
          style={{
            position: "fixed" as any,
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 40,
          }}
        />
      )}
    </View>
  );
}
