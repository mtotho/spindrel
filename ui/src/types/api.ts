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
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
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
  persona?: boolean;
  persona_content?: string;
  persona_from_workspace?: boolean;
  workspace_persona_content?: string | null;
  context_compaction?: boolean;
  compaction_interval?: number | null;
  compaction_keep_turns?: number | null;
  compaction_model?: string | null;
  history_mode?: string | null;
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
  model_params?: Record<string, any>;
  delegation_config?: Record<string, any>;
  user_id?: string | null;
  shared_workspace_id?: string | null;
  shared_workspace_role?: string | null;
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

export interface WorkspaceSkill {
  skill_id: string;
  name: string;
  mode: string;
  source_path: string;
  bot_id?: string | null;
  workspace_id: string;
  workspace_name?: string;
  chunk_count: number;
}

export interface ModelParamDefinition {
  name: string;
  label: string;
  description: string;
  type: "slider" | "number" | "select";
  min?: number;
  max?: number;
  step?: number;
  default: number | string | null;
  options?: string[];
}

export interface BotEditorData {
  bot: BotConfig;
  tool_groups: ToolGroup[];
  mcp_servers: string[];
  client_tools: string[];
  all_skills: SkillOption[];
  workspace_skills: WorkspaceSkill[];
  all_bots: { id: string; name: string }[];
  all_harnesses: string[];
  all_sandbox_profiles: { name: string; description?: string }[];
  model_param_definitions: ModelParamDefinition[];
  model_param_support: Record<string, string[]>;
}

// Integration binding
export interface IntegrationBinding {
  id: string;
  channel_id: string;
  integration_type: string;
  client_id: string;
  dispatch_config?: Record<string, any> | null;
  display_name?: string | null;
  created_at: string;
  updated_at: string;
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
  private: boolean;
  user_id?: string;
  display_name?: string;
  model_override?: string;
  model_provider_id_override?: string;
  integrations?: IntegrationBinding[];
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
  private: boolean;
  user_id?: string | null;
  allow_bot_messages: boolean;
  workspace_rag: boolean;
  max_iterations?: number;
  task_max_run_seconds?: number | null;
  channel_prompt?: string;
  context_compaction: boolean;
  compaction_interval?: number;
  compaction_keep_turns?: number;
  memory_knowledge_compaction_prompt?: string;
  compaction_prompt_template_id?: string | null;
  compaction_workspace_file_path?: string | null;
  compaction_workspace_id?: string | null;
  history_mode?: string | null;
  compaction_model?: string;
  trigger_heartbeat_before_compaction?: boolean | null;
  section_index_count?: number | null;
  section_index_verbosity?: string | null;
  elevation_enabled?: boolean;
  elevation_threshold?: number;
  elevated_model?: string;
  model_override?: string;
  model_provider_id_override?: string;
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
  // Tool / skill overrides
  local_tools_override?: string[] | null;
  local_tools_disabled?: string[] | null;
  mcp_servers_override?: string[] | null;
  mcp_servers_disabled?: string[] | null;
  client_tools_override?: string[] | null;
  client_tools_disabled?: string[] | null;
  pinned_tools_override?: string[] | null;
  skills_override?: { id: string; mode?: string; similarity_threshold?: number }[] | null;
  skills_disabled?: string[] | null;
  // Workspace overrides
  workspace_skills_enabled?: boolean | null;
  workspace_base_prompt_enabled?: boolean | null;
}

export interface EffectiveTools {
  local_tools: string[];
  mcp_servers: string[];
  client_tools: string[];
  pinned_tools: string[];
  skills: { id: string; mode: string; similarity_threshold?: number }[];
  mode: Record<string, "inherit" | "override" | "disabled">;
}

// Elevation types
export interface ElevationLogEntry {
  id: string;
  turn_id?: string;
  bot_id: string;
  channel_id?: string;
  iteration: number;
  base_model: string;
  model_chosen: string;
  was_elevated: boolean;
  classifier_score: number;
  elevation_reason?: string;
  rules_fired: string[];
  signal_scores: Record<string, number>;
  tokens_used?: number;
  latency_ms?: number;
  created_at: string;
}

