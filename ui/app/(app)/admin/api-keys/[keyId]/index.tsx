import { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { Trash2, Copy, Check, AlertTriangle, Info } from "lucide-react";
import { writeToClipboard } from "@/src/utils/clipboard";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  useApiKey,
  useApiKeyScopes,
  useCreateApiKey,
  useUpdateApiKey,
  useDeleteApiKey,
  ScopePreset,
} from "@/src/api/hooks/useApiKeys";
import {
  Section,
  FormRow,
  TextInput,
  Toggle,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function ScopeCheckboxGroup({
  groups,
  descriptions,
  selected,
  onChange,
}: {
  groups: Record<string, { description: string; scopes: string[] }>;
  descriptions?: Record<string, string>;
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

  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {Object.entries(groups).map(([group, groupInfo]) => (
        <div key={group}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: t.textMuted,
              marginBottom: 2,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            {group}
          </div>
          <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>
            {groupInfo.description}
          </div>
          <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {groupInfo.scopes.map((scope) => {
              const checked = set.has(scope);
              const isAdmin = scope === "admin";
              const desc = descriptions?.[scope];
              return (
                <button
                  key={scope}
                  onClick={() => toggle(scope)}
                  title={desc}
                  style={{
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 5,
                    border: checked
                      ? isAdmin
                        ? `1px solid ${t.dangerBorder}`
                        : `1px solid ${t.accentBorder}`
                      : `1px solid ${t.surfaceBorder}`,
                    background: checked
                      ? isAdmin
                        ? t.dangerSubtle
                        : t.accentSubtle
                      : "transparent",
                    cursor: "pointer",
                    fontSize: 12,
                    color: checked
                      ? isAdmin
                        ? t.danger
                        : t.accent
                      : t.textDim,
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
                        : `1px solid ${t.surfaceBorder}`,
                      background: checked
                        ? isAdmin
                          ? t.danger
                          : t.accent
                        : "transparent",
                      display: "flex", flexDirection: "row",
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
  const t = useThemeTokens();
  const { keyId } = useParams<{ keyId: string }>();
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

  // Preset state (create flow only)
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const activePresetData: ScopePreset | null =
    activePreset && scopeGroups?.presets?.[activePreset]
      ? scopeGroups.presets[activePreset]
      : null;

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

  const handlePreset = useCallback(
    (key: string | null) => {
      if (!key || !scopeGroups?.presets?.[key]) {
        setActivePreset(null);
        setScopes([]);
        if (!name.trim()) setName("");
        return;
      }
      const preset = scopeGroups.presets[key];
      setActivePreset(key);
      setScopes([...preset.scopes]);
      if (!name.trim() || activePreset) {
        setName(preset.name);
      }
    },
    [scopeGroups, name, activePreset],
  );

  const handleCopy = useCallback(async () => {
    if (createdKey) {
      await writeToClipboard(createdKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [createdKey]);

  if (!isNew && isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  const hasAdminScope = scopes.includes("admin");

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="API Keys"
        backTo="/admin/api-keys"
        title={isNew ? "New API Key" : "Edit API Key"}
        right={
          <>
            {!isNew && (
              <button
                onClick={handleDelete}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  padding: "6px 12px",
                  borderRadius: 6,
                  background: t.dangerSubtle,
                  border: `1px solid ${t.dangerBorder}`,
                  cursor: "pointer",
                  fontSize: 12,
                  color: t.dangerMuted,
                }}
              >
                <Trash2 size={13} /> Delete
              </button>
            )}
            <button
              onClick={createdKey ? goBack : handleSave}
              disabled={!createdKey && (isSaving || !name.trim())}
              style={{
                padding: "6px 18px",
                borderRadius: 6,
                background:
                  !createdKey && (isSaving || !name.trim()) ? t.surfaceBorder : t.accent,
                border: "none",
                cursor: !createdKey && (isSaving || !name.trim()) ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                color: "#fff",
                opacity: !createdKey && (isSaving || !name.trim()) ? 0.5 : 1,
              }}
            >
              {isSaving ? "Saving..." : createdKey ? "Done" : "Save"}
            </button>
          </>
        }
      />

      <div style={{ flex: 1, overflow: "auto" }}>
        <div
          style={{ padding: 20, maxWidth: 800, margin: "0 auto", width: "100%" }}
        >
          {/* Key reveal (create only) */}
          {createdKey && (
            <div
              style={{
                padding: 16,
                borderRadius: 10,
                background: t.successSubtle,
                border: `1px solid ${t.successBorder}`,
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <AlertTriangle size={14} color={t.warningMuted} />
                <span
                  style={{ fontSize: 13, fontWeight: 600, color: t.warningMuted }}
                >
                  Save this key now. It won't be shown again.
                </span>
              </div>
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <code
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: t.surfaceRaised,
                    fontSize: 12,
                    color: t.success,
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
                    background: t.surfaceOverlay,
                    border: `1px solid ${t.surfaceBorder}`,
                    cursor: "pointer",
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: copied ? t.success : t.textMuted,
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
                      color: t.textMuted,
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

          {/* Preset picker — only on create */}
          {isNew && scopeGroups?.presets && (
            <Section title="Quick Start">
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  flexWrap: "wrap",
                  gap: 8,
                }}
              >
                {Object.entries(scopeGroups.presets).map(
                  ([key, preset]) => {
                    const active = activePreset === key;
                    return (
                      <button
                        key={key}
                        onClick={() => handlePreset(active ? null : key)}
                        style={{
                          padding: "8px 14px",
                          borderRadius: 8,
                          border: active
                            ? `1px solid ${t.accent}`
                            : `1px solid ${t.surfaceBorder}`,
                          background: active
                            ? t.accentSubtle
                            : t.surfaceOverlay,
                          cursor: "pointer",
                          fontSize: 13,
                          fontWeight: active ? 600 : 400,
                          color: active ? t.accent : t.textMuted,
                        }}
                      >
                        <div>{preset.name}</div>
                        <div
                          style={{
                            fontSize: 10,
                            color: t.textDim,
                            marginTop: 2,
                          }}
                        >
                          {preset.description}
                        </div>
                      </button>
                    );
                  },
                )}
                <button
                  onClick={() => handlePreset(null)}
                  style={{
                    padding: "8px 14px",
                    borderRadius: 8,
                    border:
                      activePreset === null
                        ? `1px solid ${t.accent}`
                        : `1px solid ${t.surfaceBorder}`,
                    background:
                      activePreset === null
                        ? t.accentSubtle
                        : t.surfaceOverlay,
                    cursor: "pointer",
                    fontSize: 13,
                    fontWeight: activePreset === null ? 600 : 400,
                    color:
                      activePreset === null ? t.accent : t.textMuted,
                  }}
                >
                  <div>Custom</div>
                  <div
                    style={{
                      fontSize: 10,
                      color: t.textDim,
                      marginTop: 2,
                    }}
                  >
                    Pick scopes manually
                  </div>
                </button>
              </div>
            </Section>
          )}

          {/* Instructions banner for active preset */}
          {activePresetData && (
            <div
              style={{
                padding: 14,
                borderRadius: 10,
                background: t.accentSubtle,
                border: `1px solid ${t.accentBorder}`,
                marginBottom: 16,
              }}
            >
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  marginBottom: 8,
                  fontSize: 12,
                  fontWeight: 600,
                  color: t.accent,
                }}
              >
                <Info size={13} />
                Setup Instructions
              </div>
              <pre
                style={{
                  fontSize: 12,
                  color: t.textMuted,
                  whiteSpace: "pre-wrap",
                  margin: 0,
                  fontFamily: "monospace",
                  lineHeight: 1.5,
                }}
              >
                {activePresetData.instructions}
              </pre>
            </div>
          )}

          <Section title="Scopes">
            {hasAdminScope && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: t.dangerSubtle,
                  border: `1px solid ${t.dangerBorder}`,
                  fontSize: 12,
                  color: t.danger,
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
              <Spinner color={t.accent} />
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
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {new Date(apiKey.created_at).toLocaleString()}
                </span>
              </FormRow>
              <FormRow label="Last used">
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {apiKey.last_used_at
                    ? new Date(apiKey.last_used_at).toLocaleString()
                    : "Never"}
                </span>
              </FormRow>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
