import { useState } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { Lock, Plus, Trash2, Edit2, Check, X, ArrowLeft } from "lucide-react";
import {
  useSecretValues,
  useCreateSecretValue,
  useDeleteSecretValue,
  useUpdateSecretValue,
  type SecretValueItem,
} from "@/src/api/hooks/useSecretValues";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function SecretCard({
  secret,
  onDelete,
  onEdit,
}: {
  secret: SecretValueItem;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const t = useThemeTokens();
  const created = secret.created_at
    ? new Date(secret.created_at).toLocaleDateString()
    : "Unknown";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "16px 20px",
        background: t.inputBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceOverlay}`,
        width: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Lock size={14} color={t.accent} />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: t.text,
            flex: 1,
            fontFamily: "monospace",
          }}
        >
          {secret.name}
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          <button
            onClick={onEdit}
            style={{
              padding: "4px 8px",
              borderRadius: 4,
              border: `1px solid ${t.surfaceOverlay}`,
              background: "transparent",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
          >
            <Edit2 size={12} color={t.textDim} />
          </button>
          <button
            onClick={onDelete}
            style={{
              padding: "4px 8px",
              borderRadius: 4,
              border: `1px solid ${t.surfaceOverlay}`,
              background: "transparent",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
          >
            <Trash2 size={12} color={t.danger} />
          </button>
        </div>
      </div>

      {secret.description && (
        <div style={{ fontSize: 12, color: t.textDim }}>{secret.description}</div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            padding: "1px 6px",
            borderRadius: 3,
            fontSize: 10,
            fontWeight: 600,
            background: secret.has_value ? t.successSubtle : t.dangerSubtle,
            color: secret.has_value ? t.success : t.danger,
          }}
        >
          {secret.has_value ? "SET" : "EMPTY"}
        </span>
        <span style={{ fontSize: 11, color: t.textDim }}>Created: {created}</span>
      </div>
    </div>
  );
}

function CreateDialog({
  onClose,
  onSave,
  isPending,
  initial,
  prefillValue,
  prefillType,
}: {
  onClose: () => void;
  onSave: (name: string, value: string, description: string) => void;
  isPending: boolean;
  initial?: SecretValueItem;
  prefillValue?: string;
  prefillType?: string;
}) {
  const t = useThemeTokens();
  const suggestedName = prefillType
    ? prefillType.toUpperCase().replace(/\s+/g, "_").replace(/[^A-Z0-9_]/g, "")
    : "";
  const [name, setName] = useState(initial?.name ?? suggestedName);
  const [value, setValue] = useState(prefillValue ?? "");
  const [description, setDescription] = useState(
    initial?.description ?? (prefillType ? `Auto-detected ${prefillType}` : ""),
  );

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px 12px",
    borderRadius: 6,
    border: `1px solid ${t.surfaceOverlay}`,
    background: t.inputBg,
    color: t.text,
    fontSize: 13,
    outline: "none",
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: t.surface,
          borderRadius: 12,
          padding: 24,
          width: "100%",
          maxWidth: 440,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ fontSize: 16, fontWeight: 600, color: t.text }}>
          {initial ? "Edit Secret" : "New Secret"}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: t.textDim }}>Name (env var)</label>
          <input
            style={inputStyle}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="MY_API_KEY"
            autoFocus
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: t.textDim }}>
            Value {initial ? "(leave empty to keep current)" : ""}
          </label>
          <input
            style={inputStyle}
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={initial ? "••••••••" : "secret value"}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: t.textDim }}>Description (optional)</label>
          <input
            style={inputStyle}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this secret is for..."
          />
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: `1px solid ${t.surfaceOverlay}`,
              background: "transparent",
              color: t.text,
              cursor: "pointer",
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <X size={14} />
            Cancel
          </button>
          <button
            onClick={() => onSave(name, value, description)}
            disabled={isPending || !name || (!initial && !value)}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "none",
              background: t.accent,
              color: "#fff",
              cursor: isPending || !name || (!initial && !value) ? "not-allowed" : "pointer",
              opacity: isPending || !name || (!initial && !value) ? 0.5 : 1,
              fontSize: 13,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Check size={14} />
            {isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SecretValuesScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: secrets, isLoading } = useSecretValues();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [showCreate, setShowCreate] = useState(false);
  const [editingSecret, setEditingSecret] = useState<SecretValueItem | null>(null);
  const [prefillValue, setPrefillValue] = useState<string | undefined>();
  const [prefillType, setPrefillType] = useState<string | undefined>();
  const [savedName, setSavedName] = useState<string | null>(null);
  const [returnTo, setReturnTo] = useState<string | null>(null);
  const [originalMessage, setOriginalMessage] = useState<string | undefined>();

  // Check sessionStorage for prefill from SecretWarningDialog
  useState(() => {
    try {
      const raw = sessionStorage.getItem("secret_prefill");
      if (raw) {
        sessionStorage.removeItem("secret_prefill");
        const data = JSON.parse(raw);
        if (data.value) {
          setPrefillValue(data.value);
          setPrefillType(data.type);
          setReturnTo(data.returnTo ?? null);
          setOriginalMessage(data.originalMessage);
          setShowCreate(true);
        }
      }
    } catch { /* ignore */ }
  });

  const [error, setError] = useState<string | null>(null);
  const createMutation = useCreateSecretValue();
  const deleteMutation = useDeleteSecretValue();
  const updateMutation = useUpdateSecretValue(editingSecret?.id);

  const handleCreate = (name: string, value: string, description: string) => {
    setError(null);
    createMutation.mutate(
      { name, value, description },
      {
        onSuccess: () => {
          setShowCreate(false);
          // If created from prefill flow, store return data and redirect back
          if (prefillValue && returnTo) {
            try {
              sessionStorage.setItem("secret_return", JSON.stringify({
                varName: name,
                secretValue: prefillValue,
                originalMessage: originalMessage,
              }));
            } catch { /* ignore */ }
            setPrefillValue(undefined);
            setPrefillType(undefined);
            router.push(returnTo as any);
          } else {
            setPrefillValue(undefined);
            setPrefillType(undefined);
          }
        },
        onError: (err) => setError(err instanceof Error ? err.message : "Failed to create secret"),
      }
    );
  };

  const handleUpdate = (name: string, value: string, description: string) => {
    if (!editingSecret) return;
    setError(null);
    const payload: { name?: string; value?: string; description?: string } = {};
    if (name !== editingSecret.name) payload.name = name;
    if (value) payload.value = value;
    if (description !== editingSecret.description) payload.description = description;
    updateMutation.mutate(payload, {
      onSuccess: () => setEditingSecret(null),
      onError: (err) => setError(err instanceof Error ? err.message : "Failed to update secret"),
    });
  };

  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const handleDelete = (id: string) => {
    setDeleteConfirm(id);
  };

  const confirmDelete = () => {
    if (!deleteConfirm) return;
    setError(null);
    deleteMutation.mutate(deleteConfirm, {
      onSuccess: () => setDeleteConfirm(null),
      onError: (err) => {
        setDeleteConfirm(null);
        setError(err instanceof Error ? err.message : "Failed to delete secret");
      },
    });
  };

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Secret Values"
        right={
          <button
            onClick={() => setShowCreate(true)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              borderRadius: 6,
              background: t.accent,
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
              color: "#fff",
            }}
          >
            <Plus size={14} /> New Secret
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
        <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
          <div
            style={{
              padding: "12px 16px",
              marginBottom: 16,
              borderRadius: 8,
              background: t.accentSubtle,
              fontSize: 12,
              color: t.textDim,
              lineHeight: 1.5,
            }}
          >
            Secret values are encrypted at rest and injected as environment variables into workspace
            containers. Their values are automatically redacted from tool results and LLM output.
            <br /><br />
            <strong>When to use Secrets vs. workspace env vars:</strong> Use Secrets for sensitive
            values (API keys, tokens, passwords) that should never appear in tool results or
            conversation history. Use the env vars in{" "}
            <a href="/admin/bots" style={{ color: t.accent }}>Bot</a> or{" "}
            <a href="/admin/workspaces" style={{ color: t.accent }}>Workspace</a> Docker settings
            for non-sensitive configuration (feature flags, URLs, runtime options).
          </div>

          {isLoading ? (
            <View className="items-center justify-center py-20">
              <ActivityIndicator color={t.accent} />
            </View>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(380px, 1fr))" : "1fr",
                gap: 12,
              }}
            >
              {secrets?.map((s) => (
                <SecretCard
                  key={s.id}
                  secret={s}
                  onDelete={() => handleDelete(s.id)}
                  onEdit={() => setEditingSecret(s)}
                />
              ))}
              {secrets?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: t.textDim,
                    fontSize: 14,
                  }}
                >
                  No secrets yet. Create one to store encrypted environment variables.
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>

      {error && (
        <div
          style={{
            position: "fixed",
            bottom: 20,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 20px",
            borderRadius: 8,
            background: t.danger,
            color: "#fff",
            fontSize: 13,
            zIndex: 1001,
            cursor: "pointer",
            maxWidth: 400,
          }}
          onClick={() => setError(null)}
        >
          {error}
        </div>
      )}
      {savedName && (
        <div
          style={{
            position: "fixed",
            bottom: 20,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "12px 20px",
            borderRadius: 8,
            background: t.successSubtle,
            border: `1px solid ${t.successBorder}`,
            fontSize: 13,
            color: t.success,
            zIndex: 1001,
            maxWidth: 460,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>
              Secret saved as <code style={{ background: t.surfaceOverlay, padding: "1px 4px", borderRadius: 3 }}>{savedName}</code>
            </div>
            <div style={{ fontSize: 11, color: t.textDim }}>
              Tell the bot to use <code style={{ background: t.surfaceOverlay, padding: "1px 4px", borderRadius: 3 }}>${"{" + savedName + "}"}</code> instead of pasting the value.
            </div>
          </div>
          {returnTo && (
            <button
              onClick={() => { setSavedName(null); router.push(returnTo as any); }}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: `1px solid ${t.successBorder}`,
                background: "transparent",
                color: t.success,
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: 4,
                whiteSpace: "nowrap",
              }}
            >
              <ArrowLeft size={12} />
              Back to chat
            </button>
          )}
        </div>
      )}
      {deleteConfirm && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            style={{
              background: t.surface,
              borderRadius: 12,
              padding: 24,
              maxWidth: 360,
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontSize: 15, fontWeight: 600, color: t.text }}>
              Delete this secret?
            </div>
            <div style={{ fontSize: 13, color: t.textDim }}>
              This cannot be undone. The secret will be removed from all workspace containers.
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => setDeleteConfirm(null)}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: `1px solid ${t.surfaceOverlay}`,
                  background: "transparent",
                  color: t.text,
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleteMutation.isPending}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: "none",
                  background: t.danger,
                  color: "#fff",
                  cursor: deleteMutation.isPending ? "not-allowed" : "pointer",
                  opacity: deleteMutation.isPending ? 0.5 : 1,
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
      {showCreate && (
        <CreateDialog
          onClose={() => {
            setShowCreate(false);
            setPrefillValue(undefined);
            setPrefillType(undefined);
          }}
          onSave={handleCreate}
          isPending={createMutation.isPending}
          prefillValue={prefillValue}
          prefillType={prefillType}
        />
      )}
      {editingSecret && (
        <CreateDialog
          onClose={() => setEditingSecret(null)}
          onSave={handleUpdate}
          isPending={updateMutation.isPending}
          initial={editingSecret}
        />
      )}
    </View>
  );
}
