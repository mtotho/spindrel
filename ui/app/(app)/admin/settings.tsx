import { useState, useEffect, useCallback } from "react";
import { View, Text, ScrollView, ActivityIndicator, Pressable } from "react-native";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Check } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { FallbackModelList, type FallbackModelEntry } from "@/src/components/shared/FallbackModelList";
import { Section } from "@/src/components/shared/FormControls";

function useGlobalFallbackModels() {
  return useQuery({
    queryKey: ["global-fallback-models"],
    queryFn: () =>
      apiFetch<{ models: FallbackModelEntry[] }>("/api/v1/admin/global-fallback-models"),
  });
}

function useUpdateGlobalFallbackModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (models: FallbackModelEntry[]) =>
      apiFetch("/api/v1/admin/global-fallback-models", {
        method: "PUT",
        body: JSON.stringify({ models }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["global-fallback-models"] });
    },
  });
}

export default function AdminSettingsPage() {
  const { data, isLoading } = useGlobalFallbackModels();
  const updateMut = useUpdateGlobalFallbackModels();
  const [models, setModels] = useState<FallbackModelEntry[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data?.models) {
      setModels(data.models);
      setDirty(false);
    }
  }, [data]);

  const handleChange = useCallback((v: FallbackModelEntry[]) => {
    setModels(v);
    setDirty(true);
    setSaved(false);
  }, []);

  const handleSave = useCallback(async () => {
    // Filter out entries with empty model
    const clean = models.filter((m) => m.model);
    await updateMut.mutateAsync(clean);
    setDirty(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, [models, updateMut]);

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      <MobileHeader title="Global Settings" />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 24, maxWidth: 720 }}
      >
        <Section title="Global Fallback Models">
          <Text style={{ color: "#888", fontSize: 13, marginBottom: 12 }}>
            Catch-all fallback chain appended after channel/bot fallbacks. When all per-channel
            and per-bot fallbacks are exhausted, these models are tried in order.
          </Text>

          {isLoading ? (
            <ActivityIndicator color="#3b82f6" />
          ) : (
            <FallbackModelList
              value={models}
              onChange={handleChange}
            />
          )}
        </Section>

        <View style={{ marginTop: 20, flexDirection: "row", gap: 12, alignItems: "center" }}>
          <Pressable
            onPress={handleSave}
            disabled={!dirty || updateMut.isPending}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              backgroundColor: dirty ? "#3b82f6" : "#333",
              paddingHorizontal: 16,
              paddingVertical: 8,
              borderRadius: 8,
              opacity: dirty ? 1 : 0.5,
            }}
          >
            {updateMut.isPending ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : saved ? (
              <Check size={14} color="#fff" />
            ) : (
              <Save size={14} color="#fff" />
            )}
            <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
              {saved ? "Saved" : "Save"}
            </Text>
          </Pressable>

          {updateMut.isError && (
            <Text style={{ color: "#ef4444", fontSize: 12 }}>
              Failed to save
            </Text>
          )}
        </View>
      </ScrollView>
    </View>
  );
}
