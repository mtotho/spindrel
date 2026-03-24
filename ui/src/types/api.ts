// Bot types
export interface BotConfig {
  id: string;
  name: string;
  model: string;
  model_provider_id?: string;
  system_prompt?: string;
  local_tools?: string[];
  mcp_servers?: string[];
  client_tools?: string[];
  skills?: string[];
  pinned_tools?: string[];
  tool_retrieval?: boolean;
  audio_input?: string;
  context_compaction?: boolean;
  memory?: { enabled?: boolean; cross_channel?: boolean };
  knowledge?: { enabled?: boolean };
  persona?: boolean;
  delegate_bots?: string[];
  harness_access?: string[];
  slack_display_name?: string;
  slack_icon_emoji?: string;
}

// Channel types (matches server ChannelOut)
export interface Channel {
  id: string;
  name: string;
  bot_id: string;
  client_id?: string;
  integration?: string;
  active_session_id?: string;
  require_mention: boolean;
  passive_memory: boolean;
  display_name?: string;
  created_at: string;
  updated_at: string;
}

// Full channel settings (matches server ChannelSettingsOut)
export interface ChannelSettings {
  id: string;
  name: string;
  bot_id: string;
  client_id?: string;
  integration?: string;
  active_session_id?: string;
  require_mention: boolean;
  passive_memory: boolean;
  workspace_rag: boolean;
  context_compaction: boolean;
  compaction_interval?: number;
  compaction_keep_turns?: number;
  memory_knowledge_compaction_prompt?: string;
  context_compression?: boolean;
  compression_model?: string;
  compression_threshold?: number;
  compression_keep_turns?: number;
  elevation_enabled?: boolean;
  elevation_threshold?: number;
  elevated_model?: string;
}

// Model types
export interface LlmModel {
  id: string;
  display: string;
  max_tokens?: number;
}

export interface ModelGroup {
  provider_id?: string;
  provider_name: string;
  provider_type: string;
  models: LlmModel[];
}

// Completions for @-tag autocomplete
export interface CompletionItem {
  value: string;
  label: string;
}

// Session types
export interface Session {
  id: string;
  bot_id: string;
  client_id?: string;
  channel_id?: string;
  parent_session_id?: string;
  root_session_id?: string;
  depth: number;
  created_at: string;
  updated_at: string;
  summary?: string;
}

// Message types
export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  correlation_id?: string;
  tool_calls?: ToolCall[];
  created_at: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: string;
}

// Chat types
export interface ChatRequest {
  message: string;
  bot_id: string;
  client_id: string;
  session_id?: string;
  channel_id?: string;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  client_actions?: ClientAction[];
}

export interface ClientAction {
  action: string;
  params?: Record<string, unknown>;
}

// SSE event types
export type SSEEventType =
  | "skill_context"
  | "memory_context"
  | "knowledge_context"
  | "tool_start"
  | "tool_request"
  | "tool_result"
  | "transcript"
  | "response"
  | "compaction_start"
  | "compaction_done"
  | "error"
  | "queued"
  | "passive_stored";

export interface SSEEvent {
  event: SSEEventType;
  data: unknown;
}

// Admin types
export interface AdminStats {
  sessions: number;
  memories: number;
  knowledge: number;
  tools: number;
  sandboxes: number;
}
