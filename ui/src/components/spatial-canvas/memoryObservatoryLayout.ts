import type {
  MemoryFileActivity,
  MemoryObservatoryBot,
  MemoryObservatoryFile,
} from "../../api/hooks/useLearningOverview";

export interface ObservatoryFileMark {
  file: MemoryObservatoryFile;
  x: number;
  y: number;
  r: number;
  laneIndex: number;
  color: string;
}

export interface ObservatoryEventMark {
  event: MemoryFileActivity;
  x: number;
  y: number;
  r: number;
  color: string;
  matchKey: string;
}

export interface ObservatoryLane {
  bot: MemoryObservatoryBot;
  index: number;
  angle: number;
  rx: number;
  ry: number;
  color: string;
  files: ObservatoryFileMark[];
}

export function memoryFileKey(botId: string | null | undefined, filePath: string | null | undefined): string {
  return `${botId ?? ""}:${filePath ?? ""}`;
}

export function stableObservatoryHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}

export function buildObservatoryLanes(
  bots: MemoryObservatoryBot[],
  maxWriteCount: number,
): ObservatoryLane[] {
  const laneCount = Math.max(1, bots.length);
  return bots.map((bot, index) => {
    const angle = -Math.PI * 0.78 + (Math.PI * 1.56 * (index + 0.5)) / laneCount;
    const rx = 190 + index * 24;
    const ry = 96 + index * 11;
    const color = `hsl(${stableObservatoryHue(bot.bot_id)}, 58%, 60%)`;
    const files = bot.hot_files.map((file, fileIndex) => {
      const spread = bot.hot_files.length <= 1
        ? 0
        : (fileIndex - (bot.hot_files.length - 1) / 2) * 0.18;
      const t = angle + spread;
      const weight = maxWriteCount > 0 ? file.write_count / maxWriteCount : 0;
      return {
        file,
        laneIndex: index,
        color,
        x: Math.cos(t) * rx,
        y: Math.sin(t) * ry,
        r: 8 + Math.sqrt(Math.max(1, file.write_count)) * 4 + weight * 12,
      };
    });
    return { bot, index, angle, rx, ry, color, files };
  });
}

export function buildObservatoryEventMarks(
  events: MemoryFileActivity[],
  lanes: ObservatoryLane[],
): ObservatoryEventMark[] {
  const laneByBot = new Map(lanes.map((lane) => [lane.bot.bot_id, lane]));
  const now = Date.now();
  return events.slice(0, 36).map((event, index) => {
    const lane = laneByBot.get(event.bot_id);
    const color = lane?.color ?? `hsl(${stableObservatoryHue(event.bot_id)}, 44%, 58%)`;
    const ageMs = Math.max(0, now - Date.parse(event.created_at));
    const ageFactor = Math.min(1, ageMs / (1000 * 60 * 60 * 24 * 30));
    const theta = (lane?.angle ?? 0) + (index % 7 - 3) * 0.05;
    const rx = (lane?.rx ?? 210) * (0.72 + ageFactor * 0.24);
    const ry = (lane?.ry ?? 105) * (0.72 + ageFactor * 0.24);
    return {
      event,
      color,
      matchKey: memoryFileKey(event.bot_id, event.file_path),
      x: Math.cos(theta) * rx + ((index % 3) - 1) * 8,
      y: Math.sin(theta) * ry + ((index % 5) - 2) * 4,
      r: event.is_hygiene ? 5.5 : 4,
    };
  });
}
