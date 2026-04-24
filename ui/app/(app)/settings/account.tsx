import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  BellOff,
  Check,
  Copy,
  Download,
  Eye,
  EyeOff,
  Key,
  Link2,
  Lock,
  Moon,
  RefreshCw,
  Sun,
  User,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { Spinner } from "@/src/components/shared/Spinner";
import { Section, TextInput, Toggle } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { useAuthStore, type AuthUser } from "@/src/stores/auth";
import { useThemeStore } from "@/src/stores/theme";
import { useInstallPromptStore } from "@/src/stores/installPrompt";
import {
  disablePush,
  enablePush,
  getExistingSubscription,
  isPushSupported,
  notificationPermission,
} from "@/src/lib/pushSubscription";

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

function AccountSection({ user }: { user: AuthUser }) {
  const updateUser = useAuthStore((s) => s.updateUser);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || "");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDisplayName(user.display_name);
    setAvatarUrl(user.avatar_url || "");
  }, [user.display_name, user.avatar_url]);

  const dirty = displayName !== user.display_name || (avatarUrl || null) !== (user.avatar_url || null);
  const saveMutation = useMutation({
    mutationFn: () =>
      apiFetch<AuthUser>("/auth/me", {
        method: "PUT",
        body: JSON.stringify({ display_name: displayName, avatar_url: avatarUrl || null }),
      }),
    onSuccess: (data) => {
      updateUser(data);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
    },
  });

  return (
    <Section
      title="Profile"
      description="Personal identity shown in channels, audit views, and integration attribution."
      action={
        <div className="flex items-center gap-2">
          <SaveStatusPill
            tone={saveMutation.isPending ? "pending" : saved ? "saved" : dirty ? "dirty" : "idle"}
            label={saveMutation.isPending ? "Saving" : saved ? "Saved" : "Changes pending"}
          />
          <ActionButton
            label="Save"
            onPress={() => saveMutation.mutate()}
            disabled={!dirty || saveMutation.isPending}
            icon={saveMutation.isPending ? <Spinner size={13} /> : <Check size={13} />}
          />
        </div>
      }
    >
      <div className="flex items-center gap-3">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-full bg-accent/10 text-accent">
          {avatarUrl ? <img src={avatarUrl} alt="Avatar" className="h-full w-full object-cover" /> : <User size={24} />}
        </div>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-text">{user.display_name}</div>
          <div className="truncate text-[12px] text-text-dim">{user.email}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <QuietPill label={user.auth_method} />
            {user.is_admin && <StatusBadge label="Admin" variant="warning" />}
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <TextInput value={displayName} onChangeText={setDisplayName} placeholder="Display name" />
        <TextInput value={avatarUrl} onChangeText={setAvatarUrl} placeholder="Avatar URL" />
      </div>
    </Section>
  );
}

function PreferencesSection() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  const promptInstall = useInstallPromptStore((s) => s.promptInstall);
  const installEvent = useInstallPromptStore((s) => s.event);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushMessage, setPushMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isPushSupported()) return;
    getExistingSubscription().then((sub) => setPushEnabled(!!sub)).catch(() => setPushEnabled(false));
  }, []);

  const togglePush = async () => {
    setPushBusy(true);
    setPushMessage(null);
    try {
      if (pushEnabled) {
        await disablePush();
        setPushEnabled(false);
        setPushMessage("Push notifications disabled on this device.");
      } else {
        const result = await enablePush();
        if (result.ok) {
          setPushEnabled(true);
          setPushMessage("Push notifications enabled on this device.");
        } else {
          setPushMessage(result.message || `Push notifications are ${result.reason}.`);
        }
      }
    } finally {
      setPushBusy(false);
    }
  };

  const permission = notificationPermission();

  return (
    <Section title="Preferences" description="Device-local preferences that should follow you less than server settings do.">
      <div className="flex flex-col gap-2">
        <SettingsControlRow
          leading={mode === "dark" ? <Moon size={15} /> : <Sun size={15} />}
          title="Appearance"
          description={mode === "dark" ? "Dark mode is active." : "Light mode is active."}
          action={<Toggle value={mode === "dark"} onChange={(next) => setMode(next ? "dark" : "light")} />}
        />
        <SettingsControlRow
          leading={<Download size={15} />}
          title="Install app"
          description={installEvent ? "Browser install prompt is available." : "Use your browser install menu if the prompt is not available."}
          action={<ActionButton label="Install" onPress={() => void promptInstall()} size="small" disabled={!installEvent} />}
        />
        <SettingsControlRow
          leading={pushEnabled ? <Bell size={15} /> : <BellOff size={15} />}
          title="Push notifications"
          description={
            isPushSupported()
              ? pushMessage || `Browser permission: ${permission}.`
              : "This browser or device does not support web push here."
          }
          action={
            <ActionButton
              label={pushBusy ? "Working" : pushEnabled ? "Disable" : "Enable"}
              onPress={togglePush}
              size="small"
              disabled={pushBusy || !isPushSupported()}
            />
          }
        />
      </div>
    </Section>
  );
}

