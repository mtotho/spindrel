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

// Channel types
export interface Channel {
  id: string;
  client_id: string;
  bot_id: string;
  active_session_id?: string;
  integration_type?: string;
  display_name?: string;
  created_at: string;
  updated_at: string;
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
