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
  ageFactor: number;
  rank: number;
  laneIndex: number;
  color: string;
}

export interface ObservatoryEventMark {
  event: MemoryFileActivity;
  x: number;
  y: number;
  r: number;
  ageFactor: number;
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

const DAY_MS = 1000 * 60 * 60 * 24;

export function observatoryHorizonDays(days: number): number {
  return days > 0 ? days : 90;
}

export function temporalAgeFactor(value: string | null | undefined, horizonDays: number, now = Date.now()): number {
  if (!value) return 1;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return 1;
  const horizonMs = Math.max(1, horizonDays) * DAY_MS;
  return Math.max(0, Math.min(1, (now - parsed) / horizonMs));
}

export function temporalLaneScale(ageFactor: number): number {
  return 0.52 + Math.max(0, Math.min(1, ageFactor)) * 0.42;
}

export function buildObservatoryLanes(
  bots: MemoryObservatoryBot[],
  maxWriteCount: number,
  horizonDays = 30,
  now = Date.now(),
): ObservatoryLane[] {
  const laneCount = Math.max(1, bots.length);
  return bots.map((bot, index) => {
    const angle = -Math.PI * 0.78 + (Math.PI * 1.56 * (index + 0.5)) / laneCount;
    const rx = 250 + index * 32;
    const ry = 122 + index * 14;
    const color = `hsl(${stableObservatoryHue(bot.bot_id)}, 58%, 60%)`;
    const files = bot.hot_files.map((file, fileIndex) => {
      const spread = bot.hot_files.length <= 1
        ? 0
        : (fileIndex - (bot.hot_files.length - 1) / 2) * 0.15;
      const t = angle + spread;
      const weight = maxWriteCount > 0 ? file.write_count / maxWriteCount : 0;
      const ageFactor = temporalAgeFactor(file.last_updated_at, horizonDays, now);
      const temporalScale = temporalLaneScale(ageFactor);
      return {
        file,
        laneIndex: index,
        rank: fileIndex,
        color,
        ageFactor,
        x: Math.cos(t) * rx * temporalScale,
        y: Math.sin(t) * ry * temporalScale,
        r: 8 + Math.sqrt(Math.max(1, file.write_count)) * 4 + weight * 12,
      };
    });
    return { bot, index, angle, rx, ry, color, files };
  });
}

export function buildObservatoryEventMarks(
  events: MemoryFileActivity[],
  lanes: ObservatoryLane[],
  horizonDays = 30,
  now = Date.now(),
): ObservatoryEventMark[] {
  const laneByBot = new Map(lanes.map((lane) => [lane.bot.bot_id, lane]));
  return events.slice(0, 36).map((event, index) => {
    const lane = laneByBot.get(event.bot_id);
    const color = lane?.color ?? `hsl(${stableObservatoryHue(event.bot_id)}, 44%, 58%)`;
    const ageFactor = temporalAgeFactor(event.created_at, horizonDays, now);
    const temporalScale = temporalLaneScale(ageFactor);
    const theta = (lane?.angle ?? 0) + (index % 7 - 3) * 0.05;
    const rx = (lane?.rx ?? 210) * temporalScale;
    const ry = (lane?.ry ?? 105) * temporalScale;
    return {
      event,
      color,
      ageFactor,
      matchKey: memoryFileKey(event.bot_id, event.file_path),
      x: Math.cos(theta) * rx + ((index % 3) - 1) * 8,
      y: Math.sin(theta) * ry + ((index % 5) - 2) * 4,
      r: event.is_hygiene ? 5.5 : 4,
    };
  });
}
