import React from 'react';

/** Linear scale domain -> range. */
export function linear(d0: number, d1: number, r0: number, r1: number) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = (v: number) => r0 + (v - d0) * k;
  f.invert = (px: number) => d0 + (px - r0) / (k || 1);
  return f as ((v: number) => number) & { invert: (px: number) => number };
}

/** ~n "nice" ticks covering [lo, hi]. */
export function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [lo];
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

export function extent(values: number[], pad = 0): [number, number] {
  const v = values.filter((x) => Number.isFinite(x));
  if (!v.length) return [0, 1];
  const lo = Math.min(...v), hi = Math.max(...v);
  const p = (hi - lo || 1) * pad;
  return [lo - p, hi + p];
}

export const fmt = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(d);

/** Solar hour -> "14:39" */
export const hhmm = (h: number) => {
  const hh = Math.floor(((h % 24) + 24) % 24);
  const mm = Math.round((h - Math.floor(h)) * 60) % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
};

export interface Tip { x: number; y: number; lines: React.ReactNode[] }

/** Positioned tooltip inside a relatively-positioned chart wrapper. */
export const ChartTooltip: React.FC<{ tip: Tip | null; width: number }> = ({ tip, width }) => {
  if (!tip) return null;
  const left = tip.x > width * 0.6 ? tip.x - 12 : tip.x + 12;
  return (
    <div className="ll-tooltip" style={{ left, top: tip.y, transform: tip.x > width * 0.6 ? 'translate(-100%, -50%)' : 'translate(0, -50%)' }}>
      {tip.lines.map((l, i) => <div key={i}>{l}</div>)}
    </div>
  );
};

/** Recessive axes + grid for a plot area. */
export const Axes: React.FC<{
  x: (v: number) => number; y: (v: number) => number;
  xTicks: number[]; yTicks: number[];
  left: number; right: number; top: number; bottom: number;
  xLabel?: string; yLabel?: string; xFormat?: (v: number) => string; yFormat?: (v: number) => string;
}> = ({ x, y, xTicks, yTicks, left, right, top, bottom, xLabel, yLabel, xFormat = String, yFormat = String }) => (
  <g className="ll-axes">
    {yTicks.map((t) => (
      <g key={`y${t}`}>
        <line x1={left} x2={right} y1={y(t)} y2={y(t)} className="ll-grid" />
        <text x={left - 6} y={y(t)} className="ll-tick" textAnchor="end" dominantBaseline="middle">{yFormat(t)}</text>
      </g>
    ))}
    {xTicks.map((t) => (
      <text key={`x${t}`} x={x(t)} y={bottom + 14} className="ll-tick" textAnchor="middle">{xFormat(t)}</text>
    ))}
    <line x1={left} x2={right} y1={bottom} y2={bottom} className="ll-baseline" />
    {xLabel && <text x={(left + right) / 2} y={bottom + 30} className="ll-axis-label" textAnchor="middle">{xLabel}</text>}
    {yLabel && (
      <text transform={`translate(${left - 34}, ${(top + bottom) / 2}) rotate(-90)`} className="ll-axis-label" textAnchor="middle">{yLabel}</text>
    )}
  </g>
);

/** Measures the wrapper width so SVG charts stay responsive. */
export function useWidth<T extends HTMLElement>(fallback = 480): [React.RefObject<T>, number] {
  const ref = React.useRef<T>(null);
  const [w, setW] = React.useState(fallback);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => setW(Math.max(260, Math.floor(entries[0].contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
