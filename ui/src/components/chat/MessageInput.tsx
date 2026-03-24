import { useState, useRef } from "react";
import { View, TextInput, Pressable, Platform } from "react-native";
import { Send } from "lucide-react";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function MessageInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<TextInput>(null);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    inputRef.current?.focus();
  };

  const handleKeyPress = (e: any) => {
    // Cmd/Ctrl+Enter to send on web
    if (Platform.OS === "web" && e.nativeEvent?.key === "Enter" && !e.nativeEvent?.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <View className="flex-row items-end gap-2 p-4 border-t border-surface-border bg-surface">
      <TextInput
        ref={inputRef}
        className="flex-1 bg-surface-raised border border-surface-border rounded-xl px-4 py-3 text-text text-sm min-h-[44px] max-h-[120px]"
        placeholder="Type a message..."
        placeholderTextColor="#666666"
        value={text}
        onChangeText={setText}
        onKeyPress={handleKeyPress}
        multiline
        editable={!disabled}
        autoFocus={Platform.OS === "web"}
      />
      <Pressable
        onPress={handleSend}
        disabled={!text.trim() || disabled}
        className={`w-11 h-11 rounded-xl items-center justify-center ${
          text.trim() && !disabled ? "bg-accent" : "bg-surface-raised"
        }`}
      >
        <Send
          size={18}
          color={text.trim() && !disabled ? "white" : "#666666"}
        />
      </Pressable>
    </View>
  );
}
