import React, { useMemo, useState } from 'react';
import { ProfileRow } from '../../types/layerLab';
import { Axes, ChartTooltip, Tip, extent, fmt, hhmm, linear, niceTicks, useWidth } from './chartKit';

type Key = 't' | 'rh' | 'p' | 'td';
interface Props { profile: ProfileRow[]; variable: Key; title: string; unit: string; solarHour: number; value: number | null; decimals?: number }

const H = 150;
const M = { l: 42, r: 10, t: 10, b: 30 };

/** One variable's normal daily cycle (5–95% band + median) with the reading at its solar hour. */
export const DiurnalChart: React.FC<Props> = ({ profile, variable, title, unit, solarHour, value, decimals = 1 }) => {
  const [wrapRef, width] = useWidth<HTMLDivElement>(260);
  const [tip, setTip] = useState<Tip | null>(null);
  const lo = (r: ProfileRow) => r[`${variable}_p05` as keyof ProfileRow] as number;
  const mid = (r: ProfileRow) => r[`${variable}_p50` as keyof ProfileRow] as number;
  const hi = (r: ProfileRow) => r[`${variable}_p95` as keyof ProfileRow] as number;

  const { x, y, yTicks } = useMemo(() => {
    const [a, b] = extent([...profile.flatMap((r) => [lo(r), hi(r)]), ...(value !== null ? [value] : [])], 0.08);
    return { x: linear(0, 24, M.l, width - M.r), y: linear(a, b, H - M.b, M.t), yTicks: niceTicks(a, b, 3) };
  }, [profile, value, width, variable]);

  const band = `M${profile.map((r) => `${x(r.hour)},${y(hi(r))}`).join('L')}L${[...profile].reverse().map((r) => `${x(r.hour)},${y(lo(r))}`).join('L')}Z`;
  const median = `M${profile.map((r) => `${x(r.hour)},${y(mid(r))}`).join('L')}`;
  const outside = value !== null && (() => {
    const r = profile.reduce((b, c) => (Math.abs(c.hour - solarHour) < Math.abs(b.hour - solarHour) ? c : b), profile[0]);
    return value < lo(r) || value > hi(r);
  })();

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const h = x.invert(e.clientX - rect.left);
    const r = profile.reduce((b, c) => (Math.abs(c.hour - h) < Math.abs(b.hour - h) ? c : b), profile[0]);
    setTip({ x: x(r.hour), y: y(mid(r)), lines: [<b key="b">Solar {hhmm(r.hour - 0.5)}–{hhmm(r.hour + 0.5)}</b>,
      `median ${fmt(mid(r), decimals)} ${unit}`, `90% range ${fmt(lo(r), decimals)} – ${fmt(hi(r), decimals)} ${unit}`] });
  };

  return (
    <div className="ll-chart ll-chart-small" ref={wrapRef}>
      <div className="ll-chart-title">
        {title}
        {value !== null && <span className={outside ? 'll-chip ll-chip-warn' : 'll-chip'}>
          {fmt(value, decimals)} {unit}{outside ? ' · outside usual range for this hour' : ''}
        </span>}
      </div>
      <svg width={width} height={H} role="img" aria-label={`${title}: normal daily cycle with this reading`}>
        <Axes x={x} y={y} xTicks={[0, 6, 12, 18, 24]} yTicks={yTicks} left={M.l} right={width - M.r} top={M.t} bottom={H - M.b}
              xFormat={(v) => `${String(v).padStart(2, '0')}h`} yFormat={(v) => String(Math.round(v * 10) / 10)} />
        {tip && <line x1={tip.x} x2={tip.x} y1={M.t} y2={H - M.b} className="ll-crosshair" />}
        <path d={band} className="ll-band" />
        <path d={median} className="ll-median" />
        {value !== null && <circle cx={x(solarHour)} cy={y(value)} r={5.5} className="ll-reading-marker" />}
        <rect x={M.l} y={M.t} width={width - M.l - M.r} height={H - M.t - M.b} fill="transparent"
              onMouseMove={onMove} onMouseLeave={() => setTip(null)} />
      </svg>
      <ChartTooltip tip={tip} width={width} />
    </div>
  );
};
