import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  PermissionsAndroid,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useFocusEffect } from "expo-router";
import { useKeepAwake } from "expo-keep-awake";
import { voiceService } from "../../src/service/VoiceService";
import { getCachedBot, getSession, healthCheck, type VoiceState } from "../../src/agent";
import { getSessionId } from "../../src/session";
import { loadConfig } from "../../src/config";
import { startForegroundService } from "../../src/native/VoiceServiceBridge";
import { hasOverlayPermission, requestOverlayPermission } from "../../src/native/OverlayBridge";

const SILENT_SPLIT_RE = /(\[silent\][\s\S]*?\[\/silent\])/g;
const SILENT_UNWRAP_RE = /^\[silent\]([\s\S]*?)\[\/silent\]$/;

function MessageText({ text, style }: { text: string; style: any }) {
  if (!text.includes("[silent]")) {
    return <Text style={style}>{text}</Text>;
  }

  const parts = text.split(SILENT_SPLIT_RE);
  return (
    <Text style={style}>
      {parts.map((part, i) => {
        const match = part.match(SILENT_UNWRAP_RE);
        if (match) {
          return (
            <Text key={i} style={{ fontStyle: "italic", opacity: 0.6 }}>
              {match[1]}
            </Text>
          );
        }
        return <Text key={i}>{part}</Text>;
      })}
    </Text>
  );
}

interface Message {
  role: "user" | "assistant" | "status";
  text: string;
  timestamp: number;
}

