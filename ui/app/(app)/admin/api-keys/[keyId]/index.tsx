import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, Pressable } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft, Trash2, Copy, Check, AlertTriangle } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import {
  useApiKey,
  useApiKeyScopes,
  useCreateApiKey,
  useUpdateApiKey,
  useDeleteApiKey,
} from "@/src/api/hooks/useApiKeys";
import {
  Section,
  FormRow,
  TextInput,
  Toggle,
} from "@/src/components/shared/FormControls";

function ScopeCheckboxGroup({
  groups,
  selected,
  onChange,
}: {
  groups: Record<string, string[]>;
  selected: string[];
  onChange: (scopes: string[]) => void;
}) {
  const set = new Set(selected);

  const toggle = (scope: string) => {
    const next = new Set(set);
    if (next.has(scope)) {
      next.delete(scope);
    } else {
      next.add(scope);
    }
    onChange(Array.from(next));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {Object.entries(groups).map(([group, scopes]) => (
        <div key={group}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#888",
              marginBottom: 6,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            {group}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {scopes.map((scope) => {
              const checked = set.has(scope);
              const isAdmin = scope === "admin";
              return (
                <button
                  key={scope}
                  onClick={() => toggle(scope)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 5,
                    border: checked
                      ? isAdmin
                        ? "1px solid rgba(239,68,68,0.4)"
                        : "1px solid rgba(59,130,246,0.4)"
                      : "1px solid #333",
                    background: checked
                      ? isAdmin
                        ? "rgba(239,68,68,0.1)"
                        : "rgba(59,130,246,0.1)"
                      : "transparent",
                    cursor: "pointer",
                    fontSize: 12,
                    color: checked
                      ? isAdmin
                        ? "#fca5a5"
                        : "#93c5fd"
                      : "#666",
                    fontWeight: checked ? 600 : 400,
                  }}
                >
                  <span
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 3,
                      border: checked
                        ? "none"
                        : "1px solid #444",
                      background: checked
                        ? isAdmin
                          ? "#ef4444"
                          : "#3b82f6"
                        : "transparent",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    {checked && (
                      <Check size={10} color="#fff" strokeWidth={3} />
                    )}
                  </span>
                  {scope}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ApiKeyDetailScreen() {
  const { keyId } = useLocalSearchParams<{ keyId: string }>();
  const isNew = keyId === "new";
  const goBack = useGoBack("/admin/api-keys");

  const { data: apiKey, isLoading } = useApiKey(isNew ? undefined : keyId);
  const { data: scopeGroups } = useApiKeyScopes();
  const createMut = useCreateApiKey();
  const updateMut = useUpdateApiKey(keyId);
  const deleteMut = useDeleteApiKey();

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [isActive, setIsActive] = useState(true);
  const [expiresAt, setExpiresAt] = useState("");
  const [initialized, setInitialized] = useState(isNew);

  // Created key reveal state
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Initialize from loaded data
  if (apiKey && !initialized) {
    setName(apiKey.name);
    setScopes(apiKey.scopes);
    setIsActive(apiKey.is_active);
    setExpiresAt(apiKey.expires_at || "");
    setInitialized(true);
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  const handleSave = useCallback(async () => {
    if (isNew) {
      const result = await createMut.mutateAsync({
        name: name.trim(),
        scopes,
        expires_at: expiresAt || null,
      });
      setCreatedKey(result.full_key);
    } else {
      await updateMut.mutateAsync({
        name: name.trim(),
        scopes,
        is_active: isActive,
        expires_at: expiresAt || null,
      });
    }
  }, [isNew, name, scopes, isActive, expiresAt, createMut, updateMut]);

  const handleDelete = useCallback(async () => {
    if (!confirm("Delete this API key? This cannot be undone.")) return;
    await deleteMut.mutateAsync(keyId!);
    goBack();
  }, [keyId, deleteMut, goBack]);

  const handleCopy = useCallback(() => {
    if (createdKey) {
      navigator.clipboard.writeText(createdKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [createdKey]);

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  const hasAdminScope = scopes.includes("admin");

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 20px",
          borderBottom: "1px solid #222",
        }}
      >
        <button
          onClick={goBack}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 4,
          }}
        >
          <ChevronLeft size={22} color="#888" />
        </button>
        <span
          style={{
            flex: 1,
            fontSize: 16,
            fontWeight: 600,
            color: "#e5e5e5",
          }}
        >
          {isNew ? "New API Key" : "Edit API Key"}
        </span>
        {!isNew && (
          <button
            onClick={handleDelete}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "6px 12px",
              borderRadius: 6,
              background: "rgba(239,68,68,0.1)",
              border: "1px solid rgba(239,68,68,0.2)",
              cursor: "pointer",
              fontSize: 12,
              color: "#f87171",
            }}
          >
            <Trash2 size={13} /> Delete
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={isSaving || !name.trim()}
          style={{
            padding: "6px 18px",
            borderRadius: 6,
            background:
              isSaving || !name.trim() ? "#333" : "#3b82f6",
            border: "none",
            cursor: isSaving || !name.trim() ? "default" : "pointer",
            fontSize: 13,
            fontWeight: 600,
            color: "#fff",
            opacity: isSaving || !name.trim() ? 0.5 : 1,
          }}
        >
          {isSaving ? "Saving..." : createdKey ? "Done" : "Save"}
        </button>
      </div>

      <ScrollView style={{ flex: 1 }}>
        <div
          style={{ padding: 20, maxWidth: 800, margin: "0 auto", width: "100%" }}
        >
          {/* Key reveal (create only) */}
          {createdKey && (
            <div
              style={{
                padding: 16,
                borderRadius: 10,
                background: "rgba(34,197,94,0.08)",
                border: "1px solid rgba(34,197,94,0.2)",
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <AlertTriangle size={14} color="#fbbf24" />
                <span
                  style={{ fontSize: 13, fontWeight: 600, color: "#fbbf24" }}
                >
                  Save this key now. It won't be shown again.
                </span>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <code
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: "#1a1a1a",
                    fontSize: 12,
                    color: "#86efac",
                    wordBreak: "break-all",
                    fontFamily: "monospace",
                  }}
                >
                  {createdKey}
                </code>
                <button
                  onClick={handleCopy}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: "#222",
                    border: "1px solid #333",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: copied ? "#86efac" : "#888",
                  }}
                >
                  {copied ? (
                    <Check size={13} />
                  ) : (
                    <Copy size={13} />
                  )}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          )}

          <Section title="Identity">
            <FormRow label="Name">
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="e.g. workspace-bot-key"
              />
            </FormRow>
            {!isNew && (
              <>
                <FormRow label="Prefix">
                  <code
                    style={{
                      fontSize: 13,
                      color: "#888",
                      fontFamily: "monospace",
                    }}
                  >
                    {apiKey?.key_prefix}...
                  </code>
                </FormRow>
                <Toggle
                  value={isActive}
                  onChange={setIsActive}
                  label="Active"
                  description="Inactive keys are rejected on auth"
                />
              </>
            )}
          </Section>

          <Section title="Scopes">
            {hasAdminScope && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: "rgba(239,68,68,0.08)",
                  border: "1px solid rgba(239,68,68,0.15)",
                  fontSize: 12,
                  color: "#fca5a5",
                  marginBottom: 12,
                }}
              >
                Warning: admin scope grants full access to all endpoints
                including admin panel.
              </div>
            )}
            {scopeGroups ? (
              <ScopeCheckboxGroup
                groups={scopeGroups.groups}
                selected={scopes}
                onChange={setScopes}
              />
            ) : (
              <ActivityIndicator color="#3b82f6" />
            )}
          </Section>

          <Section title="Expiration">
            <FormRow
              label="Expires at"
              description="Leave empty for no expiration"
            >
              <TextInput
                value={expiresAt}
                onChangeText={setExpiresAt}
                placeholder="YYYY-MM-DDTHH:MM:SSZ"
              />
            </FormRow>
          </Section>

          {!isNew && apiKey && (
            <Section title="Info">
              <FormRow label="Created">
                <span style={{ fontSize: 13, color: "#888" }}>
                  {new Date(apiKey.created_at).toLocaleString()}
                </span>
              </FormRow>
              <FormRow label="Last used">
                <span style={{ fontSize: 13, color: "#888" }}>
                  {apiKey.last_used_at
                    ? new Date(apiKey.last_used_at).toLocaleString()
                    : "Never"}
                </span>
              </FormRow>
            </Section>
          )}
        </div>
      </ScrollView>
    </View>
  );
}
