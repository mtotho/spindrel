import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { User, Mail, Lock, ArrowRight } from "lucide-react";
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
    <View className="flex-1 bg-surface items-center justify-center p-6">
      <View className="w-full max-w-sm gap-6">
        {/* Header */}
        <View className="items-center gap-2 mb-4">
          <Text className="text-text text-2xl font-bold">Welcome to Spindrel</Text>
          <Text className="text-text-muted text-sm text-center">
            Create your admin account to get started
          </Text>
        </View>

        {/* Display Name */}
        <View className="gap-2">
          <View className="flex-row items-center gap-2">
            <User size={16} color={t.textMuted} />
            <Text className="text-text-muted text-sm">Display Name</Text>
          </View>
          <TextInput
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="Alice"
            placeholderTextColor={t.textDim}
            value={displayName}
            onChangeText={setDisplayName}
            autoCapitalize="words"
          />
        </View>

        {/* Email */}
        <View className="gap-2">
          <View className="flex-row items-center gap-2">
            <Mail size={16} color={t.textMuted} />
            <Text className="text-text-muted text-sm">Email</Text>
          </View>
          <TextInput
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="admin@example.com"
            placeholderTextColor={t.textDim}
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
            <Lock size={16} color={t.textMuted} />
            <Text className="text-text-muted text-sm">Password</Text>
          </View>
          <TextInput
            className="bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-text"
            placeholder="Choose a password"
            placeholderTextColor={t.textDim}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
          />
        </View>

        {/* Error */}
        {error && (
          <Text className="text-red-400 text-sm text-center">{error}</Text>
        )}

        {/* Create Account button */}
        <Pressable
          onPress={handleLocalSetup}
          disabled={loading}
          className="bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
        >
          {loading ? (
            <ActivityIndicator color="white" size="small" />
          ) : (
            <>
              <Text className="text-white font-semibold">Create Account</Text>
              <ArrowRight size={16} color="white" />
            </>
          )}
        </Pressable>

        <Text className="text-text-dim text-xs text-center">
          This will create the first admin account on this server.
        </Text>
      </View>
    </View>
  );
}
