import { useState } from "react";
import { View, Text, TextInput, Pressable, ActivityIndicator } from "react-native";
import { Server, Key, ArrowRight } from "lucide-react";
import { useAuthStore } from "@/src/stores/auth";

export default function LoginScreen() {
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setServer = useAuthStore((s) => s.setServer);

  const handleConnect = async () => {
    const url = serverUrl.replace(/\/+$/, "");
    if (!url) {
      setError("Server URL is required");
      return;
    }

    setTesting(true);
    setError(null);

    try {
      const res = await fetch(`${url}/health`, {
        headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setServer(url, apiKey);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not connect to server"
      );
    } finally {
      setTesting(false);
    }
  };

  return (
    <View className="flex-1 bg-surface items-center justify-center p-6">
      <View className="w-full max-w-sm gap-6">
        {/* Header */}
        <View className="items-center gap-2 mb-4">
          <Text className="text-text text-2xl font-bold">Agent Server</Text>
          <Text className="text-text-muted text-sm">
            Connect to your server to get started
          </Text>
        </View>

        {/* Server URL */}
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
          />
        </View>

        {/* API Key */}
        <View className="gap-2">
          <View className="flex-row items-center gap-2">
            <Key size={16} color="#999999" />
            <Text className="text-text-muted text-sm">
              API Key (optional)
            </Text>
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

        {/* Error */}
        {error && (
          <Text className="text-red-400 text-sm text-center">{error}</Text>
        )}

        {/* Connect button */}
        <Pressable
          onPress={handleConnect}
          disabled={testing}
          className="bg-accent rounded-lg px-4 py-3 flex-row items-center justify-center gap-2 active:bg-accent-hover"
        >
          {testing ? (
            <ActivityIndicator color="white" size="small" />
          ) : (
            <>
              <Text className="text-white font-semibold">Connect</Text>
              <ArrowRight size={16} color="white" />
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}
