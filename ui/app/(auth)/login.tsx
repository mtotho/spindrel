import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { Server, Mail, Lock, Key, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import { useRouter } from "expo-router";
import { useAuthStore } from "@/src/stores/auth";
import type { AuthStatus, TokenResponse } from "@/src/types/api";

export default function LoginScreen() {
  const router = useRouter();
  const setServer = useAuthStore((s) => s.setServer);
  const setAuth = useAuthStore((s) => s.setAuth);

  const [serverUrl, setServerUrl] = useState("");
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
          router.replace("/(auth)/setup");
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
      <View className="flex-1 bg-surface items-center justify-center p-6">
        <View className="w-full max-w-sm gap-6">
          <View className="items-center gap-2 mb-4">
            <Text className="text-text text-2xl font-bold">Agent Server</Text>
            <Text className="text-text-muted text-sm">
              Enter your server URL to get started
            </Text>
          </View>

          <View className="gap-2">
            <View className="flex-row items-center gap-2">
              <Server size={16} color="#999999" />
              <Text className="text-text-muted text-sm">Server URL</Text>
            </View>
            <TextInput
              className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
              placeholder="http://localhost:8000"
              placeholderTextColor="#666666"
              value={serverUrl}
              onChangeText={setServerUrl}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              onSubmitEditing={handleCheckServer}
            />
          </View>

          {error && (
            <Text className="text-red-400 text-sm text-center">{error}</Text>
          )}

          <Pressable
            onPress={handleCheckServer}
            disabled={loading}
            className="bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
          >
            {loading ? (
              <ActivityIndicator color="white" size="small" />
            ) : (
              <>
                <Text className="text-white font-semibold">Continue</Text>
                <ArrowRight size={16} color="white" />
              </>
            )}
          </Pressable>
        </View>
      </View>
    );
  }

  // Step 2: Login form
  return (
    <View className="flex-1 bg-surface items-center justify-center p-6">
      <View className="w-full max-w-sm gap-6">
        <View className="items-center gap-2 mb-4">
          <Text className="text-text text-2xl font-bold">Sign In</Text>
          <Text className="text-text-muted text-sm">
            {serverUrl.replace(/^https?:\/\//, "")}
          </Text>
        </View>

        {/* Email */}
        <View className="gap-2">
          <View className="flex-row items-center gap-2">
            <Mail size={16} color="#999999" />
            <Text className="text-text-muted text-sm">Email</Text>
          </View>
          <TextInput
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="you@example.com"
            placeholderTextColor="#666666"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
          />
        </View>

        {/* Password */}
        <View className="gap-2">
          <View className="flex-row items-center gap-2">
            <Lock size={16} color="#999999" />
            <Text className="text-text-muted text-sm">Password</Text>
          </View>
          <TextInput
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="Password"
            placeholderTextColor="#666666"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            onSubmitEditing={handleLogin}
          />
        </View>

        {error && (
          <Text className="text-red-400 text-sm text-center">{error}</Text>
        )}

        {/* Sign In button */}
        <Pressable
          onPress={handleLogin}
          disabled={loading}
          className="bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
        >
          {loading ? (
            <ActivityIndicator color="white" size="small" />
          ) : (
            <>
              <Text className="text-white font-semibold">Sign In</Text>
              <ArrowRight size={16} color="white" />
            </>
          )}
        </Pressable>

        {/* API Key fallback */}
        <Pressable
          onPress={() => setShowApiKey(!showApiKey)}
          className="flex-row items-center justify-center gap-1"
        >
          <Text className="text-text-dim text-xs">Use API Key instead</Text>
          {showApiKey ? (
            <ChevronUp size={12} color="#666666" />
          ) : (
            <ChevronDown size={12} color="#666666" />
          )}
        </Pressable>

        {showApiKey && (
          <View className="gap-4">
            <View className="gap-2">
              <View className="flex-row items-center gap-2">
                <Key size={16} color="#999999" />
                <Text className="text-text-muted text-sm">API Key</Text>
              </View>
              <TextInput
                className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
                placeholder="Bearer token"
                placeholderTextColor="#666666"
                value={apiKey}
                onChangeText={setApiKey}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>
            <Pressable
              onPress={handleApiKeyConnect}
              disabled={loading}
              className="border border-surface-border rounded-lg px-4 py-3 flex-row items-center justify-center gap-2"
            >
              <Text className="text-text-muted font-semibold">
                Connect with API Key
              </Text>
            </Pressable>
          </View>
        )}

        {/* Back */}
        <Pressable
          onPress={() => {
            setServerChecked(false);
            setError(null);
          }}
          className="items-center"
        >
          <Text className="text-text-dim text-xs">Change server</Text>
        </Pressable>
      </View>
    </View>
  );
}
