/**
 * Shared low-chrome SVG charts.
 *
 * These intentionally use CSS variable colors through Tailwind-compatible
 * custom properties so dark/light mode flips without component-level theme
 * branching.
 */

interface BarChartItem {
  label: string;
  value: number;
  colorClass?: string;
}

interface BarChartProps {
  items: BarChartItem[];
  formatValue?: (v: number) => string;
  maxBars?: number;
}

export function BarChart({
  items,
  formatValue = (v) => v.toFixed(2),
  maxBars = 10,
}: BarChartProps) {
  const displayed = items.slice(0, maxBars);
  if (displayed.length === 0) {
    return <div className="px-4 py-6 text-center text-[13px] text-text-dim">No data</div>;
  }

  const maxVal = Math.max(...displayed.map((d) => d.value), 0.001);

  return (
    <div className="flex flex-col gap-1.5">
      {displayed.map((item) => (
        <div key={item.label} className="grid grid-cols-[minmax(96px,180px)_1fr_80px] items-center gap-2 text-[12px]">
          <span className="truncate text-right text-text-muted" title={item.label}>{item.label}</span>
          <div className="relative h-6 overflow-hidden rounded-md bg-surface-overlay/30">
            <div
              className={`absolute inset-y-0 left-0 rounded-md ${item.colorClass ?? "bg-accent/70"}`}
              style={{ width: `${Math.max((item.value / maxVal) * 100, 1)}%` }}
            />
          </div>
          <span className="text-right font-mono text-[12px] text-text">{formatValue(item.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface LineChartPoint {
  label: string;
  value: number;
}

interface LineChartProps {
  points: LineChartPoint[];
  formatValue?: (v: number) => string;
  height?: number;
  tone?: "accent" | "success" | "warning";
}

const TONE_STROKE = {
  accent: "stroke-accent",
  success: "stroke-success",
  warning: "stroke-warning",
} as const;

const TONE_FILL = {
  accent: "fill-accent/10",
  success: "fill-success/10",
  warning: "fill-warning/10",
} as const;

export function LineChart({
  points,
  formatValue = (v) => v.toFixed(2),
  height = 200,
  tone = "accent",
}: LineChartProps) {
  if (points.length === 0) {
    return <div className="px-4 py-6 text-center text-[13px] text-text-dim">No data</div>;
  }

  const paddingLeft = 60;
  const paddingRight = 20;
  const paddingTop = 10;
  const paddingBottom = 40;
  const chartWidth = 800;
  const maxVal = Math.max(...points.map((p) => p.value), 0.001);
  const innerW = chartWidth - paddingLeft - paddingRight;
  const innerH = height - paddingTop - paddingBottom;
  const xStep = points.length > 1 ? innerW / (points.length - 1) : 0;
  const coords = points.map((p, i) => ({
    x: paddingLeft + i * xStep,
    y: paddingTop + innerH - (p.value / maxVal) * innerH,
  }));
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
  const areaPath =
    `${linePath} L ${coords[coords.length - 1].x} ${paddingTop + innerH} L ${coords[0].x} ${paddingTop + innerH} Z`;
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((frac) => ({
    y: paddingTop + innerH - frac * innerH,
    label: formatValue(frac * maxVal),
  }));
  const labelStep = Math.max(1, Math.floor(points.length / 6));
  const xLabels = points.map((p, i) => ({ ...p, i })).filter((_, i) => i % labelStep === 0 || i === points.length - 1);

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${chartWidth} ${height}`} width="100%" height={height} className="max-w-[800px]">
        {gridLines.map((g) => (
          <g key={g.y}>
            <line x1={paddingLeft} y1={g.y} x2={chartWidth - paddingRight} y2={g.y} className="stroke-surface-border" strokeWidth={1} />
            <text x={paddingLeft - 8} y={g.y + 4} textAnchor="end" className="fill-text-dim text-[10px]">{g.label}</text>
          </g>
        ))}
        <path d={areaPath} className={TONE_FILL[tone]} />
        <path d={linePath} fill="none" className={TONE_STROKE[tone]} strokeWidth={2} />
        {coords.map((c, i) => <circle key={i} cx={c.x} cy={c.y} r={3} className={`fill-surface ${TONE_STROKE[tone]}`} strokeWidth={2} />)}
        {xLabels.map((p) => (
          <text key={p.i} x={paddingLeft + p.i * xStep} y={height - 8} textAnchor="middle" className="fill-text-dim text-[10px]">
            {p.label}
          </text>
        ))}
      </svg>
    </div>
  );
}

export interface TimelineChartPoint {
  bucket: string;
  label: string;
  value: number;
  secondaryValue?: number | null;
  calls?: number;
  marker?: "info" | "warning" | "danger";
  selectable?: boolean;
}

interface TimelineChartProps {
  points: TimelineChartPoint[];
  formatValue?: (v: number) => string;
  onSelect?: (point: TimelineChartPoint) => void;
  height?: number;
}

const MARKER_FILL = {
  info: "fill-accent",
  warning: "fill-warning",
  danger: "fill-danger",
} as const;

export function TimelineChart({
  points,
  formatValue = (v) => String(Math.round(v)),
  onSelect,
  height = 220,
}: TimelineChartProps) {
  if (points.length === 0) {
    return <div className="px-4 py-8 text-center text-[13px] text-text-dim">No timeline data</div>;
  }
  const width = 900;
  const paddingLeft = 62;
  const paddingRight = 24;
  const paddingTop = 18;
  const paddingBottom = 42;
  const innerW = width - paddingLeft - paddingRight;
  const innerH = height - paddingTop - paddingBottom;
  const maxVal = Math.max(...points.map((point) => point.value), 0.001);
  const xStep = points.length > 1 ? innerW / (points.length - 1) : 0;
  const coords = points.map((point, index) => ({
    point,
    x: paddingLeft + index * xStep,
    y: paddingTop + innerH - (point.value / maxVal) * innerH,
  }));
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
  const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${paddingTop + innerH} L ${coords[0].x} ${paddingTop + innerH} Z`;
  const gridLines = [0, 0.5, 1].map((frac) => ({
    y: paddingTop + innerH - frac * innerH,
    label: formatValue(frac * maxVal),
  }));
  const labelStep = Math.max(1, Math.floor(points.length / 6));

  return (
    <div className="overflow-x-auto rounded-md bg-surface-raised/35 px-2 py-3">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} className="min-w-[680px]">
        {gridLines.map((line) => (
          <g key={line.y}>
            <line x1={paddingLeft} y1={line.y} x2={width - paddingRight} y2={line.y} className="stroke-surface-border/70" strokeWidth={1} />
            <text x={paddingLeft - 8} y={line.y + 4} textAnchor="end" className="fill-text-dim text-[10px]">{line.label}</text>
          </g>
        ))}
        <path d={areaPath} className="fill-accent/10" />
        <path d={linePath} fill="none" className="stroke-accent" strokeWidth={2} />
        {coords.map(({ point, x, y }, index) => {
          const selectable = Boolean(onSelect && point.selectable);
          return (
          <g
            key={point.bucket}
            onClick={selectable ? () => onSelect?.(point) : undefined}
            className={selectable ? "cursor-pointer" : undefined}
          >
            <circle
              cx={x}
              cy={y}
              r={point.marker ? 5 : 3}
              className={point.marker ? MARKER_FILL[point.marker] : "fill-surface stroke-accent"}
              strokeWidth={point.marker ? 0 : 2}
            />
            {(index % labelStep === 0 || index === points.length - 1) && (
              <text x={x} y={height - 10} textAnchor="middle" className="fill-text-dim text-[10px]">{point.label}</text>
            )}
          </g>
        );})}
      </svg>
    </div>
  );
}
