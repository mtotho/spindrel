/** Core domain types for Mission Control. */

// ---------------------------------------------------------------------------
// Kanban / Tasks
// ---------------------------------------------------------------------------

export interface TaskCard {
  title: string;
  meta: Record<string, string>;
  description: string;
}

export interface KanbanColumn {
  name: string;
  cards: TaskCard[];
}

// ---------------------------------------------------------------------------
// API data (matches /integrations/mission_control/overview response)
// ---------------------------------------------------------------------------

export interface ChannelSummary {
  id: string;
  name: string | null;
  bot_id: string | null;
  bot_name: string | null;
  model: string | null;
  workspace_enabled: boolean;
  task_count: number;
  template_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  is_member: boolean;
}

export interface BotSummary {
  id: string;
  name: string;
  model: string | null;
  channel_count: number;
  memory_scheme: string | null;
}

export interface OverviewData {
  channels: ChannelSummary[];
  bots: BotSummary[];
  total_channels: number;
  total_channels_all: number;
  total_bots: number;
  total_tasks: number;
  is_admin: boolean;
}

// ---------------------------------------------------------------------------
// File system
// ---------------------------------------------------------------------------

export interface WorkspaceFile {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: "active" | "archive" | "data";
}

export interface DailyLog {
  date: string;
  content: string;
}

export interface FileChannel {
  id: string;
  display_name?: string;
  name?: string | null;
  bot_id?: string | null;
  workspace_enabled?: boolean;
}
