import { useState } from "react";
import { Server, Mail, Lock, Key, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useAuthStore } from "@/src/stores/auth";
import { useThemeTokens } from "@/src/theme/tokens";
import type { AuthStatus, TokenResponse } from "@/src/types/api";

export default function LoginScreen() {
  const navigate = useNavigate();
  const t = useThemeTokens();
  const setServer = useAuthStore((s) => s.setServer);
  const setAuth = useAuthStore((s) => s.setAuth);

  const [serverUrl, setServerUrl] = useState(() => {
    if (typeof window !== "undefined") {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return "http://localhost:8000";
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serverChecked, setServerChecked] = useState(false);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);

  /** Step 1: Check server and fetch auth status */
  const handleCheckServer = async () => {
    const url = serverUrl.replace(/\/+$/, "");
    if (!url) {
      setError("Server URL is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Check health first
      const healthRes = await fetch(`${url}/health`);
      if (!healthRes.ok) throw new Error(`Server returned ${healthRes.status}`);

      // Check auth status
      const statusRes = await fetch(`${url}/auth/status`);
      if (statusRes.ok) {
        const status: AuthStatus = await statusRes.json();
        setAuthStatus(status);

        // If setup required, store the URL and redirect to setup
        if (status.setup_required) {
          // Temporarily store serverUrl so setup screen can use it
          useAuthStore.setState({ serverUrl: url });
          navigate("/setup", { replace: true });
          return;
        }
      }

      setServerChecked(true);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not connect to server"
      );
    } finally {
      setLoading(false);
    }
  };

  /** Step 2a: Login with email/password */
  const handleLogin = async () => {
    if (!email || !password) {
      setError("Email and password are required");
      return;
    }

    const url = serverUrl.replace(/\/+$/, "");
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${url}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(data.detail || `Error ${res.status}`);
      }
      const data: TokenResponse = await res.json();
      setAuth(url, data, data.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  /** Step 2b: Connect with API key (legacy) */
  const handleApiKeyConnect = async () => {
    const url = serverUrl.replace(/\/+$/, "");
    if (!url || !apiKey) {
      setError("Server URL and API key are required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${url}/health`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setServer(url, apiKey);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect");
    } finally {
      setLoading(false);
    }
  };

  // Step 1: Server URL input
  if (!serverChecked) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center p-6">
        <div className="flex w-full max-w-sm gap-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-text text-2xl font-bold">Spindrel</span>
            <span className="text-text-muted text-sm">
              Enter your server URL to get started
            </span>
          </div>

          <div className="flex gap-2">
            <div className="flex flex-row items-center gap-2">
              <Server size={16} color={t.textMuted} />
              <span className="text-text-muted text-sm">Server URL</span>
            </div>
            <input
              className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
              placeholder="http://localhost:8000"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              autoCorrect="off"
              type="url"
              onKeyDown={(e) => { if (e.key === "Enter") handleCheckServer(); }}
            />
          </div>

          {error && (
            <span className="text-red-400 text-sm text-center">{error}</span>
          )}

          <button
            type="button"
            onClick={handleCheckServer}
            disabled={loading}
            className="flex bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
          >
            {loading ? (
              <Spinner color="white" size={16} />
            ) : (
              <>
                <span className="text-white font-semibold">Continue</span>
                <ArrowRight size={16} color="white" />
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  // Step 2: Login form
  return (
    <div className="flex flex-1 bg-surface items-center justify-center p-6">
      <div className="flex w-full max-w-sm gap-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-text text-2xl font-bold">Sign In</span>
          <span className="text-text-muted text-sm">
            {serverUrl.replace(/^https?:\/\//, "")}
          </span>
        </div>

        {/* Email */}
        <div className="flex gap-2">
          <div className="flex flex-row items-center gap-2">
            <Mail size={16} color={t.textMuted} />
            <span className="text-text-muted text-sm">Email</span>
          </div>
          <input
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="you@example.com"
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
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            onKeyDown={(e) => { if (e.key === "Enter") handleLogin(); }}
          />
        </div>

        {error && (
          <span className="text-red-400 text-sm text-center">{error}</span>
        )}

        {/* Sign In button */}
        <button
          type="button"
          onClick={handleLogin}
          disabled={loading}
          className="flex bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
        >
          {loading ? (
            <Spinner color="white" size={16} />
          ) : (
            <>
              <span className="text-white font-semibold">Sign In</span>
              <ArrowRight size={16} color="white" />
            </>
          )}
        </button>

        {/* API Key fallback */}
        <button
          type="button"
          onClick={() => setShowApiKey(!showApiKey)}
          className="flex flex-row items-center justify-center gap-1"
        >
          <span className="text-text-dim text-xs">Use API Key instead</span>
          {showApiKey ? (
            <ChevronUp size={12} color={t.textDim} />
          ) : (
            <ChevronDown size={12} color={t.textDim} />
          )}
        </button>

        {showApiKey && (
          <div className="flex gap-4">
            <div className="flex gap-2">
              <div className="flex flex-row items-center gap-2">
                <Key size={16} color={t.textMuted} />
                <span className="text-text-muted text-sm">API Key</span>
              </div>
              <input
                className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
                placeholder="Bearer token"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                type="password"
                autoCorrect="off"
              />
            </div>
            <button
              type="button"
              onClick={handleApiKeyConnect}
              disabled={loading}
              className="flex border border-surface-border rounded-lg px-4 py-3 flex-row items-center justify-center gap-2"
            >
              <span className="text-text-muted font-semibold">
                Connect with API Key
              </span>
            </button>
          </div>
        )}

        {/* Back */}
        <button
          type="button"
          onClick={() => {
            setServerChecked(false);
            setError(null);
          }}
          className="flex items-center"
        >
          <span className="text-text-dim text-xs">Change server</span>
        </button>
      </div>
    </div>
  );
}