export interface ElevationConfigOut {
  enabled?: boolean;
  threshold?: number;
  elevated_model?: string;
  effective_enabled: boolean;
  effective_threshold: number;
  effective_elevated_model: string;
}

export interface ElevationOverview {
  config: ElevationConfigOut;
  recent: ElevationLogEntry[];
  stats: {
    total_decisions: number;
    elevated_count: number;
    elevation_rate: number;
    avg_score: number;
    avg_latency_ms?: number;
  };
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
  metadata?: Record<string, any>;
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
  model_override?: string;
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

// Auth types
export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  integration_config: Record<string, any>;
  is_admin: boolean;
  auth_method: string;
}

export interface AuthStatus {
  setup_required: boolean;
  google_enabled: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

// Shared Workspace types
export interface WorkspaceBot {
  bot_id: string;
  bot_name: string;
  role: string;
  cwd_override?: string | null;
  user_id?: string | null;
}

export interface SharedWorkspace {
  id: string;
  name: string;
  description?: string | null;
  image: string;
  network: string;
  env: Record<string, string>;
  ports: any[];
  mounts: any[];
  cpus?: number | null;
  memory_limit?: string | null;
  docker_user?: string | null;
  read_only_root: boolean;
  startup_script?: string | null;
  workspace_skills_enabled: boolean;
  workspace_base_prompt_enabled: boolean;
  container_id?: string | null;
  container_name?: string | null;
  status: string;
  image_id?: string | null;
  last_started_at?: string | null;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
  bots: WorkspaceBot[];
}

export interface WorkspaceCreate {
  name: string;
  description?: string;
  image?: string;
  network?: string;
  env?: Record<string, string>;
  ports?: any[];
  mounts?: any[];
  cpus?: number;
  memory_limit?: string;
  docker_user?: string;
  read_only_root?: boolean;
  startup_script?: string;
  workspace_skills_enabled?: boolean;
  workspace_base_prompt_enabled?: boolean;
  created_by_user_id?: string;
}

export interface WorkspaceUpdate {
  name?: string;
  description?: string;
  image?: string;
  network?: string;
  env?: Record<string, string>;
  ports?: any[];
  mounts?: any[];
  cpus?: number;
  memory_limit?: string;
  docker_user?: string;
  read_only_root?: boolean;
  startup_script?: string;
  workspace_skills_enabled?: boolean;
  workspace_base_prompt_enabled?: boolean;
}

export interface WorkspaceFileEntry {
  name: string;
  is_dir: boolean;
  size?: number | null;
  path: string;
  modified_at?: number | null; // unix timestamp (seconds)
}

// Context breakdown types
export interface ContextCategory {
  key: string;
  label: string;
  chars: number;
  tokens_approx: number;
  percentage: number;
  category: "static" | "rag" | "conversation" | "compaction";
  description: string;
}

export interface CompactionState {
  enabled: boolean;
  has_summary: boolean;
  summary_chars: number;
  messages_since_watermark: number;
  total_messages: number;
  compaction_interval: number;
  compaction_keep_turns: number;
  turns_until_next: number | null;
}

export interface RerankState {
  enabled: boolean;
  model: string;
  threshold_chars: number;
  max_chunks: number;
  total_rag_chars: number;
  would_rerank: boolean;
}

export interface EffectiveSetting {
  value: any;
  source: "channel" | "bot" | "global";
}

export interface ContextBreakdown {
  channel_id: string;
  session_id: string | null;
  bot_id: string;
  categories: ContextCategory[];
  total_chars: number;
  total_tokens_approx: number;
  compaction: CompactionState;
  reranking: RerankState;
  effective_settings: Record<string, EffectiveSetting>;
  disclaimer: string;
}

// Prompt Template types
export interface PromptTemplate {
  id: string;
  name: string;
  description?: string | null;
  content: string;
  category?: string | null;
  tags: string[];
  workspace_id?: string | null;
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

// Admin types
export interface AdminStats {
  sessions: number;
  memories: number;
  knowledge: number;
  tools: number;
  sandboxes: number;
}
