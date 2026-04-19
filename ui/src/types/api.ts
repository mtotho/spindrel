// Secret check types
export interface SecretCheckResult {
  has_secrets: boolean;
  exact_matches: number;
  pattern_matches: Array<{
    type: string;
  }>;
}

// Bot types
export interface MemoryConfig {
  enabled?: boolean;
  cross_channel?: boolean;
  cross_client?: boolean;
  cross_bot?: boolean;
  prompt?: string;
  similarity_threshold?: number;
}

export interface SkillConfig {
  id: string;
  mode?: string;
}

export interface BotConfig {
  id: string;
  name: string;
  model: string;
  system_prompt?: string;
  model_provider_id?: string | null;
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
  display_name?: string;
  avatar_url?: string;
  local_tools?: string[];
  mcp_servers?: string[];
  client_tools?: string[];
  pinned_tools?: string[];
  skills?: SkillConfig[];
  tool_retrieval?: boolean;
  tool_discovery?: boolean;
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
  compaction_model_provider_id?: string | null;
  history_mode?: string | null;
  audio_input?: string;
  memory?: MemoryConfig;
  memory_max_inject_chars?: number | null;
  delegate_bots?: string[];
  integration_config?: Record<string, any>;
  workspace?: Record<string, any>;
  docker_sandbox_profiles?: string[];
  model_params?: Record<string, any>;
  delegation_config?: Record<string, any>;
  user_id?: string | null;
  shared_workspace_id?: string | null;
  shared_workspace_role?: string | null;
  attachment_summarization_enabled?: boolean | null;
  attachment_summary_model?: string | null;
  attachment_summary_model_provider_id?: string | null;
  attachment_text_max_chars?: number | null;
  attachment_vision_concurrency?: number | null;
  api_permissions?: string[] | null;
  memory_scheme?: string | null;  // "workspace-files"|null
  memory_hygiene_enabled?: boolean | null;
  memory_hygiene_interval_hours?: number | null;
  memory_hygiene_prompt?: string | null;
  memory_hygiene_only_if_active?: boolean | null;
  memory_hygiene_model?: string | null;
  memory_hygiene_model_provider_id?: string | null;
  memory_hygiene_target_hour?: number | null;
  memory_hygiene_extra_instructions?: string | null;
  skill_review_enabled?: boolean | null;
  skill_review_interval_hours?: number | null;
  skill_review_prompt?: string | null;
  skill_review_only_if_active?: boolean | null;
  skill_review_model?: string | null;
  skill_review_model_provider_id?: string | null;
  skill_review_target_hour?: number | null;
  skill_review_extra_instructions?: string | null;
  carapaces?: string[];
  system_prompt_workspace_file?: boolean;
  system_prompt_write_protected?: boolean;
  source_type?: string;  // "system"|"file"|"manual"
  created_at?: string;
  updated_at?: string;
}

