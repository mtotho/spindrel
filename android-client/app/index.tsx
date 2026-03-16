import { useEffect, useRef, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useRouter } from "expo-router";
import { useKeepAwake } from "expo-keep-awake";
import { voiceService } from "../src/service/VoiceService";
import { healthCheck, type VoiceState } from "../src/agent";

interface Message {
  role: "user" | "assistant" | "status";
  text: string;
  timestamp: number;
}

export default function HomeScreen() {
  useKeepAwake();

  const router = useRouter();
  const scrollRef = useRef<ScrollView>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [stateDetail, setStateDetail] = useState<string>();
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    healthCheck().then(setConnected);
  }, []);

  useEffect(() => {
    return voiceService.addListener((state, detail) => {
      setVoiceState(state);
      setStateDetail(detail);
    });
  }, []);

  const addMessage = (msg: Message) => {
    setMessages((prev) => [...prev, msg]);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || voiceState === "processing") return;

    setInput("");
    addMessage({ role: "user", text, timestamp: Date.now() });

    try {
      const response = await voiceService.processTranscript(text);
      if (response) {
        addMessage({ role: "assistant", text: response, timestamp: Date.now() });
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Request failed";
      addMessage({ role: "status", text: `Error: ${msg}`, timestamp: Date.now() });
    }
  };

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
        <Text style={styles.statusText}>{stateLabel}</Text>
        <View style={styles.statusRight}>
          <View
            style={[
              styles.connectionDot,
              { backgroundColor: connected ? "#4ade80" : connected === false ? "#ef4444" : "#6b7280" },
            ]}
          />
          <Pressable onPress={() => router.push("/settings")} style={styles.settingsButton}>
            <Text style={styles.settingsIcon}>⚙</Text>
          </Pressable>
        </View>
      </View>

      {/* Messages */}
      <ScrollView ref={scrollRef} style={styles.messages} contentContainerStyle={styles.messagesContent}>
        {messages.length === 0 && (
          <Text style={styles.emptyText}>
            Type a message below or configure settings to get started.
          </Text>
        )}
        {messages.map((msg, i) => (
          <View
            key={i}
            style={[
              styles.messageBubble,
              msg.role === "user"
                ? styles.userBubble
                : msg.role === "assistant"
                  ? styles.assistantBubble
                  : styles.statusBubble,
            ]}
          >
            <Text
              style={[
                styles.messageText,
                msg.role === "status" && styles.statusMessageText,
              ]}
            >
              {msg.text}
            </Text>
          </View>
        ))}
      </ScrollView>

      {/* Input */}
      <View style={styles.inputRow}>
        <TextInput
          style={styles.textInput}
          value={input}
          onChangeText={setInput}
          placeholder="Type a message..."
          placeholderTextColor="#6b7280"
          returnKeyType="send"
          onSubmitEditing={handleSend}
          editable={voiceState !== "processing"}
        />
        <Pressable
          style={[styles.sendButton, voiceState === "processing" && styles.sendButtonDisabled]}
          onPress={handleSend}
          disabled={voiceState === "processing"}
        >
          <Text style={styles.sendButtonText}>
            {voiceState === "processing" ? "..." : "Send"}
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
  connectionDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  settingsButton: {
    padding: 4,
  },
  settingsIcon: {
    fontSize: 20,
    color: "#9ca3af",
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
