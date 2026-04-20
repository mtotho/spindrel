import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { User, Link2, Lock, Check, Eye, EyeOff, Key, Copy, RefreshCw, AlertTriangle } from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { apiFetch } from "@/src/api/client";
import { useAuthStore, AuthUser } from "@/src/stores/auth";
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

interface ApiKeyMeta {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

interface ApiKeyRotateResult {
  key: ApiKeyMeta;
  full_key: string;
}

function useIntegrations() {
  return useQuery({
    queryKey: ["auth-integrations"],
    queryFn: () => apiFetch<IntegrationInfo[]>("/auth/integrations"),
  });
}

function useMyApiKey() {
  return useQuery({
    queryKey: ["auth-me-api-key"],
    queryFn: () => apiFetch<ApiKeyMeta | null>("/auth/me/api-key"),
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
      {saved && <span className="text-green-400 text-xs">Saved</span>}
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
        <Link2 size={16} className="text-text-muted" />
        <span className="text-text font-semibold text-base">Integrations</span>
      </div>
      <span className="text-text-muted text-xs">
        Link your accounts so the server can associate integration messages with your user.
      </span>

      {integrations.map((integration) => (
        <div
          key={integration.id}
          className="flex flex-col bg-surface-raised rounded-lg p-4 gap-3"
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
      {saved && <span className="text-green-400 text-xs">Saved</span>}
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
          <Lock size={16} className="text-text-muted" />
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
        <Lock size={16} className="text-text-muted" />
        <span className="text-text font-semibold text-base">Security</span>
      </div>

      <div className="flex flex-col bg-surface-raised rounded-lg p-4 gap-3">
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
          className="flex bg-accent rounded px-4 py-2 self-start flex-row items-center gap-2 disabled:opacity-50"
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
// API Key Section — user's own scoped key. GET metadata + POST rotate.
// ---------------------------------------------------------------------------

function ApiKeySection() {
  const qc = useQueryClient();
  const { data: key, isLoading } = useMyApiKey();
  const [revealed, setRevealed] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);

  const rotateMutation = useMutation({
    mutationFn: () =>
      apiFetch<ApiKeyRotateResult>("/auth/me/api-key/rotate", { method: "POST" }),
    onSuccess: (data) => {
      setRevealed(data.full_key);
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["auth-me-api-key"] });
    },
  });

  const copy = () => {
    if (!revealed) return;
    navigator.clipboard.writeText(revealed).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-row items-center gap-2">
        <Key size={16} className="text-text-muted" />
        <span className="text-text font-semibold text-base">API Key</span>
      </div>
      <span className="text-text-muted text-xs">
        Your personal scoped API key. Use it to call Spindrel from scripts or
        tools outside the web app. Only the metadata is visible after creation
        — rotate to see a new plaintext value (once).
      </span>

      <div className="flex flex-col bg-surface-raised rounded-lg p-4 gap-3">
        {isLoading ? (
          <Spinner size={16} />
        ) : !key ? (
          <span className="text-text-muted text-sm">
            No API key yet — rotate to mint one.
          </span>
        ) : (
          <>
            <div className="flex flex-row items-center justify-between gap-2">
              <span className="text-text font-mono text-sm">
                {key.key_prefix}
                <span className="text-text-dim">...</span>
              </span>
              <span
                className={
                  key.is_active
                    ? "text-green-400 text-[10px] uppercase tracking-wider"
                    : "text-red-400 text-[10px] uppercase tracking-wider"
                }
              >
                {key.is_active ? "Active" : "Inactive"}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-text-dim text-xs">Scopes</span>
              <div className="flex flex-row flex-wrap gap-1">
                {key.scopes.map((s) => (
                  <span
                    key={s}
                    className="bg-surface-overlay px-1.5 py-0.5 rounded text-text-muted text-[11px]"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex flex-row gap-4 text-xs text-text-dim">
              <span>
                Created {new Date(key.created_at).toLocaleDateString()}
              </span>
              {key.last_used_at && (
                <span>
                  Last used {new Date(key.last_used_at).toLocaleDateString()}
                </span>
              )}
            </div>
          </>
        )}

        {revealed ? (
          <div className="flex flex-col gap-2 bg-amber-500/10 border border-amber-500/30 rounded p-3">
            <div className="flex flex-row items-center gap-2">
              <AlertTriangle size={14} className="text-amber-400" />
              <span className="text-amber-400 text-xs font-medium">
                Copy this key now — it won't be shown again.
              </span>
            </div>
            <div className="flex flex-row items-center gap-2">
              <code className="flex-1 text-[12px] text-text font-mono break-all bg-surface rounded px-2 py-1.5">
                {revealed}
              </code>
              <button
                type="button"
                onClick={copy}
                className="flex flex-row items-center gap-1 bg-surface-overlay rounded px-2 py-1.5 hover:bg-surface-overlay/80"
              >
                <Copy size={12} className="text-text-muted" />
                <span className="text-text-muted text-xs">
                  {copied ? "Copied" : "Copy"}
                </span>
              </button>
            </div>
            <button
              type="button"
              onClick={() => setRevealed(null)}
              className="self-start text-text-dim text-xs hover:text-text-muted"
            >
              Dismiss
            </button>
          </div>
        ) : confirming ? (
          <div className="flex flex-col gap-2 bg-amber-500/10 border border-amber-500/30 rounded p-3">
            <span className="text-amber-400 text-xs">
              Rotating will invalidate your current key. Any scripts using it
              will stop working until updated.
            </span>
            <div className="flex flex-row gap-2">
              <button
                type="button"
                onClick={() => rotateMutation.mutate()}
                disabled={rotateMutation.isPending}
                className="flex flex-row items-center gap-1 bg-accent rounded px-3 py-1.5 disabled:opacity-50"
              >
                {rotateMutation.isPending ? (
                  <Spinner size={12} color="#fff" />
                ) : (
                  <RefreshCw size={12} color="#fff" />
                )}
                <span className="text-white text-xs font-medium">
                  {key ? "Rotate key" : "Mint key"}
                </span>
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="text-text-dim text-xs px-3 py-1.5 hover:text-text-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="flex flex-row items-center gap-1.5 self-start bg-surface-overlay rounded px-3 py-1.5 hover:bg-surface-overlay/80"
          >
            <RefreshCw size={12} className="text-text-muted" />
            <span className="text-text-muted text-xs">
              {key ? "Rotate key" : "Mint key"}
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account Page
// ---------------------------------------------------------------------------

export default function AccountSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <span className="text-text-muted">Not logged in</span>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex flex-col gap-8 max-w-lg">
        <AccountSection user={user} />
        <div className="h-px bg-surface-border" />
        <ApiKeySection />
        <div className="h-px bg-surface-border" />
        <IntegrationsSection user={user} />
        <div className="h-px bg-surface-border" />
        <SecuritySection user={user} />
        <div className="h-px bg-surface-border" />
        <button
          type="button"
          onClick={clear}
          className="bg-red-500/10 border border-red-500/30 rounded px-4 py-2 self-start"
        >
          <span className="text-red-400 text-sm font-medium">Sign Out</span>
        </button>
      </div>
    </div>
  );
}