export interface Carapace {
  id: string;
  name: string;
  description?: string | null;
  local_tools: string[];
  mcp_tools: string[];
  pinned_tools: string[];
  system_prompt_fragment?: string | null;
  includes: string[];
  tags: string[];
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

// Workflows
export interface Workflow {
  id: string;
  name: string;
  description?: string | null;
  params: Record<string, any>;
  secrets: string[];
  defaults: Record<string, any>;
  steps: WorkflowStep[];
  triggers: Record<string, boolean>;
  tags: string[];
  session_mode: string;
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowStep {
  id: string;
  type?: 'agent' | 'tool' | 'exec';
  prompt?: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  working_directory?: string;
  args?: string[];
  when?: Record<string, any> | null;
  requires_approval?: boolean;
  on_failure?: string;
  secrets?: string[];
  tools?: string[];
  carapaces?: string[];
  model?: string | null;
  timeout?: number | null;
  inject_prior_results?: boolean;
  prior_result_max_chars?: number | null;
  result_max_chars?: number | null;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  bot_id: string;
  channel_id?: string | null;
  session_id?: string | null;
  params: Record<string, any>;
  status: string;
  current_step_index: number;
  step_states: WorkflowStepState[];
  dispatch_type: string;
  dispatch_config?: Record<string, any> | null;
  triggered_by?: string | null;
  session_mode: string;
  error?: string | null;
  workflow_snapshot?: Record<string, any> | null;
  created_at: string;
  completed_at?: string | null;
}

export interface WorkflowStepState {
  status: string;
  task_id?: string | null;
  result?: string | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  correlation_id?: string | null;
  retry_count?: number;
}

export interface WorkflowConnection {
  type: "heartbeat" | "scheduled_task";
  workflow_id: string;
  // heartbeat fields
  enabled?: boolean;
  interval_minutes?: number;
  // scheduled_task fields
  task_id?: string;
  workflow_session_mode?: string | null;
  recurrence?: string | null;
  status?: string;
  title?: string | null;
  bot_id?: string;
  scheduled_at?: string | null;
}

// Tool group from editor data
export interface ToolPack {
  pack: string;
  label: string;
  group?: string | null;
  warning?: string | null;
  tools: { name: string; description?: string | null }[];
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
  source_type?: string;
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

export interface ResolvedToolEntry {
  name: string;
  source: string;       // "bot", "carapace:<id>", "memory_scheme"
  source_label: string;  // human-readable
  integration: string;
}

export interface ResolvedPreview {
  tools: ResolvedToolEntry[];
  pinned_tools: ResolvedToolEntry[];
  mcp_servers: ResolvedToolEntry[];
}

export interface BotEditorData {
  bot: BotConfig;
  tool_groups: ToolGroup[];
  mcp_servers: string[];
  client_tools: string[];
  all_skills: SkillOption[];
  all_bots: { id: string; name: string }[];
  all_sandbox_profiles: { name: string; description?: string }[];
  model_param_definitions: ModelParamDefinition[];
  model_param_support: Record<string, string[]>;
  resolved_preview?: ResolvedPreview | null;
  starter_skill_ids?: string[];
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

// Chat HUD — integration-declared widgets in chat view
export interface HudOnClick {
  type: "link" | "action" | "refresh";
  href?: string;
  endpoint?: string;
  method?: string;
  body?: Record<string, any>;
  confirm?: string;
}

export interface HudItem {
  type: "badge" | "action" | "divider" | "text" | "progress" | "group";
  label?: string;
  value?: string;
  icon?: string;
  variant?: "default" | "success" | "warning" | "danger" | "accent" | "muted";
  on_click?: HudOnClick;
  max?: number; // for progress items
  items?: HudItem[]; // for group items
}

export interface HudData {
  visible: boolean;
  items: HudItem[];
}

export interface ChatHudWidget {
  id: string;
  style: "status_strip" | "side_panel" | "input_bar" | "floating_action";
  endpoint?: string;
  iframe_path?: string;
  poll_interval?: number;
  label?: string;
  icon?: string;
  width?: number;
  collapsed_by_default?: boolean;
  on_click?: HudOnClick;
  badge_endpoint?: string;
}

// Integration activation
export interface ChatHudPreset {
  label: string;
  widgets: string[];
  description?: string;
}

export interface ConfigField {
  key: string;
  type: "string" | "boolean" | "number" | "select" | "multiselect" | "browse";
  label: string;
  description?: string;
  default?: any;
  options?: { value: string; label: string }[];
  source_integration?: string;
  browse_endpoint?: string;
}

export interface ActivatableIntegration {
  integration_type: string;
  description: string;
  requires_workspace: boolean;
  activated: boolean;
  carapaces: string[];
  tools: string[];
  has_system_prompt: boolean;
  version?: string | null;
  includes: string[];
  chat_hud?: ChatHudWidget[];
  chat_hud_presets?: Record<string, ChatHudPreset>;
  activation_config?: Record<string, any>;
  config_fields?: ConfigField[];
  included_by?: string[];
}

export interface ActivationResult {
  integration_type: string;
  activated: boolean;
  manifest?: Record<string, any> | null;
  warnings: Array<{ code: string; message: string }>;
}

export interface ChannelBotMemberConfig {
  max_rounds?: number | null;
  auto_respond?: boolean;
  response_style?: "brief" | "normal" | "detailed" | null;
  system_prompt_addon?: string | null;
  model_override?: string | null;
  priority?: number;
}

export interface ChannelBotMember {
  id: string;
  channel_id: string;
  bot_id: string;
  bot_name?: string;
  config: ChannelBotMemberConfig;
  created_at: string;
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
  protected?: boolean;
  user_id?: string;
  display_name?: string;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  integrations?: IntegrationBinding[];
  member_bots?: ChannelBotMember[];
  heartbeat_enabled?: boolean;
  heartbeat_in_quiet_hours?: boolean;
  channel_workspace_enabled?: boolean;
  workspace_id?: string | null;
  resolved_workspace_id?: string | null;
  config?: {
    pinned_panels?: PinnedPanel[];
    pinned_widgets?: PinnedWidget[];
    /** Pipeline-mode override. Controls whether the channel shows the
     *  pipeline launchpad + Findings panel chrome. "auto" (default):
     *  visible when \u22651 subscription exists. "on": always visible.
     *  "off": hidden even when subscriptions exist. */
    pipeline_mode?: "auto" | "on" | "off";
  };
  category?: string | null;
  tags?: string[];
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PinnedPanel {
  path: string;
  position: "right" | "bottom";
  pinned_at: string;
  pinned_by: string;
}

/** A tool result widget pinned to the side panel for persistent access. */
export interface PinnedWidget {
  id: string;
  tool_name: string;
  display_name: string;
  bot_id: string;
  envelope: ToolResultEnvelope;
  position: number;
  pinned_at: string;
  /** Per-pin user config — shallow-merged over the template's default_config
   *  and exposed as `{{config.*}}` in widget + state_poll templates. Flipped
   *  via `{dispatch: "widget_config"}` actions. */
  config?: Record<string, unknown>;
}

/** A widget pinned to the chat-less `/widgets` dashboard. Row shape mirrors
 *  `channel.config.pinned_widgets[]` so the same renderer handles both. */
export interface WidgetDashboardPin {
  id: string;
  dashboard_key: string;
  position: number;
  source_kind: "channel" | "adhoc";
  source_channel_id: string | null;
  source_bot_id: string | null;
  tool_name: string;
  tool_args: Record<string, unknown>;
  widget_config: Record<string, unknown>;
  envelope: ToolResultEnvelope;
  display_label: string | null;
  grid_layout: GridLayoutItem | Record<string, never>;
  pinned_at: string | null;
  updated_at: string | null;
}

/** {x, y, w, h} in the 12-column dashboard grid. Empty object when unset. */
export interface GridLayoutItem {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Discriminator telling `PinnedToolWidget` which surface it lives on. */
export type WidgetScope =
  | { kind: "channel"; channelId: string }
  | { kind: "dashboard" };

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
  protected?: boolean;
  user_id?: string | null;
  allow_bot_messages: boolean;
  workspace_rag: boolean;
  thinking_display?: string;
  tool_output_display?: string;
  max_iterations?: number;
  task_max_run_seconds?: number | null;
  channel_prompt?: string;
  channel_prompt_workspace_file_path?: string | null;
  channel_prompt_workspace_id?: string | null;
  context_compaction: boolean;
  compaction_interval?: number;
  compaction_keep_turns?: number;
  memory_knowledge_compaction_prompt?: string;
  compaction_prompt_template_id?: string | null;
  compaction_workspace_file_path?: string | null;
  compaction_workspace_id?: string | null;
  history_mode?: string | null;
  compaction_model?: string;
  compaction_model_provider_id?: string | null;
  trigger_heartbeat_before_compaction?: boolean | null;
  // Memory flush (dedicated pre-compaction memory save)
  memory_flush_enabled?: boolean | null;
  memory_flush_model?: string | null;
  memory_flush_model_provider_id?: string | null;
  memory_flush_prompt?: string | null;
  memory_flush_prompt_template_id?: string | null;
  memory_flush_workspace_file_path?: string | null;
  memory_flush_workspace_id?: string | null;
  section_index_count?: number | null;
  section_index_verbosity?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
  // Tool / skill restrictions
  local_tools_disabled?: string[] | null;
  mcp_servers_disabled?: string[] | null;
  client_tools_disabled?: string[] | null;
  // Workspace overrides
  workspace_base_prompt_enabled?: boolean | null;
  // Channel workspace
  channel_workspace_enabled?: boolean | null;
  workspace_schema_template_id?: string | null;
  workspace_schema_content?: string | null;
  index_segments?: Array<{ path_prefix: string; patterns?: string[]; embedding_model?: string | null; similarity_threshold?: number; top_k?: number }>;
  index_segment_defaults?: {
    embedding_model: string;
    patterns: string[];
    similarity_threshold: number;
    top_k: number;
  } | null;
  // Carapace overrides
  carapaces_extra?: string[] | null;
  carapaces_disabled?: string[] | null;
  workspace_id?: string | null;
  resolved_workspace_id?: string | null;
  category?: string | null;
  tags?: string[];
  /** Pipeline-mode override on this channel. "auto" (default) shows the
   *  pipeline launchpad when subscriptions exist; "on" forces it visible;
   *  "off" hides it even with subscriptions. Stored in `channel.config`. */
  pipeline_mode?: "auto" | "on" | "off";
}

export interface EffectiveTools {
  local_tools: string[];
  mcp_servers: string[];
  client_tools: string[];
  pinned_tools: string[];
  skills: { id: string; mode: string; name?: string }[];
  mode: Record<string, "inherit" | "disabled">;
  disabled: Record<string, string[]>;
  carapaces: string[];
  carapace_sources: Record<string, string>;
}

// Model types
export interface LlmModel {
  id: string;
  display: string;
  max_tokens?: number;
  download_status?: "cached" | "not_downloaded" | "downloading";
  size_mb?: number;
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
  description?: string;
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

/** OpenAI function-call format as stored in DB */
export interface ToolCall {
  id: string;
  type?: string;
  function?: { name: string; arguments: string };
  // Flattened form (for convenience)
  name?: string;
  arguments?: string;
}

/** Extract name and arguments from a ToolCall regardless of format */
export function normalizeToolCall(tc: ToolCall): { name: string; arguments: string } {
  if (tc.function) {
    return { name: tc.function.name, arguments: tc.function.arguments };
  }
  return { name: tc.name ?? "unknown", arguments: tc.arguments ?? "{}" };
}

/**
 * Rendered tool result envelope — mirrors `ToolResultEnvelope.compact_dict()`
 * from `app/agent/tool_dispatch.py`. Carries the user-visible body for the
 * web UI's mimetype-keyed renderer (markdown / json-tree / sandboxed-html /
 * unified-diff / file-listing). The full untruncated body lives on the
 * persisted `tool_calls` row when `truncated=true`; the UI lazy-fetches it
 * via `GET /api/v1/sessions/{sid}/tool-calls/{record_id}/result`.
 */
export interface ToolResultEnvelope {
  content_type: string;
  body: string | null;
  plain_body: string;
  display: "badge" | "inline" | "panel";
  truncated: boolean;
  record_id: string | null;
  byte_size: number;
  widget_type?: string;
  /** Resolved display label from widget template (e.g., entity name) */
  display_label?: string | null;
  /** When true, this widget supports state refresh on load via state_poll */
  refreshable?: boolean;
  /** If set, pinned widgets should auto-refresh on this interval (seconds) */
  refresh_interval_seconds?: number | null;
  /** For file-backed widgets (emit_html_widget path-mode): workspace-relative path
   *  the renderer fetches content from. Paired with `source_channel_id`. */
  source_path?: string | null;
  /** Channel id scoping `source_path` to its channel workspace. */
  source_channel_id?: string | null;
  /** Bot that emitted the envelope. Drives the widget-auth mint so
   *  interactive HTML widgets authenticate as this bot, not as the
   *  viewing user. */
  source_bot_id?: string | null;
}

/** Action definition for interactive widget components (toggle, button, select, etc.) */
export interface WidgetAction {
  /** "tool" dispatches through tool_dispatch, "api" calls a REST endpoint directly,
   *  "widget_config" patches the pinned widget's config and returns a refreshed envelope. */
  dispatch: "tool" | "api" | "widget_config";
  /** For dispatch:"tool" — the tool name to call */
  tool?: string;
  /** For dispatch:"api" — the endpoint path (allowlisted internal paths only) */
  endpoint?: string;
  method?: "POST" | "PUT" | "PATCH" | "DELETE";
  /** Static args merged with the dynamic value from the interactive element */
  args?: Record<string, unknown>;
  /** For dispatch:"widget_config" — the config patch to shallow-merge into the pin. */
  config?: Record<string, unknown>;
  /** Key name for the dynamic value (e.g., toggle sends {[value_key]: true/false}) */
  value_key?: string;
  /** Flip the value client-side before server confirms */
  optimistic?: boolean;
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
  model_provider_id_override?: string | null;
  attachments?: ChatAttachment[];
  file_metadata?: ChatFileMetadata[];
  audio_data?: string;
  audio_format?: string;
  audio_native?: boolean;
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
  | "tool_start"
  | "tool_request"
  | "tool_result"
  | "assistant_text"
  | "text_delta"
  | "thinking"
  | "thinking_content"
  | "transcript"
  | "response"
  | "compaction_start"
  | "compaction_done"
  | "warning"
  | "error"
  | "queued"
  | "cancelled"
  | "passive_stored"
  | "secret_warning"
  | "approval_request"
  | "approval_resolved"
  | "delegation_post"
  | "pending_tasks"
  | "stream_meta"
  | "pending_member_stream"
  | "context_budget"
  | "skill_auto_inject"
  | "llm_status";

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
  write_access?: string[];
  user_id?: string | null;
}

export interface SharedWorkspace {
  id: string;
  name: string;
  description?: string | null;
  env: Record<string, string>;
  workspace_base_prompt_enabled: boolean;
  indexing_config?: Record<string, any> | null;
  write_protected_paths?: string[];
  status: string;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
  bots: WorkspaceBot[];
}

export interface WorkspaceCreate {
  name: string;
  description?: string;
  env?: Record<string, string>;
  workspace_base_prompt_enabled?: boolean;
  write_protected_paths?: string[];
  created_by_user_id?: string;
}

export interface WorkspaceUpdate {
  name?: string;
  description?: string;
  env?: Record<string, string>;
  workspace_base_prompt_enabled?: boolean;
  write_protected_paths?: string[];
  indexing_config?: Record<string, any>;
}

export interface WorkspaceFileEntry {
  name: string;
  is_dir: boolean;
  size?: number | null;
  path: string;
  modified_at?: number | null; // unix timestamp (seconds)
  display_name?: string | null; // from .channel_info for channel UUID dirs
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

export interface CompressionState {
  enabled: boolean;
  model: string | null;
  threshold: number;
  keep_turns: number;
  conversation_chars: number;
  would_compress: boolean;
}

export interface ContextBreakdown {
  channel_id: string;
  session_id: string | null;
  bot_id: string;
  categories: ContextCategory[];
  total_chars: number;
  total_tokens_approx: number;
  compaction: CompactionState;
  compression?: CompressionState | null;
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
  group?: string | null;
  recommended_heartbeat?: {
    prompt: string;
    interval: string;
    quiet_start?: string | null;
    quiet_end?: string | null;
  } | null;
  workspace_id?: string | null;
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

// Cron job types
export interface CronEntry {
  expression: string;
  command: string;
  source_type: "container" | "host";
  source_name: string;
  workspace_id?: string | null;
  workspace_name?: string | null;
  user: string;
}

// Heartbeat types
export interface HeartbeatHistoryRun {
  id: string;
  status: string;
  run_at: string;
  completed_at?: string | null;
  result?: string | null;
  error?: string | null;
  correlation_id?: string | null;
  repetition_detected?: boolean | null;
  tool_calls: { tool_name: string; tool_type: string; iteration?: number | null; duration_ms?: number | null; error?: string | null }[];
  total_tokens: number;
  iterations: number;
  duration_ms?: number | null;
}

// Spike alert types
export interface SpikeConfig {
  id: string;
  enabled: boolean;
  window_minutes: number;
  baseline_hours: number;
  relative_threshold: number;
  absolute_threshold_usd: number;
  cooldown_minutes: number;
  targets: SpikeTarget[];
  last_alert_at: string | null;
  last_check_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SpikeTarget {
  type: "channel" | "integration";
  channel_id?: string;
  integration_type?: string;
  client_id?: string;
  label?: string;
}

export interface SpikeStatus {
  enabled: boolean;
  spiking: boolean;
  window_rate: number;
  baseline_rate: number;
  spike_ratio: number | null;
  cooldown_active: boolean;
  cooldown_remaining_seconds: number;
}

export interface SpikeAlert {
  id: string;
  window_rate_usd_per_hour: number;
  baseline_rate_usd_per_hour: number;
  spike_ratio: number | null;
  trigger_reason: string;
  top_models: { model: string; cost: number; calls: number }[];
  top_bots: { bot_id: string; cost: number }[];
  recent_traces: { correlation_id: string; model: string; bot_id: string; cost: number }[];
  targets_attempted: number;
  targets_succeeded: number;
  delivery_details: { target: SpikeTarget; success: boolean; error?: string }[];
  created_at: string | null;
}

export interface SpikeAlertList {
  total: number;
  page: number;
  page_size: number;
  alerts: SpikeAlert[];
}

export interface TargetOption {
  type: "channel" | "integration";
  channel_id?: string;
  integration_type?: string;
  client_id?: string;
  label: string;
}

export interface AvailableIntegration {
  integration_type: string;
  client_id_prefix: string;
}

export interface AvailableTargetsResponse {
  options: TargetOption[];
  integrations: AvailableIntegration[];
}

// Storage / data retention types
export interface TableStats {
  table: string;
  row_count: number;
  size_bytes: number | null;
  size_display: string | null;
  oldest_row: string | null;
  purgeable: number;
}

export interface StorageBreakdown {
  tables: TableStats[];
  retention_days: number | null;
  sweep_interval_s: number;
}

export interface PurgeResult {
  deleted: Record<string, number>;
  total: number;
}

// Docker Stacks
export interface DockerStack {
  id: string;
  name: string;
  description?: string | null;
  created_by_bot: string;
  channel_id?: string | null;
  compose_definition: string;
  project_name: string;
  status: string;
  error_message?: string | null;
  network_name?: string | null;
  container_ids: Record<string, string>;
  exposed_ports: Record<string, Array<{ host_port: number; container_port: number; protocol?: string }>>;
  source: string;
  integration_id?: string | null;
  connect_networks: string[];
  last_started_at?: string | null;
  last_stopped_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DockerStackServiceStatus {
  name: string;
  state: string;
  health?: string | null;
  ports: Array<{ host_port: number; container_port: number; protocol?: string }>;
}

// Admin types
export interface AdminStats {
  sessions: number;
  tools: number;
  sandboxes: number;
}
