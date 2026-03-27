/**
 * Simple SVG chart components for the Usage page.
 * Uses inline SVG (web) — no external charting library needed.
 */

interface BarChartItem {
  label: string;
  value: number;
  color?: string;
}

interface BarChartProps {
  items: BarChartItem[];
  formatValue?: (v: number) => string;
  barColor?: string;
  maxBars?: number;
}

export function BarChart({
  items,
  formatValue = (v) => v.toFixed(2),
  barColor = "#3b82f6",
  maxBars = 10,
}: BarChartProps) {
  const displayed = items.slice(0, maxBars);
  if (displayed.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: "center", color: "#666", fontSize: 13 }}>
        No data
      </div>
    );
  }

  const maxVal = Math.max(...displayed.map((d) => d.value), 0.001);
  const barHeight = 28;
  const gap = 6;
  const labelWidth = 160;
  const valueWidth = 80;
  const chartHeight = displayed.length * (barHeight + gap) - gap;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: gap }}>
      {displayed.map((item, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: labelWidth,
              fontSize: 12,
              color: "#999",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              textAlign: "right",
              flexShrink: 0,
            }}
            title={item.label}
          >
            {item.label}
          </span>
          <div style={{ flex: 1, height: barHeight, position: "relative" }}>
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: `${Math.max((item.value / maxVal) * 100, 1)}%`,
                backgroundColor: item.color || barColor,
                borderRadius: 4,
                opacity: 0.8,
              }}
            />
          </div>
          <span
            style={{
              width: valueWidth,
              fontSize: 12,
              color: "#ccc",
              textAlign: "right",
              fontFamily: "monospace",
              flexShrink: 0,
            }}
          >
            {formatValue(item.value)}
          </span>
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
  lineColor?: string;
  fillColor?: string;
  height?: number;
}

export function LineChart({
  points,
  formatValue = (v) => v.toFixed(2),
  lineColor = "#3b82f6",
  fillColor = "rgba(59,130,246,0.15)",
  height = 200,
}: LineChartProps) {
  if (points.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: "center", color: "#666", fontSize: 13 }}>
        No data
      </div>
    );
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
    linePath +
    ` L ${coords[coords.length - 1].x} ${paddingTop + innerH}` +
    ` L ${coords[0].x} ${paddingTop + innerH} Z`;

  // Y-axis grid lines (4 lines)
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((frac) => ({
    y: paddingTop + innerH - frac * innerH,
    label: formatValue(frac * maxVal),
  }));

  // X-axis labels (show ~6 labels max)
  const labelStep = Math.max(1, Math.floor(points.length / 6));
  const xLabels = points
    .map((p, i) => ({ ...p, i }))
    .filter((_, i) => i % labelStep === 0 || i === points.length - 1);

  return (
    <div style={{ overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${chartWidth} ${height}`}
        width="100%"
        height={height}
        style={{ maxWidth: chartWidth }}
      >
        {/* Grid lines */}
        {gridLines.map((g, i) => (
          <g key={i}>
            <line
              x1={paddingLeft}
              y1={g.y}
              x2={chartWidth - paddingRight}
              y2={g.y}
              stroke="#333"
              strokeWidth={1}
            />
            <text
              x={paddingLeft - 8}
              y={g.y + 4}
              textAnchor="end"
              fill="#666"
              fontSize={10}
            >
              {g.label}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill={fillColor} />

        {/* Line */}
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth={2} />

        {/* Data points */}
        {coords.map((c, i) => (
          <circle
            key={i}
            cx={c.x}
            cy={c.y}
            r={3}
            fill={lineColor}
            stroke="#111"
            strokeWidth={1}
          />
        ))}

        {/* X-axis labels */}
        {xLabels.map((p) => (
          <text
            key={p.i}
            x={paddingLeft + p.i * xStep}
            y={height - 8}
            textAnchor="middle"
            fill="#666"
            fontSize={10}
          >
            {p.label}
          </text>
        ))}
      </svg>
    </div>
  );
}
