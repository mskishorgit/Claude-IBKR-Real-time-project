interface Props {
  values: number[];
  width?: number;
  height?: number;
  positive: boolean;
}

const POSITIVE_COLOR = "#34d399"; // emerald-400, matches P/L green used elsewhere in the app
const NEGATIVE_COLOR = "#f87171"; // red-400, matches P/L red used elsewhere in the app

/** Minimal, dependency-free inline-SVG line — for a grid of many small
 * tiles, one lightweight-charts instance per tile would be excessive.
 * Single series, no axes/legend (a sparkline's whole point is "just the
 * shape"), colored by the tile's own up/down status rather than a
 * generic categorical hue. */
export function Sparkline({ values, width = 96, height = 28, positive }: Props) {
  const color = positive ? POSITIVE_COLOR : NEGATIVE_COLOR;

  if (values.length < 2) {
    return (
      <svg width={width} height={height} className="overflow-visible">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="#334155" strokeWidth={1} />
      </svg>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const padding = 3;

  const points = values.map((value, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - padding - ((value - min) / range) * (height - padding * 2);
    return [x, y] as const;
  });

  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lastX, lastY] = points[points.length - 1];

  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
    </svg>
  );
}
