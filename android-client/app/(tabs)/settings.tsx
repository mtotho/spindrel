import { useCallback, useState } from "react";
import {
  ActivityIndicator,
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
import { loadConfig, saveConfig, BUILT_IN_WAKE_WORDS, type AppConfig } from "../../src/config";
import { testConnection, refreshBotCache } from "../../src/agent";
import { voiceService } from "../../src/service/VoiceService";
import { hasOverlayPermission, requestOverlayPermission } from "../../src/native/OverlayBridge";
import * as Speech from "expo-speech";
import { LISTEN_SOUND_PRESETS, playListenTone, type ListenSoundPreset } from "../../src/voice/tone";
import { voiceDisplayName, isLocalVoice } from "../../src/voice/voiceLabels";
import { useMemo } from "react";

type ConnectionState = "untested" | "testing" | "connected" | "partial" | "failed";

export default function SettingsScreen() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connState, setConnState] = useState<ConnectionState>("untested");
  const [connMessage, setConnMessage] = useState<string>("");
  const [bots, setBots] = useState<Array<{ id: string; name: string; model: string }>>([]);
  const [dirty, setDirty] = useState(false);
  const [overlayPermission, setOverlayPermission] = useState<boolean | null>(null);
  const [ttsVoices, setTtsVoices] = useState<Array<{ identifier: string; name: string; language: string; quality: string }>>([]);
  const [showNetworkVoices, setShowNetworkVoices] = useState(false);
  const [voiceLanguageFilter, setVoiceLanguageFilter] = useState<string>("en-US");

  useFocusEffect(
    useCallback(() => {
      loadConfig().then((c) => {
        setConfig(c);
      });
      hasOverlayPermission().then(setOverlayPermission).catch(() => {});

      const loadVoices = async () => {
        const voices = await Speech.getAvailableVoicesAsync();
        if (voices.length > 0) {
          setTtsVoices(
            voices.map((v) => ({
              identifier: v.identifier,
              name: v.name,
              language: v.language,
              quality: (v as { quality?: string }).quality ?? "Default",
            }))
          );
        } else {
          setTimeout(loadVoices, 1000);
        }
      };
      Speech.speak(" ", { rate: 1 });
      setTimeout(() => void loadVoices(), 300);
    }, [])
  );

  // Yes, filteredVoices should be in a useMemo if you want it to update in response to filter changes!
  const filteredVoices = useMemo(() => {
    let list = ttsVoices;
    if (!showNetworkVoices) {
      list = list.filter((v) => isLocalVoice(v.identifier));
    }
    if (voiceLanguageFilter !== "all") {
      list = list.filter((v) => v.language.toLowerCase() === voiceLanguageFilter.toLowerCase());
    }
    const sorted = list.sort((a, b) => {
      const aLocal = isLocalVoice(a.identifier) ? 0 : 1;
      const bLocal = isLocalVoice(b.identifier) ? 0 : 1;
      if (aLocal !== bLocal) return aLocal - bLocal;
      return voiceDisplayName(a.identifier).localeCompare(voiceDisplayName(b.identifier));
    });
    const selectedId = config?.ttsVoice;
    const selectedVoice = selectedId && ttsVoices.find((v) => v.identifier === selectedId);

    // Optional: Remove in production

    if (selectedVoice && !sorted.some((v) => v.identifier === selectedId)) {
      return [selectedVoice, ...sorted];
    }
    return sorted;
  }, [ttsVoices, showNetworkVoices, voiceLanguageFilter, config?.ttsVoice]);

  const voiceLanguages = useMemo(() => (
    Array.from(
      new Set(ttsVoices.map((v) => v.language).filter(Boolean))
    ).sort()
  ), [ttsVoices]);


  const updateField = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) => {
    if (!config) return;
    const updated = { ...config, [key]: value };
    setConfig(updated);
    setDirty(true);
  };

  const updateAndSave = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) => {
    if (!config) return;
    const updated = { ...config, [key]: value };
    setConfig(updated);
    saveConfig(updated);
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
    if (!config) return;

    // Always save current values before testing
    await saveConfig(config);
    setDirty(false);

    setConnState("testing");
    setConnMessage(`Testing ${config.agentUrl}...`);
    setBots([]);

    const result = await testConnection();

    if (result.ok) {
      setConnState(result.message.includes("but") ? "partial" : "connected");
      setConnMessage(result.message);

      // Fetch bots if fully connected
      if (!result.message.includes("but")) {
        try {
          const b = await refreshBotCache();
          setBots(b);
        } catch {
          // bots list failed but connection is ok
        }
      }
    } else {
      setConnState("failed");
      setConnMessage(result.message);
    }
  };

  if (!config) return null;

  const connColor: Record<ConnectionState, string> = {
    untested: "#4b5563",
    testing: "#facc15",
    connected: "#4ade80",
    partial: "#fb923c",
    failed: "#ef4444",
  };

  const connLabel: Record<ConnectionState, string> = {
    untested: "Not tested",
    testing: "Testing...",
    connected: "Connected",
    partial: "Partial",
    failed: "Failed",
  };

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

      <Pressable
        style={[styles.testButton, connState === "testing" && styles.testButtonDisabled]}
        onPress={handleTestConnection}
        disabled={connState === "testing"}
      >
        {connState === "testing" ? (
          <View style={styles.testButtonInner}>
            <ActivityIndicator size="small" color="#60a5fa" />
            <Text style={styles.testButtonText}>Testing...</Text>
          </View>
        ) : (
          <Text style={styles.testButtonText}>Test Connection</Text>
        )}
      </Pressable>

      {connState !== "untested" && (
        <View style={styles.connResultBox}>
          <View style={styles.connResultHeader}>
            <View style={[styles.connectionIndicator, { backgroundColor: connColor[connState] }]} />
            <Text style={[styles.connResultLabel, { color: connColor[connState] }]}>
              {connLabel[connState]}
            </Text>
          </View>
          {connMessage ? (
            <Text style={styles.connResultMessage}>{connMessage}</Text>
          ) : null}
        </View>
      )}

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
          {connState !== "connected" && (
            <Text style={styles.hintText}>Test connection to see available bots</Text>
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

      <Text style={styles.label}>TTS Voice</Text>
      <View style={[styles.switchRow, { marginTop: 6 }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.switchLabel}>Local voices only</Text>
          <Text style={[styles.hintText, { marginTop: 4 }]}>
            Local voices start instantly. Network voices can add several seconds delay.
          </Text>
        </View>
        <Switch
          value={!showNetworkVoices}
          onValueChange={(v) => setShowNetworkVoices(!v)}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={!showNetworkVoices ? "#60a5fa" : "#9ca3af"}
        />
      </View>
      {voiceLanguages.length > 1 && (
        <>
          <Text style={[styles.label, { marginTop: 8 }]}>Language</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 4 }} contentContainerStyle={{ gap: 8, flexDirection: "row", paddingVertical: 4 }}>
            <Pressable
              style={[styles.wakeWordChip, voiceLanguageFilter === "all" && styles.wakeWordChipActive]}
              onPress={() => setVoiceLanguageFilter("all")}
            >
              <Text style={[styles.wakeWordText, voiceLanguageFilter === "all" && styles.wakeWordTextActive]}>All</Text>
            </Pressable>
            {voiceLanguages.map((lang) => {
              const isActive = voiceLanguageFilter === lang;
              return (
                <Pressable
                  key={lang}
                  style={[styles.wakeWordChip, isActive && styles.wakeWordChipActive]}
                  onPress={() => setVoiceLanguageFilter(lang)}
                >
                  <Text style={[styles.wakeWordText, isActive && styles.wakeWordTextActive]}>{lang}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </>
      )}
      {ttsVoices.length > 0 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }} contentContainerStyle={{ gap: 8, flexDirection: "row", paddingVertical: 4, flexWrap: "wrap" }}>
          <Pressable
            style={[styles.wakeWordChip, !config.ttsVoice && styles.wakeWordChipActive]}
            onPress={() => updateField("ttsVoice", "")}
          >
            <Text style={[styles.wakeWordText, !config.ttsVoice && styles.wakeWordTextActive]}>Default</Text>
          </Pressable>
          {filteredVoices.map((v) => {
            const isActive = config.ttsVoice === v.identifier;
            const label = voiceDisplayName(v.identifier, v.name && v.name !== v.identifier ? v.name : undefined);
            return (
              <Pressable
                key={v.identifier}
                style={[styles.wakeWordChip, isActive && styles.wakeWordChipActive]}
                onPress={() => updateField("ttsVoice", v.identifier)}
              >
                <Text style={[styles.wakeWordText, isActive && styles.wakeWordTextActive]} numberOfLines={1}>
                  {label}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : (
        <Text style={[styles.hintText, { marginTop: 8 }]}>Loading voices…</Text>
      )}
      <Text style={styles.hintText}>
        {showNetworkVoices ? "Showing all voices. Network voices may have delay." : "Local voices only — start instantly."}
      </Text>

      <Text style={styles.label}>TTS Speed</Text>
      <TextInput
        style={styles.input}
        value={String(config.ttsSpeed)}
        onChangeText={(v) => {
          const n = parseFloat(v);
          if (!Number.isNaN(n) && n > 0) updateField("ttsSpeed", n);
        }}
        placeholder="1.0"
        placeholderTextColor="#6b7280"
        keyboardType="decimal-pad"
      />
      <Text style={styles.hintText}>1.0 = normal; higher = faster.</Text>

      <Text style={styles.label}>Listen sound</Text>
      <View style={styles.wakeWordGrid}>
        {LISTEN_SOUND_PRESETS.map((preset) => {
          const isActive = (config.listenSound || "chime") === preset;
          return (
            <Pressable
              key={preset}
              style={[styles.wakeWordChip, isActive && styles.wakeWordChipActive]}
              onPress={() => updateField("listenSound", preset)}
            >
              <Text style={[styles.wakeWordText, isActive && styles.wakeWordTextActive]}>{preset}</Text>
            </Pressable>
          );
        })}
      </View>
      <Text style={styles.hintText}>Tone played when wake word is detected.</Text>
      <Pressable
        style={[styles.testButton, { marginTop: 8, alignSelf: "flex-start" }]}
        onPress={() => playListenTone((config.listenSound as ListenSoundPreset) || "chime")}
      >
        <Text style={styles.testButtonText}>Play listen tone</Text>
      </Pressable>

      <Text style={styles.label}>Transcription</Text>
      <View style={styles.pickerRow}>
        <Pressable
          style={[
            styles.pickerOption,
            config.transcriptionMode === "server" && styles.pickerOptionSelected,
          ]}
          onPress={() => updateAndSave("transcriptionMode", "server")}
        >
          <Text style={[styles.pickerOptionText, config.transcriptionMode === "server" && styles.pickerOptionTextSelected]}>
            Server (Whisper)
          </Text>
        </Pressable>
        <Pressable
          style={[
            styles.pickerOption,
            config.transcriptionMode === "local" && styles.pickerOptionSelected,
          ]}
          onPress={() => updateAndSave("transcriptionMode", "local")}
        >
          <Text style={[styles.pickerOptionText, config.transcriptionMode === "local" && styles.pickerOptionTextSelected]}>
            Local (Cheetah)
          </Text>
        </Pressable>
      </View>
      <Text style={styles.hintText}>
        {config.transcriptionMode === "local"
          ? "On-device transcription with Picovoice Cheetah. Uses the same Picovoice key as wake word. No audio sent to server for STT."
          : "Send recorded audio to the server for transcription (faster-whisper)."}
      </Text>

      <View style={styles.switchRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.switchLabel}>Native Audio Input</Text>
          <Text style={[styles.hintText, { marginTop: 4 }]}>
            Send audio directly to the AI model instead of transcribing first. Can also be set per-bot in server config.
          </Text>
        </View>
        <Switch
          value={config.audioNative}
          onValueChange={(v) => updateAndSave("audioNative", v)}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={config.audioNative ? "#60a5fa" : "#9ca3af"}
        />
      </View>

      <View style={styles.switchRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.switchLabel}>Overlay</Text>
          {config.overlayEnabled && overlayPermission === false && (
            <Text style={[styles.hintText, { color: "#fb923c", marginTop: 4 }]}>
              Permission required — tap Grant below
            </Text>
          )}
          {config.overlayEnabled && overlayPermission === true && (
            <Text style={[styles.hintText, { color: "#4ade80", marginTop: 4 }]}>
              Permission granted
            </Text>
          )}
        </View>
        <Switch
          value={config.overlayEnabled}
          onValueChange={async (v) => {
            updateField("overlayEnabled", v);
            if (v) {
              const granted = await hasOverlayPermission();
              setOverlayPermission(granted);
              if (!granted) {
                Alert.alert(
                  "Overlay Permission",
                  "To show the voice assistant overlay on top of other apps, you need to grant the \"Display over other apps\" permission. Tap Grant to open Android settings.",
                  [
                    { text: "Later", style: "cancel" },
                    {
                      text: "Grant",
                      onPress: async () => {
                        await requestOverlayPermission();
                      },
                    },
                  ]
                );
              }
              voiceService.checkOverlayPermission();
            }
          }}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={config.overlayEnabled ? "#60a5fa" : "#9ca3af"}
        />
      </View>

      {config.overlayEnabled && overlayPermission === false && (
        <Pressable
          style={[styles.testButton, { backgroundColor: "#78350f" }]}
          onPress={async () => {
            await requestOverlayPermission();
            setTimeout(async () => {
              const granted = await hasOverlayPermission();
              setOverlayPermission(granted);
              voiceService.checkOverlayPermission();
            }, 1000);
          }}
        >
          <Text style={[styles.testButtonText, { color: "#fbbf24" }]}>
            Grant Overlay Permission
          </Text>
        </Pressable>
      )}

      {/* Wake Word */}
      <Text style={[styles.sectionTitle, { marginTop: 28 }]}>Wake Word</Text>

      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>Enable Wake Word</Text>
        <Switch
          value={config.wakeWordEnabled}
          onValueChange={(v) => {
            updateField("wakeWordEnabled", v);
            voiceService.setWakeWordEnabled(v).catch(() => {});
          }}
          trackColor={{ true: "#1d4ed8", false: "#374151" }}
          thumbColor={config.wakeWordEnabled ? "#60a5fa" : "#9ca3af"}
        />
      </View>

      <Text style={styles.label}>Picovoice Access Key</Text>
      <TextInput
        style={styles.input}
        value={config.picovoiceAccessKey}
        onChangeText={(v) => updateField("picovoiceAccessKey", v)}
        placeholder="Get free key at console.picovoice.ai"
        placeholderTextColor="#6b7280"
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
      />
      <Text style={styles.hintText}>
        Free from console.picovoice.ai — no credit card required
      </Text>

      <Text style={styles.label}>Wake Word Gain</Text>
      <TextInput
        style={styles.input}
        value={String(config.wakeWordGain)}
        onChangeText={(v) => {
          const n = parseFloat(v);
          if (!Number.isNaN(n)) updateField("wakeWordGain", n);
        }}
        placeholder="1.0"
        placeholderTextColor="#6b7280"
        keyboardType="decimal-pad"
      />
      <Text style={styles.hintText}>
        Boost mic input for wake word (1.0 = normal, 1.5–2.0 can help on quiet tablets). Restart wake word after changing.
      </Text>

      <Text style={styles.label}>Trim after wake word (ms)</Text>
      <TextInput
        style={styles.input}
        value={String(config.wakeWordTrimMs)}
        onChangeText={(v) => {
          const n = parseInt(v, 10);
          if (!Number.isNaN(n) && n >= 0) updateField("wakeWordTrimMs", n);
        }}
        placeholder="800"
        placeholderTextColor="#6b7280"
        keyboardType="number-pad"
      />
      <Text style={styles.hintText}>
        Ms of recording to drop from the start after wake word so "jarvis" etc. is not transcribed. Default 800.
      </Text>

      <Text style={styles.label}>Keyword</Text>
      <View style={styles.wakeWordGrid}>
        {BUILT_IN_WAKE_WORDS.map((kw) => {
          const isActive = config.wakeWord === kw;
          return (
            <Pressable
              key={kw}
              style={[styles.wakeWordChip, isActive && styles.wakeWordChipActive]}
              onPress={() => updateField("wakeWord", kw)}
            >
              <Text style={[styles.wakeWordText, isActive && styles.wakeWordTextActive]}>
                {kw}
              </Text>
            </Pressable>
          );
        })}
      </View>

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
  testButton: {
    backgroundColor: "#0f3460",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 8,
    marginTop: 14,
    alignItems: "center",
  },
  testButtonDisabled: {
    opacity: 0.7,
  },
  testButtonInner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  testButtonText: {
    color: "#60a5fa",
    fontWeight: "600",
    fontSize: 15,
  },
  connResultBox: {
    marginTop: 10,
    backgroundColor: "#1a1a2e",
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  connResultHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  connectionIndicator: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  connResultLabel: {
    fontSize: 14,
    fontWeight: "700",
  },
  connResultMessage: {
    color: "#9ca3af",
    fontSize: 13,
    marginTop: 6,
    lineHeight: 18,
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
  pickerRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 8,
  },
  pickerOption: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 8,
    backgroundColor: "#1a1a2e",
    borderWidth: 1,
    borderColor: "#2a2a4e",
    alignItems: "center",
  },
  pickerOptionSelected: {
    borderColor: "#60a5fa",
    backgroundColor: "#0f1b3e",
  },
  pickerOptionText: {
    color: "#9ca3af",
    fontSize: 14,
    fontWeight: "500",
  },
  pickerOptionTextSelected: {
    color: "#60a5fa",
  },
  wakeWordGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 4,
  },
  wakeWordChip: {
    backgroundColor: "#1a1a2e",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  wakeWordChipActive: {
    borderColor: "#60a5fa",
    backgroundColor: "#0f1b3e",
  },
  wakeWordText: {
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: "500",
    textTransform: "capitalize",
  },
  wakeWordTextActive: {
    color: "#60a5fa",
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