function ApiKeySection() {
  const qc = useQueryClient();
  const { data: key, isLoading } = useMyApiKey();
  const [revealed, setRevealed] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);

  const rotateMutation = useMutation({
    mutationFn: () => apiFetch<ApiKeyRotateResult>("/auth/me/api-key/rotate", { method: "POST" }),
    onSuccess: (data) => {
      setRevealed(data.full_key);
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["auth-me-api-key"] });
    },
  });

  return (
    <Section title="API key" description="Your personal scoped key for scripts and external tools. Plaintext is shown once after rotation.">
      <div className="flex flex-col gap-2">
        {isLoading ? (
          <div className="py-4"><Spinner size={16} /></div>
        ) : key ? (
          <SettingsControlRow
            leading={<Key size={15} />}
            title={<span className="font-mono">{key.key_prefix}<span className="text-text-dim">...</span></span>}
            description={`Created ${new Date(key.created_at).toLocaleDateString()}${key.last_used_at ? `, last used ${new Date(key.last_used_at).toLocaleDateString()}` : ""}`}
            meta={<StatusBadge label={key.is_active ? "Active" : "Inactive"} variant={key.is_active ? "success" : "danger"} />}
          />
        ) : (
          <EmptyState message="No personal API key exists yet." />
        )}
        {key?.scopes?.length ? (
          <div className="flex flex-wrap gap-1.5">
            {key.scopes.map((scope) => <QuietPill key={scope} label={scope} maxWidthClass="max-w-[220px]" />)}
          </div>
        ) : null}
        {revealed && (
          <InfoBanner variant="warning" icon={<AlertTriangle size={14} />}>
            <div className="flex flex-col gap-2">
              <div>Copy this key now. It will not be shown again.</div>
              <code className="rounded-md bg-surface-overlay/45 px-2 py-1.5 font-mono text-[11px] text-text">{revealed}</code>
              <div>
                <ActionButton
                  label={copied ? "Copied" : "Copy"}
                  onPress={() => navigator.clipboard.writeText(revealed).then(() => {
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1200);
                  })}
                  size="small"
                  icon={<Copy size={12} />}
                />
              </div>
            </div>
          </InfoBanner>
        )}
        <div className="flex flex-wrap gap-2">
          {confirming ? (
            <>
              <ActionButton
                label={rotateMutation.isPending ? "Rotating" : key ? "Rotate key" : "Mint key"}
                onPress={() => rotateMutation.mutate()}
                disabled={rotateMutation.isPending}
                icon={<RefreshCw size={13} />}
              />
              <ActionButton label="Cancel" onPress={() => setConfirming(false)} variant="ghost" />
            </>
          ) : (
            <ActionButton label={key ? "Rotate key" : "Mint key"} onPress={() => setConfirming(true)} icon={<RefreshCw size={13} />} />
          )}
        </div>
      </div>
    </Section>
  );
}

