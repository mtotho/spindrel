import { useCallback, useEffect, useState } from "react";
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
import { useFocusEffect } from "expo-router";
import { loadConfig, saveConfig, type AppConfig } from "../../src/config";
import { healthCheck, listBots } from "../../src/agent";

export default function SettingsScreen() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [bots, setBots] = useState<Array<{ id: string; name: string; model: string }>>([]);
  const [dirty, setDirty] = useState(false);

  useFocusEffect(
    useCallback(() => {
      loadConfig().then((c) => {
        setConfig(c);
        fetchBots();
      });
    }, [])
  );

  const fetchBots = async () => {
    try {
      const ok = await healthCheck();
      setConnected(ok);
      if (ok) {
        const b = await listBots();
        setBots(b);
      }
    } catch {
      setConnected(false);
    }
  };

  const updateField = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) => {
    if (!config) return;
    setConfig({ ...config, [key]: value });
    setDirty(true);
  };

  const selectBot = (botId: string) => {
    updateField("botId", botId);
  };

  const handleSave = async () => {
    if (!config) return;
    await saveConfig(config);
    setDirty(false);
    Alert.alert("Saved", "Configuration updated.");
  };

  const handleTestConnection = async () => {
    if (dirty && config) {
      await saveConfig(config);
      setDirty(false);
    }
    await fetchBots();
  };

  if (!config) return null;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Server */}
      <Text style={styles.sectionTitle}>Server</Text>

      <Text style={styles.label}>URL</Text>
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

      <View style={styles.connectionRow}>
        <Pressable style={styles.testButton} onPress={handleTestConnection}>
          <Text style={styles.testButtonText}>Test</Text>
        </Pressable>
        <View
          style={[
            styles.connectionIndicator,
            {
              backgroundColor:
                connected === true ? "#4ade80" : connected === false ? "#ef4444" : "#4b5563",
            },
          ]}
        />
        <Text style={styles.connectionLabel}>
          {connected === true ? "Connected" : connected === false ? "Disconnected" : "Unknown"}
        </Text>
      </View>

      {/* Bot */}
      <Text style={[styles.sectionTitle, { marginTop: 28 }]}>Bot</Text>

      {bots.length > 0 ? (
        <View style={styles.botGrid}>
          {bots.map((b) => {
            const isActive = config.botId === b.id;
            return (
              <Pressable
                key={b.id}
                style={[styles.botCard, isActive && styles.botCardActive]}
                onPress={() => selectBot(b.id)}
              >
                <Text style={[styles.botName, isActive && styles.botNameActive]}>{b.name}</Text>
                <Text style={styles.botModel}>{b.model}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <View>
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
          {connected === false && (
            <Text style={styles.hintText}>Connect to server to see available bots</Text>
          )}
        </View>
      )}

      {/* Client */}
      <Text style={[styles.sectionTitle, { marginTop: 28 }]}>Client</Text>

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
        <Text style={styles.switchLabel}>TTS</Text>
        <Switch
          value={config.ttsEnabled}
          onValueChange={(v) => updateField("ttsEnabled", v)}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={config.ttsEnabled ? "#60a5fa" : "#9ca3af"}
        />
      </View>

      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>Overlay</Text>
        <Switch
          value={config.overlayEnabled}
          onValueChange={(v) => updateField("overlayEnabled", v)}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={config.overlayEnabled ? "#60a5fa" : "#9ca3af"}
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

      {/* Save */}
      {dirty && (
        <Pressable style={styles.saveButton} onPress={handleSave}>
          <Text style={styles.saveButtonText}>Save Changes</Text>
        </Pressable>
      )}
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
    fontSize: 14,
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
  connectionRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 12,
    gap: 10,
  },
  testButton: {
    backgroundColor: "#0f3460",
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: 6,
  },
  testButtonText: {
    color: "#60a5fa",
    fontWeight: "600",
    fontSize: 14,
  },
  connectionIndicator: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  connectionLabel: {
    color: "#9ca3af",
    fontSize: 13,
  },
  botGrid: {
    gap: 8,
  },
  botCard: {
    backgroundColor: "#1a1a2e",
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  botCardActive: {
    borderColor: "#60a5fa",
    backgroundColor: "#0f1b3e",
  },
  botName: {
    color: "#e0e0e0",
    fontSize: 15,
    fontWeight: "600",
  },
  botNameActive: {
    color: "#60a5fa",
  },
  botModel: {
    color: "#6b7280",
    fontSize: 13,
    marginTop: 2,
  },
  hintText: {
    color: "#6b7280",
    fontSize: 12,
    marginTop: 6,
    fontStyle: "italic",
  },
  switchRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 14,
    backgroundColor: "#1a1a2e",
    padding: 14,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  switchLabel: {
    color: "#e0e0e0",
    fontSize: 15,
    fontWeight: "500",
  },
  saveButton: {
    backgroundColor: "#065f46",
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 24,
  },
  saveButtonText: {
    color: "#4ade80",
    fontWeight: "700",
    fontSize: 16,
  },
});
