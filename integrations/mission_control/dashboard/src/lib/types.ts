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
// API data
// ---------------------------------------------------------------------------

export interface ChannelSummary {
  id: string;
  name: string | null;
  bot_id: string | null;
  workspace_enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface BotSummary {
  id: string;
  name: string;
  model: string | null;
}

export interface OverviewData {
  channels: ChannelSummary[];
  bots: BotSummary[];
  task_counts: Record<string, number>;
  session_count: number;
  channel_count: number;
  bot_count: number;
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
  workspace_type: string;
}
