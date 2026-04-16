import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useEffect } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  Shield,
  ShieldOff,
  Pencil,
  X,
  Check,
  UserPlus,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";

interface UserRecord {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  integration_config: Record<string, any>;
  is_admin: boolean;
  is_active: boolean;
  auth_method: string;
  created_at: string;
}

interface IntegrationField {
  key: string;
  label: string;
  description: string;
}

interface IntegrationInfo {
  id: string;
  name: string;
  fields: IntegrationField[];
}

function useUsers() {
  return useQuery({
    queryKey: ["admin-users"],
    queryFn: () => apiFetch<UserRecord[]>("/api/v1/admin/users"),
  });
}

function useIntegrations() {
  return useQuery({
    queryKey: ["auth-integrations"],
    queryFn: () => apiFetch<IntegrationInfo[]>("/auth/integrations"),
  });
}

function useIdentitySuggestions(integration: string, enabled: boolean) {
  return useQuery({
    queryKey: ["identity-suggestions", integration],
    queryFn: () => apiFetch<string[]>(`/api/v1/admin/users/identity-suggestions/${integration}`),
    enabled,
  });
}

// ---------------------------------------------------------------------------
// Integration fields editor with suggestions for user_id fields
// ---------------------------------------------------------------------------
function IntegrationFieldsEditor({
  user,
  integrations,
  values,
  onChange,
}: {
  user: UserRecord;
  integrations: IntegrationInfo[];
  values: Record<string, Record<string, string>>;
  onChange: (integrationId: string, key: string, value: string) => void;
}) {
  if (!integrations.length) return null;

  return (
    <>
      {integrations.map((integration) => (
        <div key={integration.id} className="flex flex-col gap-2">
          <span className="text-text-dim text-xs font-medium">{integration.name}</span>
          {integration.fields.map((field) => (
            <IntegrationFieldInput
              key={field.key}
              integration={integration.id}
              field={field}
              value={values[integration.id]?.[field.key] || ""}
              onChange={(v) => onChange(integration.id, field.key, v)}
            />
          ))}
        </div>
      ))}
    </>
  );
}

