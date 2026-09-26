import React, { useMemo, useState } from 'react';
import { ScatterPoint, RelationshipCurve } from '../../types/layerLab';
import { Axes, ChartTooltip, Tip, extent, fmt, hhmm, linear, niceTicks, useWidth } from './chartKit';

interface Props {
  scatter: ScatterPoint[];
  curve?: RelationshipCurve;
  solarHour: number;
  reading: { t: number; rh: number };
  site: string;
}

const H = 300;
const M = { l: 48, r: 14, t: 12, b: 40 };

/**
 * Joint T–RH state for this station's season: every hourly observation in the
 * reference window (blue), those at the same time of day emphasised, the
 * relationship Layer 3 learned at this hour (expected RH ±2σ), and the reading.
 */
export const JointStateChart: React.FC<Props> = ({ scatter, curve, solarHour, reading, site }) => {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);

  const near = (h: number) => Math.abs(((h - solarHour) + 12 + 24) % 24 - 12) <= 1;
  const { x, y, xTicks, yTicks } = useMemo(() => {
    const [t0, t1] = extent([...scatter.map((p) => p.t), reading.t], 0.05);
    const x = linear(t0, t1, M.l, width - M.r);
    const y = linear(0, 100, H - M.b, M.t);
    return { x, y, xTicks: niceTicks(t0, t1, 6), yTicks: [0, 20, 40, 60, 80, 100] };
  }, [scatter, reading.t, width]);

  const band = curve ? (() => {
    const upper = curve.t.map((t, i) => `${x(t)},${y(Math.min(100, curve.expected[i] + 2 * curve.sd))}`);
    const lower = curve.t.map((t, i) => `${x(t)},${y(Math.max(0, curve.expected[i] - 2 * curve.sd))}`).reverse();
    return `M${upper.join('L')}L${lower.join('L')}Z`;
  })() : null;
  const line = curve ? `M${curve.t.map((t, i) => `${x(t)},${y(Math.min(100, Math.max(0, curve.expected[i])))}`).join('L')}` : null;

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    let best: ScatterPoint | null = null, bd = 14 * 14;
    for (const p of scatter) {
      const d = (x(p.t) - px) ** 2 + (y(p.rh) - py) ** 2;
      if (d < bd) { bd = d; best = p; }
    }
    const dr = (x(reading.t) - px) ** 2 + (y(reading.rh) - py) ** 2;
    if (dr < 16 * 16) {
      setTip({ x: x(reading.t), y: y(reading.rh), lines: [<b key="b">This reading</b>, `${fmt(reading.t)} °C · ${fmt(reading.rh, 0)} % RH`] });
    } else if (best) {
      setTip({ x: x(best.t), y: y(best.rh), lines: [
        <b key="b">{site} · solar {hhmm(best.h)}</b>, `${fmt(best.t)} °C · ${fmt(best.rh, 0)} % RH · ${fmt(best.p)} hPa`] });
    } else setTip(null);
  };

  return (
    <div className="ll-chart" ref={wrapRef}>
      <svg width={width} height={H} role="img"
           aria-label={`Temperature versus relative humidity at ${site} for this season, with the current reading marked`}>
        <Axes x={x} y={y} xTicks={xTicks} yTicks={yTicks} left={M.l} right={width - M.r} top={M.t} bottom={H - M.b}
              xLabel="Air temperature (°C)" yLabel="Relative humidity (%)" />
        {scatter.map((p, i) => !near(p.h) && (
          <circle key={i} cx={x(p.t)} cy={y(p.rh)} r={2} className="ll-dot-reference" />
        ))}
        {scatter.map((p, i) => near(p.h) && (
          <circle key={`n${i}`} cx={x(p.t)} cy={y(p.rh)} r={3} className="ll-dot-samehour" />
        ))}
        {band && <path d={band} className="ll-expect-band" />}
        {line && <path d={line} className="ll-expect-line" />}
        <circle cx={x(reading.t)} cy={y(reading.rh)} r={7} className="ll-reading-marker" />
        <rect x={M.l} y={M.t} width={width - M.l - M.r} height={H - M.t - M.b} fill="transparent"
              onMouseMove={onMove} onMouseLeave={() => setTip(null)} />
      </svg>
      <ChartTooltip tip={tip} width={width} />
      <div className="ll-legend">
        <span><i className="ll-key ll-key-reference" />All hours in season window</span>
        <span><i className="ll-key ll-key-samehour" />Same time of day (±1 h)</span>
        <span><i className="ll-key ll-key-expect" />Expected RH at this hour ±2σ (learned)</span>
        <span><i className="ll-key ll-key-reading" />This reading</span>
      </div>
    </div>
  );
};
