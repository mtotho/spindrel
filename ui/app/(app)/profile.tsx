import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { User, Link2, Lock, Check, X, Eye, EyeOff } from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { apiFetch } from "@/src/api/client";
import { useAuthStore, AuthUser } from "@/src/stores/auth";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";

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
  const t = useThemeTokens();
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
    <div className="flex flex-col gap-4">
      <span className="text-text font-semibold text-base">Account</span>

      {/* Avatar preview */}
      <div className="flex flex-row items-center gap-4">
        <div className="flex w-16 h-16 rounded-full bg-accent/20 items-center justify-center overflow-hidden">
          {avatarUrl ? (
            <img src={avatarUrl} style={{ width: 64, height: 64 }} alt="Avatar" />
          ) : (
            <User size={28} color={t.accent} />
          )}
        </div>
        <div>
          <span className="text-text font-medium">{user.display_name}</span>
          <span className="text-text-muted text-xs">{user.email}</span>
          <div className="flex flex-row gap-2 mt-1">
            <div className="bg-surface-overlay px-1.5 py-0.5 rounded">
              <span className="text-text-dim text-[10px]">{user.auth_method}</span>
            </div>
            {user.is_admin && (
              <div className="bg-amber-500/20 px-1.5 py-0.5 rounded">
                <span className="text-amber-400 text-[10px] font-medium">Admin</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Fields */}
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

      {dirty && (
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="flex bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
        >
          {saveMutation.isPending ? (
            <Spinner size={16} color="#fff" />
          ) : (
            <Check size={14} color="#fff" />
          )}
          <span className="text-white text-sm font-medium">Save</span>
        </button>
      )}
      {saved && (
        <span className="text-green-400 text-xs">Saved</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integrations Section
// ---------------------------------------------------------------------------

function IntegrationsSection({ user }: { user: AuthUser }) {
  const t = useThemeTokens();
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
      <div className="flex flex-col gap-4">
        <span className="text-text font-semibold text-base">Integrations</span>
        <Spinner size={16} color={t.accent} />
      </div>
    );
  }

  if (!integrations?.length) {
    return (
      <div className="flex flex-col gap-4">
        <span className="text-text font-semibold text-base">Integrations</span>
        <span className="text-text-muted text-sm">No integrations configured.</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-row items-center gap-2">
        <Link2 size={16} color="#9ca3af" />
        <span className="text-text font-semibold text-base">Integrations</span>
      </div>
      <span className="text-text-muted text-xs">
        Link your accounts so the server can associate integration messages with your user.
      </span>

      {integrations.map((integration) => (
        <div
          key={integration.id}
          className="flex flex-col bg-surface-raised border border-surface-border rounded-lg p-4 gap-3"
        >
          <span className="text-text font-medium">{integration.name}</span>
          {integration.fields.map((field) => (
            <div key={field.key} className="flex flex-col gap-1">
              <span className="text-text-dim text-xs">{field.label}</span>
              <input
                className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
                value={values[integration.id]?.[field.key] || ""}
                onChange={(e) => updateField(integration.id, field.key, e.target.value)}
                placeholder={field.description}
              />
            </div>
          ))}
        </div>
      ))}

      {dirty && (
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="flex bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
        >
          {saveMutation.isPending ? (
            <Spinner size={16} color="#fff" />
          ) : (
            <Check size={14} color="#fff" />
          )}
          <span className="text-white text-sm font-medium">Save</span>
        </button>
      )}
      {saved && (
        <span className="text-green-400 text-xs">Saved</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Security Section (password change for local auth)
// ---------------------------------------------------------------------------

function SecuritySection({ user }: { user: AuthUser }) {
  const t = useThemeTokens();
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
      <div className="flex flex-col gap-4">
        <div className="flex flex-row items-center gap-2">
          <Lock size={16} color="#9ca3af" />
          <span className="text-text font-semibold text-base">Security</span>
        </div>
        <span className="text-text-muted text-sm">
          Password management is not available for {user.auth_method} authentication.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-row items-center gap-2">
        <Lock size={16} color="#9ca3af" />
        <span className="text-text font-semibold text-base">Security</span>
      </div>

      <div className="flex flex-col bg-surface-raised border border-surface-border rounded-lg p-4 gap-3">
        <span className="text-text font-medium text-sm">Change Password</span>

        <div className="flex flex-col gap-1">
          <span className="text-text-dim text-xs">Current Password</span>
          <div className="flex flex-row items-center">
            <input
              className="flex-1 bg-surface border border-surface-border rounded-l px-3 py-2 text-text text-sm"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              type={showCurrent ? "text" : "password"}
            />
            <button
              type="button"
              onClick={() => setShowCurrent(!showCurrent)}
              className="bg-surface border border-l-0 border-surface-border rounded-r px-3 py-2"
            >
              {showCurrent ? (
                <EyeOff size={14} color={t.textMuted} />
              ) : (
                <Eye size={14} color={t.textMuted} />
              )}
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-text-dim text-xs">New Password</span>
          <div className="flex flex-row items-center">
            <input
              className="flex-1 bg-surface border border-surface-border rounded-l px-3 py-2 text-text text-sm"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              type={showNew ? "text" : "password"}
            />
            <button
              type="button"
              onClick={() => setShowNew(!showNew)}
              className="bg-surface border border-l-0 border-surface-border rounded-r px-3 py-2"
            >
              {showNew ? (
                <EyeOff size={14} color={t.textMuted} />
              ) : (
                <Eye size={14} color={t.textMuted} />
              )}
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-text-dim text-xs">Confirm New Password</span>
          <input
            className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            type={showNew ? "text" : "password"}
          />
        </div>

        {error && <span className="text-red-400 text-xs">{error}</span>}
        {success && <span className="text-green-400 text-xs">Password changed successfully</span>}

        <button
          type="button"
          onClick={handleSubmit}
          disabled={changeMutation.isPending || !currentPassword || !newPassword}
          className="flex bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2"
          style={{
            opacity: !currentPassword || !newPassword ? 0.5 : 1,
          }}
        >
          {changeMutation.isPending ? (
            <Spinner size={16} color="#fff" />
          ) : (
            <Lock size={14} color="#fff" />
          )}
          <span className="text-white text-sm font-medium">Change Password</span>
        </button>
      </div>
    </div>
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
      <div className="flex flex-1 bg-surface items-center justify-center">
        <span className="text-text-muted">Not logged in</span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Profile" />

      <div className="flex-1 p-6 overflow-auto">
        <div className="flex flex-col gap-8 max-w-lg">
          <AccountSection user={user} />

          <div className="h-px bg-surface-border" />

          <IntegrationsSection user={user} />

          <div className="h-px bg-surface-border" />

          <SecuritySection user={user} />

          <div className="h-px bg-surface-border" />

          {/* Sign out */}
          <button
            type="button"
            onClick={clear}
            className="bg-red-500/10 border border-red-500/30 rounded px-4 py-2 self-start"
          >
            <span className="text-red-400 text-sm font-medium">Sign Out</span>
          </button>
        </div>
      </div>
    </div>
  );
}