function IntegrationsSection({ user }: { user: AuthUser }) {
  const updateUser = useAuthStore((s) => s.updateUser);
  const { data: integrations, isLoading } = useIntegrations();
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!integrations) return;
    const init: Record<string, Record<string, string>> = {};
    for (const integration of integrations) {
      init[integration.id] = {};
      for (const field of integration.fields) {
        init[integration.id][field.key] = user.integration_config?.[integration.id]?.[field.key] || "";
      }
    }
    setValues(init);
  }, [integrations, user.integration_config]);

  const dirty = integrations?.some((integration) =>
    integration.fields.some((field) =>
      (values[integration.id]?.[field.key] || "") !== (user.integration_config?.[integration.id]?.[field.key] || ""),
    ),
  ) ?? false;

  const saveMutation = useMutation({
    mutationFn: () => {
      const config = { ...(user.integration_config || {}) };
      for (const [integrationId, fields] of Object.entries(values)) {
        const cleaned = Object.fromEntries(Object.entries(fields).filter(([, value]) => value));
        if (Object.keys(cleaned).length > 0) config[integrationId] = { ...(config[integrationId] || {}), ...cleaned };
      }
      return apiFetch<AuthUser>("/auth/me", { method: "PUT", body: JSON.stringify({ integration_config: config }) });
    },
    onSuccess: (data) => {
      updateUser(data);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
    },
  });

  return (
    <Section
      title="Integration identity"
      description="Per-user identifiers that let integrations associate incoming messages with your account."
      action={
        <div className="flex items-center gap-2">
          <SaveStatusPill
            tone={saveMutation.isPending ? "pending" : saved ? "saved" : dirty ? "dirty" : "idle"}
            label={saveMutation.isPending ? "Saving" : saved ? "Saved" : "Changes pending"}
          />
          <ActionButton label="Save" onPress={() => saveMutation.mutate()} disabled={!dirty || saveMutation.isPending} />
        </div>
      }
    >
      {isLoading ? (
        <div className="py-4"><Spinner size={16} /></div>
      ) : !integrations?.length ? (
        <EmptyState message="No integration identity fields are configured." />
      ) : (
        <div className="flex flex-col gap-3">
          {integrations.map((integration) => (
            <div key={integration.id} className="rounded-md bg-surface-raised/40 px-3 py-3">
              <div className="mb-3 flex items-center gap-2 text-[12px] font-semibold text-text">
                <Link2 size={14} className="text-text-dim" />
                {integration.name}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {integration.fields.map((field) => (
                  <div key={field.key} className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-medium text-text-muted">{field.label}</label>
                    <TextInput
                      value={values[integration.id]?.[field.key] || ""}
                      onChangeText={(value) => setValues((prev) => ({
                        ...prev,
                        [integration.id]: { ...prev[integration.id], [field.key]: value },
                      }))}
                      placeholder={field.description}
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

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
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setError(null);
      setSuccess(true);
      window.setTimeout(() => setSuccess(false), 2400);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed to change password"),
  });

  const submit = () => {
    setError(null);
    if (newPassword.length < 8) return setError("Password must be at least 8 characters.");
    if (newPassword !== confirmPassword) return setError("Passwords do not match.");
    changeMutation.mutate();
  };

  return (
    <Section title="Security" description="Credential management for your account.">
      {user.auth_method !== "local" ? (
        <InfoBanner variant="info" icon={<Lock size={14} />}>
          Password management is handled by {user.auth_method} authentication.
        </InfoBanner>
      ) : (
        <div className="flex max-w-2xl flex-col gap-3 rounded-md bg-surface-raised/40 px-3 py-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-[12px] font-medium text-text-muted">Current password</label>
              <div className="flex">
                <TextInput value={currentPassword} onChangeText={setCurrentPassword} type={showCurrent ? "text" : "password"} className="rounded-r-none" />
                <button type="button" onClick={() => setShowCurrent(!showCurrent)} className="rounded-r-md border border-l-0 border-input-border bg-input px-3 text-text-dim hover:text-text">
                  {showCurrent ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[12px] font-medium text-text-muted">New password</label>
              <div className="flex">
                <TextInput value={newPassword} onChangeText={setNewPassword} type={showNew ? "text" : "password"} className="rounded-r-none" />
                <button type="button" onClick={() => setShowNew(!showNew)} className="rounded-r-md border border-l-0 border-input-border bg-input px-3 text-text-dim hover:text-text">
                  {showNew ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          </div>
          <TextInput value={confirmPassword} onChangeText={setConfirmPassword} type={showNew ? "text" : "password"} placeholder="Confirm new password" />
          {error && <InfoBanner variant="danger">{error}</InfoBanner>}
          {success && <StatusBadge label="Password changed" variant="success" />}
          <ActionButton
            label={changeMutation.isPending ? "Changing" : "Change password"}
            onPress={submit}
            disabled={changeMutation.isPending || !currentPassword || !newPassword}
            icon={<Lock size={13} />}
          />
        </div>
      )}
    </Section>
  );
}

export default function AccountSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  if (!user) {
    return <div className="flex h-full items-center justify-center p-6 text-text-muted">Not logged in</div>;
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-7 px-4 py-5 md:px-6">
      <AccountSection user={user} />
      <PreferencesSection />
      <ApiKeySection />
      <IntegrationsSection user={user} />
      <SecuritySection user={user} />
      <Section title="Session" description="End this browser session.">
        <ActionButton label="Sign out" onPress={clear} variant="danger" />
      </Section>
    </div>
  );
}
