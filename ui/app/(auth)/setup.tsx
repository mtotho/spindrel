import { useState } from "react";
import { User, Mail, Lock, ArrowRight } from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useAuthStore } from "@/src/stores/auth";
import { useThemeTokens } from "@/src/theme/tokens";
import type { TokenResponse } from "@/src/types/api";

export default function SetupScreen() {
  const t = useThemeTokens();
  const { serverUrl } = useAuthStore.getState();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLocalSetup = async () => {
    if (!email || !password) {
      setError("Email and password are required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${serverUrl}/auth/setup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: "local",
          email,
          password,
          display_name: displayName || email.split("@")[0],
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(data.detail || `Error ${res.status}`);
      }
      const data: TokenResponse = await res.json();
      setAuth(serverUrl, data, data.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-1 bg-surface items-center justify-center p-6">
      <div className="flex w-full max-w-sm gap-6">
        {/* Header */}
        <div className="flex items-center gap-2 mb-4">
          <span className="text-text text-2xl font-bold">Welcome to Spindrel</span>
          <span className="text-text-muted text-sm text-center">
            Create your admin account to get started
          </span>
        </div>

        {/* Display Name */}
        <div className="flex gap-2">
          <div className="flex flex-row items-center gap-2">
            <User size={16} color={t.textMuted} />
            <span className="text-text-muted text-sm">Display Name</span>
          </div>
          <input
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="Alice"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>

        {/* Email */}
        <div className="flex gap-2">
          <div className="flex flex-row items-center gap-2">
            <Mail size={16} color={t.textMuted} />
            <span className="text-text-muted text-sm">Email</span>
          </div>
          <input
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="admin@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoCorrect="off"
            type="email"
          />
        </div>

        {/* Password */}
        <div className="flex gap-2">
          <div className="flex flex-row items-center gap-2">
            <Lock size={16} color={t.textMuted} />
            <span className="text-text-muted text-sm">Password</span>
          </div>
          <input
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="Choose a password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
          />
        </div>

        {/* Error */}
        {error && (
          <span className="text-red-400 text-sm text-center">{error}</span>
        )}

        {/* Create Account button */}
        <button
          type="button"
          onClick={handleLocalSetup}
          disabled={loading}
          className="flex bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
        >
          {loading ? (
            <Spinner color="white" size={16} />
          ) : (
            <>
              <span className="text-white font-semibold">Create Account</span>
              <ArrowRight size={16} color="white" />
            </>
          )}
        </button>

        <span className="text-text-dim text-xs text-center">
          This will create the first admin account on this server.
        </span>
      </div>
    </div>
  );
}