export default function HomeScreen() {
  useKeepAwake();

  const scrollRef = useRef<ScrollView>(null);
  const micPulse = useRef(new Animated.Value(1)).current;
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [stateDetail, setStateDetail] = useState<string>();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [transcript, setTranscript] = useState<string>();
  const transcriptRef = useRef<string>();
  const [sessionId, setSessionId] = useState<string>("");
  const [botId, setBotId] = useState<string>("default");
  const [audioMode, setAudioMode] = useState<"native" | "stt">("stt");
  const lastLoadedSession = useRef<string>("");

  useEffect(() => {
    healthCheck().then(setConnected);

    const initService = async () => {
      if (Platform.OS === "android") {
        try {
          const micGranted = await PermissionsAndroid.request(
            PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
            {
              title: "Microphone Permission",
              message: "Agent Voice Client needs microphone access for voice commands.",
              buttonPositive: "Allow",
            }
          );
          if (micGranted !== PermissionsAndroid.RESULTS.GRANTED) {
            console.warn("Microphone permission denied — foreground service cannot start");
            return;
          }
        } catch (e) {
          console.warn("Permission request error:", e);
        }
      }

      await startForegroundService().catch((e) =>
        console.warn("Failed to start foreground service:", e)
      );

      const config = await loadConfig();

      if (config.overlayEnabled) {
        const overlayGranted = await hasOverlayPermission().catch(() => false);
        if (!overlayGranted) {
          await requestOverlayPermission().catch(() => {});
        }
        await voiceService.checkOverlayPermission().catch(() => {});
        voiceService.enableBadge().catch(() => {});
      }

      if (config.wakeWordEnabled && config.picovoiceAccessKey) {
        voiceService.setWakeWordEnabled(true).catch((e) =>
          console.warn("Failed to start wake word:", e)
        );
      }
    };

    initService();
  }, []);

  useEffect(() => {
    return voiceService.addListener((state, detail) => {
      setVoiceState(state);
      setStateDetail(detail);
      if (state === "processing" && detail && !detail.startsWith("Using ") && detail !== "Transcribing..." && detail !== "Sending audio...") {
        setTranscript(detail);
        transcriptRef.current = detail;
      }
      if (state === "idle") {
        setTranscript(undefined);
      }
    });
  }, []);

  // Subscribe to messages from wake-word-triggered interactions
  useEffect(() => {
    return voiceService.addMessageListener((userText, assistantText) => {
      addMessage({ role: "user", text: userText, timestamp: Date.now() });
      addMessage({ role: "assistant", text: assistantText, timestamp: Date.now() });
    });
  }, []);

  // Subscribe to transcript events from native audio mode.
  // Updates a pending user message placeholder with what the AI heard.
  const pendingTranscriptIdx = useRef<number | null>(null);
  useEffect(() => {
    return voiceService.addTranscriptListener((transcript) => {
      if (pendingTranscriptIdx.current !== null) {
        setMessages((prev) => {
          const updated = [...prev];
          const idx = pendingTranscriptIdx.current!;
          if (idx < updated.length && updated[idx].role === "user") {
            updated[idx] = { ...updated[idx], text: transcript || "[couldn't hear]" };
          }
          return updated;
        });
      }
    });
  }, []);

  // Show assistant response in chat immediately, before TTS finishes.
  // Starts true so only UI-initiated flows (handleMic/handleSend) arm it.
  const responseHandled = useRef(true);
  useEffect(() => {
    return voiceService.addResponseListener((response) => {
      if (response && !responseHandled.current) {
        responseHandled.current = true;
        addMessage({ role: "assistant", text: response, timestamp: Date.now() });
      }
    });
  }, []);

  const loadSessionHistory = useCallback(async () => {
    const config = await loadConfig();
    setBotId(config.botId);

    const bot = getCachedBot(config.botId);
    const useNative = config.audioNative || bot?.audio_input === "native";
    setAudioMode(useNative ? "native" : "stt");

    const currentId = await getSessionId();
    setSessionId(currentId);

    if (currentId === lastLoadedSession.current) return;
    lastLoadedSession.current = currentId;

    try {
      const detail = await getSession(currentId);
      const loaded: Message[] = [];
      for (const msg of detail.messages) {
        if (msg.role === "system" || msg.role === "tool") continue;
        if (!msg.content) continue;
        loaded.push({
          role: msg.role === "user" ? "user" : "assistant",
          text: msg.content,
          timestamp: new Date(msg.created_at).getTime(),
        });
      }
      setMessages(loaded);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: false }), 100);
    } catch {
      setMessages([]);
    }
  }, []);

  // Load history on mount and when returning from settings (session may have changed)
  useFocusEffect(
    useCallback(() => {
      loadSessionHistory();
    }, [loadSessionHistory])
  );

  useEffect(() => {
    if (voiceState === "listening") {
      const pulse = Animated.loop(
        Animated.sequence([
          Animated.timing(micPulse, { toValue: 1.15, duration: 600, useNativeDriver: true }),
          Animated.timing(micPulse, { toValue: 1, duration: 600, useNativeDriver: true }),
        ])
      );
      pulse.start();
      return () => pulse.stop();
    } else {
      micPulse.setValue(1);
    }
  }, [voiceState, micPulse]);

  const addMessage = (msg: Message) => {
    setMessages((prev) => [...prev, msg]);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || voiceState === "processing") return;

    setInput("");
    addMessage({ role: "user", text, timestamp: Date.now() });
    responseHandled.current = false;

    try {
      await voiceService.processTranscript(text);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Request failed";
      addMessage({ role: "status", text: `Error: ${msg}`, timestamp: Date.now() });
    }
  };

  const handleMic = async () => {
    if (voiceState === "listening") {
      voiceService.stop();
      return;
    }
    if (voiceState !== "idle") return;

    transcriptRef.current = undefined;
    pendingTranscriptIdx.current = null;
    responseHandled.current = false;

    try {
      const config = await loadConfig();
      const bot = getCachedBot(config.botId);
      const useNative = config.audioNative || bot?.audio_input === "native";

      if (useNative) {
        setMessages((prev) => {
          pendingTranscriptIdx.current = prev.length;
          return [...prev, { role: "user", text: "...", timestamp: Date.now() }];
        });
        setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
      }

      await voiceService.processVoice();
      const spokenText = transcriptRef.current;
      transcriptRef.current = undefined;

      if (!useNative && spokenText) {
        addMessage({ role: "user", text: spokenText, timestamp: Date.now() });
      }

      pendingTranscriptIdx.current = null;
    } catch (error) {
      pendingTranscriptIdx.current = null;
      const msg = error instanceof Error ? error.message : "Voice input failed";
      addMessage({ role: "status", text: `Error: ${msg}`, timestamp: Date.now() });
    }
  };

  const busy = voiceState === "processing" || voiceState === "responding";

  const stateColor = {
    idle: "#4ade80",
    listening: "#facc15",
    processing: "#60a5fa",
    responding: "#c084fc",
  }[voiceState];

  const stateLabel = {
    idle: "Ready",
    listening: "Listening...",
    processing: stateDetail || "Processing...",
    responding: "Speaking...",
  }[voiceState];

  return (
    <View style={styles.container}>
      {/* Status bar */}
      <View style={styles.statusBar}>
        <View style={[styles.statusDot, { backgroundColor: stateColor }]} />
        <Text style={styles.statusText} numberOfLines={1}>{stateLabel}</Text>
        <View style={styles.statusRight}>
          <Text style={styles.botLabel}>{botId}</Text>
          <Text style={[styles.audioModeLabel, audioMode === "native" && styles.audioModeNative]}>
            {audioMode === "native" ? "native" : "stt"}
          </Text>
          {sessionId ? (
            <Text style={styles.sessionLabel}>{sessionId.slice(0, 6)}</Text>
          ) : null}
          <View
            style={[
              styles.connectionDot,
              { backgroundColor: connected ? "#4ade80" : connected === false ? "#ef4444" : "#6b7280" },
            ]}
          />
        </View>
      </View>

      {/* Messages */}
      <ScrollView ref={scrollRef} style={styles.messages} contentContainerStyle={styles.messagesContent}>
        {messages.length === 0 && (
          <Text style={styles.emptyText}>
            Type a message or tap the mic button to speak.
          </Text>
        )}
        {messages.map((msg, i) => (
          <View
            key={`${sessionId}-${i}`}
            style={[
              styles.messageBubble,
              msg.role === "user"
                ? styles.userBubble
                : msg.role === "assistant"
                  ? styles.assistantBubble
                  : styles.statusBubble,
            ]}
          >
            {msg.role === "assistant" ? (
              <MessageText text={msg.text} style={styles.messageText} />
            ) : (
              <Text
                style={[
                  styles.messageText,
                  msg.role === "status" && styles.statusMessageText,
                ]}
              >
                {msg.text}
              </Text>
            )}
          </View>
        ))}
      </ScrollView>

      {/* Input */}
      <View style={styles.inputRow}>
        <Animated.View style={{ transform: [{ scale: micPulse }] }}>
          <Pressable
            style={[
              styles.micButton,
              voiceState === "listening" && styles.micButtonActive,
              busy && styles.micButtonDisabled,
            ]}
            onPress={handleMic}
            disabled={busy}
          >
            <Text style={styles.micIcon}>
              {voiceState === "listening" ? "⏹" : "🎤"}
            </Text>
          </Pressable>
        </Animated.View>

        <TextInput
          style={styles.textInput}
          value={input}
          onChangeText={setInput}
          placeholder="Type a message..."
          placeholderTextColor="#6b7280"
          returnKeyType="send"
          onSubmitEditing={handleSend}
          editable={!busy && voiceState !== "listening"}
        />
        <Pressable
          style={[styles.sendButton, (busy || voiceState === "listening") && styles.sendButtonDisabled]}
          onPress={handleSend}
          disabled={busy || voiceState === "listening"}
        >
          <Text style={styles.sendButtonText}>
            {busy ? "..." : "Send"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#16213e",
  },
  statusBar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: "#1a1a2e",
    borderBottomWidth: 1,
    borderBottomColor: "#2a2a4e",
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  statusText: {
    color: "#e0e0e0",
    fontSize: 14,
    flex: 1,
  },
  statusRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  botLabel: {
    color: "#60a5fa",
    fontSize: 12,
    fontWeight: "600",
  },
  audioModeLabel: {
    color: "#6b7280",
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    backgroundColor: "#2a2a4e",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  audioModeNative: {
    color: "#fbbf24",
    backgroundColor: "#422006",
  },
  sessionLabel: {
    color: "#6b7280",
    fontSize: 11,
    fontFamily: "monospace",
  },
  connectionDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  messages: {
    flex: 1,
  },
  messagesContent: {
    padding: 16,
    gap: 12,
  },
  emptyText: {
    color: "#6b7280",
    textAlign: "center",
    marginTop: 40,
    fontSize: 15,
    lineHeight: 22,
  },
  messageBubble: {
    padding: 12,
    borderRadius: 12,
    maxWidth: "85%",
  },
  userBubble: {
    backgroundColor: "#0f3460",
    alignSelf: "flex-end",
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: "#1a1a2e",
    alignSelf: "flex-start",
    borderBottomLeftRadius: 4,
  },
  statusBubble: {
    backgroundColor: "transparent",
    alignSelf: "center",
    paddingVertical: 4,
  },
  messageText: {
    color: "#e0e0e0",
    fontSize: 15,
    lineHeight: 22,
  },
  statusMessageText: {
    color: "#6b7280",
    fontSize: 13,
    fontStyle: "italic",
  },
  inputRow: {
    flexDirection: "row",
    padding: 12,
    gap: 8,
    backgroundColor: "#1a1a2e",
    borderTopWidth: 1,
    borderTopColor: "#2a2a4e",
    alignItems: "center",
  },
  micButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "#16213e",
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 2,
    borderColor: "#2a2a4e",
  },
  micButtonActive: {
    backgroundColor: "#7f1d1d",
    borderColor: "#ef4444",
  },
  micButtonDisabled: {
    opacity: 0.4,
  },
  micIcon: {
    fontSize: 20,
  },
  textInput: {
    flex: 1,
    backgroundColor: "#16213e",
    color: "#e0e0e0",
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  sendButton: {
    backgroundColor: "#0f3460",
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 8,
    justifyContent: "center",
  },
  sendButtonDisabled: {
    opacity: 0.5,
  },
  sendButtonText: {
    color: "#60a5fa",
    fontWeight: "600",
    fontSize: 15,
  },
});