function IntegrationFieldInput({
  integration,
  field,
  value,
  onChange,
}: {
  integration: string;
  field: IntegrationField;
  value: string;
  onChange: (v: string) => void;
}) {
  const isUserIdField = field.key === "user_id";
  const { data: suggestions } = useIdentitySuggestions(integration, isUserIdField);
  const [showSuggestions, setShowSuggestions] = useState(false);

  return (
    <div className="flex flex-col gap-1">
      <span className="text-text-dim text-[11px]">{field.label}</span>
      <div>
        <input
          className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            if (isUserIdField) setShowSuggestions(true);
          }}
          onFocus={() => { if (isUserIdField && suggestions?.length) setShowSuggestions(true); }}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
          placeholder={field.description}
        />
        {isUserIdField && showSuggestions && suggestions && suggestions.length > 0 && (
          <div className="bg-surface-raised border border-surface-border rounded mt-1 overflow-hidden" style={{ maxHeight: 150 }}>
            {suggestions
              .filter((s) => !value || s.toLowerCase().includes(value.toLowerCase()))
              .slice(0, 8)
              .map((suggestion) => (
                <button type="button"
                  key={suggestion}
                  onClick={() => {
                    onChange(suggestion);
                    setShowSuggestions(false);
                  }}
                  className="px-3 py-2 hover:bg-surface-overlay"
                >
                  <span className="text-text text-sm">{suggestion}</span>
                </button>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserRow
// ---------------------------------------------------------------------------
function UserRow({ user, onRefresh }: { user: UserRecord; onRefresh: () => void }) {
  const t = useThemeTokens();
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || "");
  const { data: integrations } = useIntegrations();
  const [integrationValues, setIntegrationValues] = useState<Record<string, Record<string, string>>>({});

  // Initialize integration values from user config
  useEffect(() => {
    if (!integrations) return;
    const init: Record<string, Record<string, string>> = {};
    for (const integration of integrations) {
      init[integration.id] = {};
      for (const field of integration.fields) {
        init[integration.id][field.key] =
          user.integration_config?.[integration.id]?.[field.key] || "";
      }
    }
    setIntegrationValues(init);
  }, [integrations, user.integration_config]);

  const updateIntegrationField = (integrationId: string, key: string, value: string) => {
    setIntegrationValues((prev) => ({
      ...prev,
      [integrationId]: { ...prev[integrationId], [key]: value },
    }));
  };

  const updateMutation = useMutation({
    mutationFn: (body: Record<string, any>) =>
      apiFetch(`/api/v1/admin/users/${user.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      setEditing(false);
      onRefresh();
    },
  });

  const handleSave = () => {
    // Merge integration values into config
    const config = { ...(user.integration_config || {}) };
    for (const [integrationId, fields] of Object.entries(integrationValues)) {
      const cleaned: Record<string, string> = {};
      for (const [k, v] of Object.entries(fields)) {
        if (v) cleaned[k] = v;
      }
      if (Object.keys(cleaned).length > 0) {
        config[integrationId] = { ...(config[integrationId] || {}), ...cleaned };
      } else {
        // Clear empty integration config
        delete config[integrationId];
      }
    }

    updateMutation.mutate({
      display_name: displayName,
      avatar_url: avatarUrl || null,
      integration_config: config,
    });
  };

  const toggleAdmin = () => {
    updateMutation.mutate({ is_admin: !user.is_admin });
  };

  if (editing) {
    return (
      <div className="flex flex-col bg-surface-raised border border-accent/30 rounded-lg p-4 gap-3">
        <div className="flex flex-row items-center justify-between">
          <span className="text-text font-medium">{user.email}</span>
          <div className="flex flex-row gap-2">
            <button type="button" onClick={handleSave} className="p-1.5 rounded bg-accent/20">
              <Check size={14} color={t.accent} />
            </button>
            <button type="button" onClick={() => setEditing(false)} className="p-1.5 rounded bg-surface-overlay">
              <X size={14} color={t.textMuted} />
            </button>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-text-dim text-xs">Display Name</span>
          <input
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-text-dim text-xs">Avatar URL</span>
          <input
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={avatarUrl}
            onChange={(e) => setAvatarUrl(e.target.value)}
            placeholder="https://..."
          />
        </div>
        {integrations && (
          <IntegrationFieldsEditor
            user={user}
            integrations={integrations}
            values={integrationValues}
            onChange={updateIntegrationField}
          />
        )}
      </div>
    );
  }

  return (
    <button type="button" className="flex bg-surface-raised border border-surface-border rounded-lg p-4 flex-row items-center gap-4 hover:border-accent/50">
      <div className="flex w-10 h-10 rounded-full bg-accent/20 items-center justify-center overflow-hidden">
        {user.avatar_url ? (
          <img src={user.avatar_url} style={{ width: 40, height: 40 }} alt="" />
        ) : (
          <Users size={20} color={t.accent} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-row items-center gap-2">
          <span className="text-text font-medium">{user.display_name}</span>
          {user.is_admin && (
            <div className="bg-amber-500/20 px-1.5 py-0.5 rounded">
              <span className="text-amber-400 text-[10px] font-medium">Admin</span>
            </div>
          )}
          <div className="bg-surface-overlay px-1.5 py-0.5 rounded">
            <span className="text-text-dim text-[10px]">{user.auth_method}</span>
          </div>
          {!user.is_active && (
            <div className="bg-red-500/20 px-1.5 py-0.5 rounded">
              <span className="text-red-400 text-[10px]">Inactive</span>
            </div>
          )}
        </div>
        <span className="text-text-muted text-xs mt-0.5">{user.email}</span>
      </div>
      <div className="flex flex-row gap-2">
        <button type="button" onClick={() => setEditing(true)} className="p-2 rounded hover:bg-surface-overlay">
          <Pencil size={14} color={t.textMuted} />
        </button>
        <button type="button" onClick={toggleAdmin} className="p-2 rounded hover:bg-surface-overlay">
          {user.is_admin ? (
            <ShieldOff size={14} color="#f59e0b" />
          ) : (
            <Shield size={14} color={t.textMuted} />
          )}
        </button>
      </div>
    </button>
  );
}

export default function UsersScreen() {
  const t = useThemeTokens();
  const { data, isLoading, refetch } = useUsers();
  const { refreshing, onRefresh } = usePageRefresh();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      apiFetch("/api/v1/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email: newEmail,
          display_name: newName || newEmail.split("@")[0],
          password: newPassword,
        }),
      }),
    onSuccess: () => {
      setShowCreate(false);
      setNewEmail("");
      setNewName("");
      setNewPassword("");
      setCreateError(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (e) => {
      setCreateError(e instanceof Error ? e.message : "Failed to create user");
    },
  });

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Users"
        subtitle={`${data?.length ?? 0} users`}
        right={
          <button type="button"
            onClick={() => setShowCreate(!showCreate)}
            className="flex flex-row items-center gap-2 bg-accent px-4 py-2 rounded-lg"
          >
            <UserPlus size={14} color="#fff" />
            <span className="text-white text-sm font-medium">New User</span>
          </button>
        }
      />

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1 p-4">
          <div className="flex flex-col gap-2 max-w-3xl">
            {/* Create form */}
            {showCreate && (
              <div className="flex flex-col bg-surface-raised border border-accent/30 rounded-lg p-4 gap-3 mb-2">
                <span className="text-text font-medium">Create Local User</span>
                <input
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  autoCapitalize="none"
                  type="email"
                />
                <input
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Display name (optional)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <input
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  type="password"
                />
                {createError && (
                  <span className="text-red-400 text-xs">{createError}</span>
                )}
                <button type="button"
                  onClick={() => createMutation.mutate()}
                  disabled={createMutation.isPending}
                  className="flex flex-col bg-accent rounded px-4 py-2 items-center"
                >
                  <span className="text-white text-sm font-medium">Create</span>
                </button>
              </div>
            )}

            {/* User list */}
            {data?.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                onRefresh={() =>
                  queryClient.invalidateQueries({ queryKey: ["admin-users"] })
                }
              />
            ))}
          </div>
        </RefreshableScrollView>
      )}
    </div>
  );
}
