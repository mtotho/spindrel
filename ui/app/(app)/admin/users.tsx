import { useState, useEffect } from "react";
import {
  View,
  Text,
  Pressable,
  ActivityIndicator,
  TextInput,
  Image,
} from "react-native";
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
import { MobileHeader } from "@/src/components/layout/MobileHeader";

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
        <View key={integration.id} className="gap-2">
          <Text className="text-text-dim text-xs font-medium">{integration.name}</Text>
          {integration.fields.map((field) => (
            <IntegrationFieldInput
              key={field.key}
              integration={integration.id}
              field={field}
              value={values[integration.id]?.[field.key] || ""}
              onChange={(v) => onChange(integration.id, field.key, v)}
            />
          ))}
        </View>
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
    <View className="gap-1">
      <Text className="text-text-dim text-[11px]">{field.label}</Text>
      <View>
        <TextInput
          className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
          value={value}
          onChangeText={(v) => {
            onChange(v);
            if (isUserIdField) setShowSuggestions(true);
          }}
          onFocus={() => { if (isUserIdField && suggestions?.length) setShowSuggestions(true); }}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
          placeholder={field.description}
          placeholderTextColor="#666666"
        />
        {isUserIdField && showSuggestions && suggestions && suggestions.length > 0 && (
          <View className="bg-surface-raised border border-surface-border rounded mt-1 overflow-hidden" style={{ maxHeight: 150 }}>
            {suggestions
              .filter((s) => !value || s.toLowerCase().includes(value.toLowerCase()))
              .slice(0, 8)
              .map((suggestion) => (
                <Pressable
                  key={suggestion}
                  onPress={() => {
                    onChange(suggestion);
                    setShowSuggestions(false);
                  }}
                  className="px-3 py-2 hover:bg-surface-overlay"
                >
                  <Text className="text-text text-sm">{suggestion}</Text>
                </Pressable>
              ))}
          </View>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// UserRow
// ---------------------------------------------------------------------------
function UserRow({ user, onRefresh }: { user: UserRecord; onRefresh: () => void }) {
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
      <View className="bg-surface-raised border border-accent/30 rounded-lg p-4 gap-3">
        <View className="flex-row items-center justify-between">
          <Text className="text-text font-medium">{user.email}</Text>
          <View className="flex-row gap-2">
            <Pressable onPress={handleSave} className="p-1.5 rounded bg-accent/20">
              <Check size={14} color="#3b82f6" />
            </Pressable>
            <Pressable onPress={() => setEditing(false)} className="p-1.5 rounded bg-surface-overlay">
              <X size={14} color="#999999" />
            </Pressable>
          </View>
        </View>
        <View className="gap-2">
          <Text className="text-text-dim text-xs">Display Name</Text>
          <TextInput
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={displayName}
            onChangeText={setDisplayName}
          />
        </View>
        <View className="gap-2">
          <Text className="text-text-dim text-xs">Avatar URL</Text>
          <TextInput
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={avatarUrl}
            onChangeText={setAvatarUrl}
            placeholder="https://..."
            placeholderTextColor="#666666"
          />
        </View>
        {integrations && (
          <IntegrationFieldsEditor
            user={user}
            integrations={integrations}
            values={integrationValues}
            onChange={updateIntegrationField}
          />
        )}
      </View>
    );
  }

  return (
    <Pressable className="bg-surface-raised border border-surface-border rounded-lg p-4 flex-row items-center gap-4 hover:border-accent/50">
      <View className="w-10 h-10 rounded-full bg-accent/20 items-center justify-center overflow-hidden">
        {user.avatar_url ? (
          <Image source={{ uri: user.avatar_url }} style={{ width: 40, height: 40 }} />
        ) : (
          <Users size={20} color="#3b82f6" />
        )}
      </View>
      <View className="flex-1 min-w-0">
        <View className="flex-row items-center gap-2">
          <Text className="text-text font-medium">{user.display_name}</Text>
          {user.is_admin && (
            <View className="bg-amber-500/20 px-1.5 py-0.5 rounded">
              <Text className="text-amber-400 text-[10px] font-medium">Admin</Text>
            </View>
          )}
          <View className="bg-surface-overlay px-1.5 py-0.5 rounded">
            <Text className="text-text-dim text-[10px]">{user.auth_method}</Text>
          </View>
          {!user.is_active && (
            <View className="bg-red-500/20 px-1.5 py-0.5 rounded">
              <Text className="text-red-400 text-[10px]">Inactive</Text>
            </View>
          )}
        </View>
        <Text className="text-text-muted text-xs mt-0.5">{user.email}</Text>
      </View>
      <View className="flex-row gap-2">
        <Pressable onPress={() => setEditing(true)} className="p-2 rounded hover:bg-surface-overlay">
          <Pencil size={14} color="#999999" />
        </Pressable>
        <Pressable onPress={toggleAdmin} className="p-2 rounded hover:bg-surface-overlay">
          {user.is_admin ? (
            <ShieldOff size={14} color="#f59e0b" />
          ) : (
            <Shield size={14} color="#999999" />
          )}
        </Pressable>
      </View>
    </Pressable>
  );
}

export default function UsersScreen() {
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
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Users"
        subtitle={`${data?.length ?? 0} users`}
        right={
          <Pressable
            onPress={() => setShowCreate(!showCreate)}
            className="flex-row items-center gap-2 bg-accent px-4 py-2 rounded-lg"
          >
            <UserPlus size={14} color="#fff" />
            <Text className="text-white text-sm font-medium">New User</Text>
          </Pressable>
        }
      />

      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1 p-4">
          <View className="gap-2 max-w-3xl">
            {/* Create form */}
            {showCreate && (
              <View className="bg-surface-raised border border-accent/30 rounded-lg p-4 gap-3 mb-2">
                <Text className="text-text font-medium">Create Local User</Text>
                <TextInput
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Email"
                  placeholderTextColor="#666666"
                  value={newEmail}
                  onChangeText={setNewEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                />
                <TextInput
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Display name (optional)"
                  placeholderTextColor="#666666"
                  value={newName}
                  onChangeText={setNewName}
                />
                <TextInput
                  className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                  placeholder="Password"
                  placeholderTextColor="#666666"
                  value={newPassword}
                  onChangeText={setNewPassword}
                  secureTextEntry
                />
                {createError && (
                  <Text className="text-red-400 text-xs">{createError}</Text>
                )}
                <Pressable
                  onPress={() => createMutation.mutate()}
                  disabled={createMutation.isPending}
                  className="bg-accent rounded px-4 py-2 items-center"
                >
                  <Text className="text-white text-sm font-medium">Create</Text>
                </Pressable>
              </View>
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
          </View>
        </RefreshableScrollView>
      )}
    </View>
  );
}
