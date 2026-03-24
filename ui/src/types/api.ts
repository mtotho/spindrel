// Bot types
export interface MemoryConfig {
  enabled?: boolean;
  cross_channel?: boolean;
  cross_client?: boolean;
  cross_bot?: boolean;
  prompt?: string;
  similarity_threshold?: number;
}

export interface KnowledgeConfig {
  enabled?: boolean;
}

export interface SkillConfig {
  id: string;
  mode?: string;
  similarity_threshold?: number | null;
}

export interface BotConfig {
  id: string;
  name: string;
  model: string;
  system_prompt?: string;
  model_provider_id?: string;
  display_name?: string;
  avatar_url?: string;
  local_tools?: string[];
  mcp_servers?: string[];
  client_tools?: string[];
  pinned_tools?: string[];
  skills?: SkillConfig[];
  tool_retrieval?: boolean;
  tool_similarity_threshold?: number | null;
  tool_result_config?: Record<string, any>;
  compression_config?: Record<string, any>;
  persona?: boolean;
  persona_content?: string;
  context_compaction?: boolean;
  compaction_interval?: number | null;
  compaction_keep_turns?: number | null;
  compaction_model?: string | null;
  audio_input?: string;
  memory?: MemoryConfig;
  memory_max_inject_chars?: number | null;
  knowledge?: KnowledgeConfig;
  knowledge_max_inject_chars?: number | null;
  delegate_bots?: string[];
  harness_access?: string[];
  integration_config?: Record<string, any>;
  workspace?: Record<string, any>;
  docker_sandbox_profiles?: string[];
  delegation_config?: Record<string, any>;
  elevation_enabled?: boolean | null;
  elevation_threshold?: number | null;
  elevated_model?: string | null;
  attachment_summarization_enabled?: boolean | null;
  attachment_summary_model?: string | null;
  attachment_text_max_chars?: number | null;
  attachment_vision_concurrency?: number | null;
  created_at?: string;
  updated_at?: string;
}

// Tool group from editor data
export interface ToolPack {
  pack: string;
  tools: { name: string }[];
}

export interface ToolGroup {
  integration: string;
  is_core: boolean;
  packs: ToolPack[];
  total: number;
}

export interface SkillOption {
  id: string;
  name: string;
  description?: string;
}

export interface BotEditorData {
  bot: BotConfig;
  tool_groups: ToolGroup[];
  mcp_servers: string[];
  client_tools: string[];
  all_skills: SkillOption[];
  all_bots: { id: string; name: string }[];
  all_harnesses: string[];
  all_sandbox_profiles: { name: string; description?: string }[];
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

// Attachment types
export interface AttachmentBrief {
  id: string;
  type: string; // image, file, text, audio, video
  filename: string;
  mime_type: string;
  size_bytes: number;
  description?: string;
  has_file_data: boolean;
}

// Message types
export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  correlation_id?: string;
  tool_calls?: ToolCall[];
  attachments?: AttachmentBrief[];
  created_at: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: string;
}

// Chat types
export interface ChatAttachment {
  type: string;
  content: string; // base64
  mime_type: string;
  name?: string;
}

export interface ChatFileMetadata {
  filename: string;
  mime_type: string;
  size_bytes: number;
  file_data: string; // base64
}

export interface ChatRequest {
  message: string;
  bot_id: string;
  client_id: string;
  session_id?: string;
  channel_id?: string;
  attachments?: ChatAttachment[];
  file_metadata?: ChatFileMetadata[];
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
