import { useEffect, useState } from "react";
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { loadConfig, saveConfig, type AppConfig } from "../src/config";
import { healthCheck, listBots } from "../src/agent";
import { newSessionId } from "../src/session";

export default function SettingsScreen() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<"unknown" | "ok" | "failed">("unknown");
  const [bots, setBots] = useState<Array<{ id: string; name: string; model: string }>>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    loadConfig().then(setConfig);
  }, []);

  const updateField = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) => {
    if (!config) return;
    setConfig({ ...config, [key]: value });
    setDirty(true);
  };

  const handleSave = async () => {
    if (!config) return;
    await saveConfig(config);
    setDirty(false);
    Alert.alert("Saved", "Configuration updated.");
  };

  const handleTest = async () => {
    if (dirty && config) {
      await saveConfig(config);
      setDirty(false);
    }
    setConnectionStatus("unknown");
    const ok = await healthCheck();
    setConnectionStatus(ok ? "ok" : "failed");
    if (ok) {
      try {
        const b = await listBots();
        setBots(b);
      } catch {
        setBots([]);
      }
    }
  };

  const handleNewSession = async () => {
    const id = await newSessionId();
    Alert.alert("New Session", `Session ID: ${id.slice(0, 8)}...`);
  };

  if (!config) return null;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.sectionTitle}>Server Connection</Text>

      <Text style={styles.label}>Server URL</Text>
      <TextInput
        style={styles.input}
        value={config.agentUrl}
        onChangeText={(v) => updateField("agentUrl", v)}
        placeholder="http://192.168.1.x:8000"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />

      <Text style={styles.label}>API Key</Text>
      <TextInput
        style={styles.input}
        value={config.apiKey}
        onChangeText={(v) => updateField("apiKey", v)}
        placeholder="your-bearer-key"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
      />

      <Pressable style={styles.button} onPress={handleTest}>
        <Text style={styles.buttonText}>Test Connection</Text>
      </Pressable>

      {connectionStatus === "ok" && (
        <Text style={styles.successText}>Connected successfully</Text>
      )}
      {connectionStatus === "failed" && (
        <Text style={styles.errorText}>Connection failed — check URL and network</Text>
      )}

      {bots.length > 0 && (
        <View style={styles.botsSection}>
          <Text style={styles.label}>Available Bots</Text>
          {bots.map((b) => (
            <Pressable
              key={b.id}
              style={[styles.botRow, config.botId === b.id && styles.botRowActive]}
              onPress={() => updateField("botId", b.id)}
            >
              <Text style={styles.botName}>{b.name}</Text>
              <Text style={styles.botDetail}>
                {b.id} · {b.model}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      <Text style={[styles.sectionTitle, { marginTop: 24 }]}>Client</Text>

      <Text style={styles.label}>Bot ID</Text>
      <TextInput
        style={styles.input}
        value={config.botId}
        onChangeText={(v) => updateField("botId", v)}
        placeholder="default"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
      />

      <Text style={styles.label}>Client ID</Text>
      <TextInput
        style={styles.input}
        value={config.clientId}
        onChangeText={(v) => updateField("clientId", v)}
        placeholder="android-tablet"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
      />

      <View style={styles.switchRow}>
        <Text style={styles.label}>TTS Enabled</Text>
        <Switch
          value={config.ttsEnabled}
          onValueChange={(v) => updateField("ttsEnabled", v)}
          trackColor={{ true: "#0f3460", false: "#374151" }}
        />
      </View>

      <View style={styles.switchRow}>
        <Text style={styles.label}>Overlay Enabled</Text>
        <Switch
          value={config.overlayEnabled}
          onValueChange={(v) => updateField("overlayEnabled", v)}
          trackColor={{ true: "#0f3460", false: "#374151" }}
        />
      </View>

      <Text style={styles.label}>Wake Word</Text>
      <TextInput
        style={styles.input}
        value={config.wakeWord}
        onChangeText={(v) => updateField("wakeWord", v)}
        placeholder="jarvis"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
      />

      {dirty && (
        <Pressable style={[styles.button, styles.saveButton]} onPress={handleSave}>
          <Text style={styles.buttonText}>Save</Text>
        </Pressable>
      )}

      <Text style={[styles.sectionTitle, { marginTop: 24 }]}>Session</Text>

      <Pressable style={styles.button} onPress={handleNewSession}>
        <Text style={styles.buttonText}>New Session</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#16213e",
  },
  content: {
    padding: 20,
    paddingBottom: 40,
  },
  sectionTitle: {
    color: "#60a5fa",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 12,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  label: {
    color: "#9ca3af",
    fontSize: 13,
    marginBottom: 4,
    marginTop: 12,
  },
  input: {
    backgroundColor: "#1a1a2e",
    color: "#e0e0e0",
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  button: {
    backgroundColor: "#0f3460",
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: "center",
    marginTop: 16,
  },
  saveButton: {
    backgroundColor: "#065f46",
  },
  buttonText: {
    color: "#60a5fa",
    fontWeight: "600",
    fontSize: 15,
  },
  successText: {
    color: "#4ade80",
    fontSize: 13,
    marginTop: 8,
    textAlign: "center",
  },
  errorText: {
    color: "#ef4444",
    fontSize: 13,
    marginTop: 8,
    textAlign: "center",
  },
  botsSection: {
    marginTop: 8,
  },
  botRow: {
    backgroundColor: "#1a1a2e",
    padding: 12,
    borderRadius: 8,
    marginTop: 6,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  botRowActive: {
    borderColor: "#60a5fa",
  },
  botName: {
    color: "#e0e0e0",
    fontSize: 15,
    fontWeight: "600",
  },
  botDetail: {
    color: "#6b7280",
    fontSize: 13,
    marginTop: 2,
  },
  switchRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
  },
});
