import { useState } from "react";
import { View, Text, TextInput, Pressable, ActivityIndicator } from "react-native";
import { X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { useCreatePromptTemplate } from "../../api/hooks/usePromptTemplates";

interface Props {
  content: string;
  onClose: () => void;
  onSaved?: (id: string) => void;
}

export function SaveAsTemplateModal({ content, onClose, onSaved }: Props) {
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const createMutation = useCreatePromptTemplate();

  const canSave = name.trim().length > 0 && !createMutation.isPending;

  const handleSave = async () => {
    if (!canSave) return;
    try {
      const result = await createMutation.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        content,
        category: "workspace_schema",
      });
      onSaved?.(result.id);
      onClose();
    } catch {
      // mutation error is handled by react-query
    }
  };

  if (typeof document === "undefined") return null;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      {/* Modal */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 400,
          maxWidth: "90vw",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          padding: 20,
        }}
      >
        {/* Header */}
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <Text style={{ fontSize: 14, fontWeight: "700", color: t.text }}>Save as New Template</Text>
          <Pressable onPress={onClose} hitSlop={8}>
            <X size={16} color={t.textDim} />
          </Pressable>
        </View>

        {/* Name */}
        <View style={{ marginBottom: 12 }}>
          <Text style={{ fontSize: 11, fontWeight: "600", color: t.textDim, marginBottom: 4 }}>Name</Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="e.g. My Custom Schema"
            placeholderTextColor={t.textDim}
            autoFocus
            style={{
              background: t.inputBg,
              borderWidth: 1,
              borderColor: t.inputBorder,
              borderRadius: 6,
              padding: 8,
              fontSize: 13,
              color: t.inputText,
            } as any}
          />
        </View>

        {/* Description */}
        <View style={{ marginBottom: 16 }}>
          <Text style={{ fontSize: 11, fontWeight: "600", color: t.textDim, marginBottom: 4 }}>Description (optional)</Text>
          <TextInput
            value={description}
            onChangeText={setDescription}
            placeholder="Brief description of this schema"
            placeholderTextColor={t.textDim}
            style={{
              background: t.inputBg,
              borderWidth: 1,
              borderColor: t.inputBorder,
              borderRadius: 6,
              padding: 8,
              fontSize: 13,
              color: t.inputText,
            } as any}
          />
        </View>

        {/* Actions */}
        <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
          <Pressable
            onPress={onClose}
            style={{
              paddingHorizontal: 12,
              paddingVertical: 6,
              borderRadius: 6,
              borderWidth: 1,
              borderColor: t.surfaceBorder,
            }}
          >
            <Text style={{ fontSize: 12, color: t.textDim }}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={handleSave}
            disabled={!canSave}
            style={{
              paddingHorizontal: 12,
              paddingVertical: 6,
              borderRadius: 6,
              backgroundColor: canSave ? t.accent : t.surfaceOverlay,
              opacity: canSave ? 1 : 0.5,
            }}
          >
            {createMutation.isPending ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={{ fontSize: 12, fontWeight: "600", color: "#fff" }}>Save Template</Text>
            )}
          </Pressable>
        </View>

        {createMutation.isError && (
          <Text style={{ color: t.danger, fontSize: 11, marginTop: 8 }}>
            Failed to save template. Please try again.
          </Text>
        )}
      </div>
    </>,
    document.body
  );
}
