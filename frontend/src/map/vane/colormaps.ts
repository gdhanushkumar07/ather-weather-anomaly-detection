/**
 * Colormap lookup tables adapted from Vane (Apache-2.0, (c) Rijwind contributors)
 */

export type ColormapStops = Array<[number, string]>;
export type Colormap = string | ColormapStops;

export const TEMPERATURE_STOPS: ColormapStops = [
  [-30, '#7c3aed'],
  [-20, '#6366f1'],
  [-10, '#3b82f6'],
  [-5, '#0ea5e9'],
  [0, '#22d3ee'],
  [5, '#2dd4bf'],
  [10, '#4ade80'],
  [15, '#a3e635'],
  [20, '#facc15'],
  [25, '#fb923c'],
  [30, '#ef4444'],
  [35, '#b91c1c'],
  [45, '#7f1d1d'],
];
export const TEMPERATURE_CLIM: [number, number] = [-30, 45];

export function parseColor(hex: string): [number, number, number, number] {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  if (h.length === 6) h += 'ff';
  const n = parseInt(h, 16);
  return [(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff];
}

export function buildLut(colormap: ColormapStops, clim: [number, number]): Uint8Array {
  const [lo, hi] = clim;
  const positions = colormap.map(([value]) => (value - lo) / (hi - lo));
  const colors = colormap.map(([, color]) => parseColor(color));

  const lut = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let j = 0;
    while (j < positions.length - 2 && t > positions[j + 1]!) j++;
    const t0 = positions[j]!;
    const t1 = positions[j + 1]!;
    const f = Math.min(1, Math.max(0, t1 === t0 ? 0 : (t - t0) / (t1 - t0)));
    for (let c = 0; c < 4; c++) {
      lut[i * 4 + c] = Math.round(colors[j]![c]! + (colors[j + 1]![c]! - colors[j]![c]!) * f);
    }
  }
  return lut;
}
