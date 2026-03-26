import { useState, useEffect } from "react";
import {
  View,
  Text,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Image,
} from "react-native";
import { useQuery, useMutation } from "@tanstack/react-query";
import { User, Link2, Lock, Check, X, Eye, EyeOff } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useAuthStore, AuthUser } from "@/src/stores/auth";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

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

function useIntegrations() {
  return useQuery({
    queryKey: ["auth-integrations"],
    queryFn: () => apiFetch<IntegrationInfo[]>("/auth/integrations"),
  });
}

// ---------------------------------------------------------------------------
// Account Section
// ---------------------------------------------------------------------------

function AccountSection({ user }: { user: AuthUser }) {
  const updateUser = useAuthStore((s) => s.updateUser);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || "");
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const changed =
      displayName !== user.display_name ||
      (avatarUrl || null) !== (user.avatar_url || null);
    setDirty(changed);
    setSaved(false);
  }, [displayName, avatarUrl, user]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiFetch<AuthUser>("/auth/me", {
        method: "PUT",
        body: JSON.stringify({
          display_name: displayName,
          avatar_url: avatarUrl || null,
        }),
      }),
    onSuccess: (data) => {
      updateUser(data);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <View className="gap-4">
      <Text className="text-text font-semibold text-base">Account</Text>

      {/* Avatar preview */}
      <View className="flex-row items-center gap-4">
        <View className="w-16 h-16 rounded-full bg-accent/20 items-center justify-center overflow-hidden">
          {avatarUrl ? (
            <Image source={{ uri: avatarUrl }} style={{ width: 64, height: 64 }} />
          ) : (
            <User size={28} color="#3b82f6" />
          )}
        </View>
        <View>
          <Text className="text-text font-medium">{user.display_name}</Text>
          <Text className="text-text-muted text-xs">{user.email}</Text>
          <View className="flex-row gap-2 mt-1">
            <View className="bg-surface-overlay px-1.5 py-0.5 rounded">
              <Text className="text-text-dim text-[10px]">{user.auth_method}</Text>
            </View>
            {user.is_admin && (
              <View className="bg-amber-500/20 px-1.5 py-0.5 rounded">
                <Text className="text-amber-400 text-[10px] font-medium">Admin</Text>
              </View>
            )}
          </View>
        </View>
      </View>

      {/* Fields */}
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

      {dirty && (
        <Pressable
          onPress={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
        >
          {saveMutation.isPending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Check size={14} color="#fff" />
          )}
          <Text className="text-white text-sm font-medium">Save</Text>
        </Pressable>
      )}
      {saved && (
        <Text className="text-green-400 text-xs">Saved</Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Integrations Section
// ---------------------------------------------------------------------------

function IntegrationsSection({ user }: { user: AuthUser }) {
  const updateUser = useAuthStore((s) => s.updateUser);
  const { data: integrations, isLoading } = useIntegrations();
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  // Initialize from user.integration_config
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
    setValues(init);
    setDirty(false);
  }, [integrations, user.integration_config]);

  const updateField = (integrationId: string, key: string, value: string) => {
    setValues((prev) => ({
      ...prev,
      [integrationId]: { ...prev[integrationId], [key]: value },
    }));
    setDirty(true);
    setSaved(false);
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      // Merge values into integration_config, preserving other keys
      const config = { ...(user.integration_config || {}) };
      for (const [integrationId, fields] of Object.entries(values)) {
        const cleaned: Record<string, string> = {};
        for (const [k, v] of Object.entries(fields)) {
          if (v) cleaned[k] = v;
        }
        if (Object.keys(cleaned).length > 0) {
          config[integrationId] = { ...(config[integrationId] || {}), ...cleaned };
        }
      }
      return apiFetch<AuthUser>("/auth/me", {
        method: "PUT",
        body: JSON.stringify({ integration_config: config }),
      });
    },
    onSuccess: (data) => {
      updateUser(data);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (isLoading) {
    return (
      <View className="gap-4">
        <Text className="text-text font-semibold text-base">Integrations</Text>
        <ActivityIndicator size="small" color="#3b82f6" />
      </View>
    );
  }

  if (!integrations?.length) {
    return (
      <View className="gap-4">
        <Text className="text-text font-semibold text-base">Integrations</Text>
        <Text className="text-text-muted text-sm">No integrations configured.</Text>
      </View>
    );
  }

  return (
    <View className="gap-4">
      <View className="flex-row items-center gap-2">
        <Link2 size={16} color="#9ca3af" />
        <Text className="text-text font-semibold text-base">Integrations</Text>
      </View>
      <Text className="text-text-muted text-xs">
        Link your accounts so the server can associate integration messages with your user.
      </Text>

      {integrations.map((integration) => (
        <View
          key={integration.id}
          className="bg-surface-raised border border-surface-border rounded-lg p-4 gap-3"
        >
          <Text className="text-text font-medium">{integration.name}</Text>
          {integration.fields.map((field) => (
            <View key={field.key} className="gap-1">
              <Text className="text-text-dim text-xs">{field.label}</Text>
              <TextInput
                className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                value={values[integration.id]?.[field.key] || ""}
                onChangeText={(v) => updateField(integration.id, field.key, v)}
                placeholder={field.description}
                placeholderTextColor="#666666"
              />
            </View>
          ))}
        </View>
      ))}

      {dirty && (
        <Pressable
          onPress={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
        >
          {saveMutation.isPending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Check size={14} color="#fff" />
          )}
          <Text className="text-white text-sm font-medium">Save</Text>
        </Pressable>
      )}
      {saved && (
        <Text className="text-green-400 text-xs">Saved</Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Security Section (password change for local auth)
// ---------------------------------------------------------------------------

function SecuritySection({ user }: { user: AuthUser }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const changeMutation = useMutation({
    mutationFn: () =>
      apiFetch("/auth/me/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setError(null);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Failed to change password");
    },
  });

  const handleSubmit = () => {
    setError(null);
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    changeMutation.mutate();
  };

  if (user.auth_method !== "local") {
    return (
      <View className="gap-4">
        <View className="flex-row items-center gap-2">
          <Lock size={16} color="#9ca3af" />
          <Text className="text-text font-semibold text-base">Security</Text>
        </View>
        <Text className="text-text-muted text-sm">
          Password management is not available for {user.auth_method} authentication.
        </Text>
      </View>
    );
  }

  return (
    <View className="gap-4">
      <View className="flex-row items-center gap-2">
        <Lock size={16} color="#9ca3af" />
        <Text className="text-text font-semibold text-base">Security</Text>
      </View>

      <View className="bg-surface-raised border border-surface-border rounded-lg p-4 gap-3">
        <Text className="text-text font-medium text-sm">Change Password</Text>

        <View className="gap-1">
          <Text className="text-text-dim text-xs">Current Password</Text>
          <View className="flex-row items-center">
            <TextInput
              className="flex-1 bg-surface border border-surface-border rounded-l px-3 py-2 text-text text-sm"
              value={currentPassword}
              onChangeText={setCurrentPassword}
              secureTextEntry={!showCurrent}
            />
            <Pressable
              onPress={() => setShowCurrent(!showCurrent)}
              className="bg-surface border border-l-0 border-surface-border rounded-r px-3 py-2"
            >
              {showCurrent ? (
                <EyeOff size={14} color="#999" />
              ) : (
                <Eye size={14} color="#999" />
              )}
            </Pressable>
          </View>
        </View>

        <View className="gap-1">
          <Text className="text-text-dim text-xs">New Password</Text>
          <View className="flex-row items-center">
            <TextInput
              className="flex-1 bg-surface border border-surface-border rounded-l px-3 py-2 text-text text-sm"
              value={newPassword}
              onChangeText={setNewPassword}
              secureTextEntry={!showNew}
            />
            <Pressable
              onPress={() => setShowNew(!showNew)}
              className="bg-surface border border-l-0 border-surface-border rounded-r px-3 py-2"
            >
              {showNew ? (
                <EyeOff size={14} color="#999" />
              ) : (
                <Eye size={14} color="#999" />
              )}
            </Pressable>
          </View>
        </View>

        <View className="gap-1">
          <Text className="text-text-dim text-xs">Confirm New Password</Text>
          <TextInput
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            secureTextEntry={!showNew}
          />
        </View>

        {error && <Text className="text-red-400 text-xs">{error}</Text>}
        {success && <Text className="text-green-400 text-xs">Password changed successfully</Text>}

        <Pressable
          onPress={handleSubmit}
          disabled={changeMutation.isPending || !currentPassword || !newPassword}
          className="bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
          style={{
            opacity: !currentPassword || !newPassword ? 0.5 : 1,
          }}
        >
          {changeMutation.isPending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Lock size={14} color="#fff" />
          )}
          <Text className="text-white text-sm font-medium">Change Password</Text>
        </Pressable>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Profile Screen
// ---------------------------------------------------------------------------

export default function ProfileScreen() {
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  if (!user) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <Text className="text-text-muted">Not logged in</Text>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Profile" />

      <ScrollView className="flex-1 p-6">
        <View className="gap-8 max-w-lg">
          <AccountSection user={user} />

          <View className="h-px bg-surface-border" />

          <IntegrationsSection user={user} />

          <View className="h-px bg-surface-border" />

          <SecuritySection user={user} />

          <View className="h-px bg-surface-border" />

          {/* Sign out */}
          <Pressable
            onPress={clear}
            className="bg-red-500/10 border border-red-500/30 rounded px-4 py-2 self-start"
          >
            <Text className="text-red-400 text-sm font-medium">Sign Out</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
