// Color ramps mirroring Windy.com's signature meteorological palettes

export interface ColorStop {
  val: number; // Value in base unit
  r: number;
  g: number;
  b: number;
  a?: number;
  label?: string;
}

export const WIND_COLOR_RAMP: ColorStop[] = [
  { val: 0, r: 40, g: 60, b: 120, label: '0' },
  { val: 5, r: 44, g: 110, b: 160, label: '5' },
  { val: 10, r: 50, g: 155, b: 170, label: '10' },
  { val: 15, r: 60, g: 180, b: 140, label: '15' },
  { val: 20, r: 90, g: 195, b: 90, label: '20' },
  { val: 25, r: 160, g: 205, b: 60, label: '25' },
  { val: 30, r: 215, g: 200, b: 40, label: '30' },
  { val: 35, r: 240, g: 150, b: 30, label: '35' },
  { val: 40, r: 235, g: 90, b: 35, label: '40' },
  { val: 50, r: 220, g: 45, b: 50, label: '50' },
  { val: 60, r: 180, g: 30, b: 100, label: '60' },
  { val: 75, r: 140, g: 25, b: 150, label: '75+' },
];

export const TEMP_COLOR_RAMP: ColorStop[] = [
  { val: -30, r: 180, g: 70, b: 210, label: '-30°' },
  { val: -20, r: 100, g: 60, b: 190, label: '-20°' },
  { val: -10, r: 40, g: 90, b: 190, label: '-10°' },
  { val: 0, r: 60, g: 170, b: 230, label: '0°' },
  { val: 10, r: 70, g: 210, b: 200, label: '10°' },
  { val: 18, r: 100, g: 210, b: 120, label: '18°' },
  { val: 24, r: 170, g: 220, b: 70, label: '24°' },
  { val: 30, r: 245, g: 195, b: 40, label: '30°' },
  { val: 36, r: 245, g: 120, b: 30, label: '36°' },
  { val: 42, r: 230, g: 45, b: 35, label: '42°' },
  { val: 50, r: 160, g: 20, b: 60, label: '50°+' },
];

export const RAIN_COLOR_RAMP: ColorStop[] = [
  { val: 0, r: 0, g: 0, b: 0, a: 0, label: '0 mm' },
  { val: 0.5, r: 70, g: 150, b: 210, a: 0.6, label: '0.5' },
  { val: 2, r: 50, g: 180, b: 130, a: 0.75, label: '2' },
  { val: 5, r: 110, g: 200, b: 60, a: 0.8, label: '5' },
  { val: 10, r: 220, g: 210, b: 40, a: 0.85, label: '10' },
  { val: 20, r: 240, g: 130, b: 30, a: 0.9, label: '20' },
  { val: 40, r: 230, g: 40, b: 40, a: 0.95, label: '40' },
  { val: 70, r: 170, g: 20, b: 160, a: 1.0, label: '70+' },
];

export const CLOUDS_COLOR_RAMP: ColorStop[] = [
  { val: 0, r: 0, g: 0, b: 0, a: 0, label: '0%' },
  { val: 25, r: 140, g: 160, b: 180, a: 0.35, label: '25%' },
  { val: 50, r: 190, g: 205, b: 220, a: 0.6, label: '50%' },
  { val: 75, r: 225, g: 235, b: 245, a: 0.8, label: '75%' },
  { val: 100, r: 255, g: 255, b: 255, a: 0.95, label: '100%' },
];

export const WAVES_COLOR_RAMP: ColorStop[] = [
  { val: 0, r: 20, g: 60, b: 100, label: '0m' },
  { val: 1, r: 35, g: 110, b: 150, label: '1m' },
  { val: 2, r: 40, g: 160, b: 160, label: '2m' },
  { val: 3.5, r: 80, g: 190, b: 120, label: '3.5m' },
  { val: 5, r: 180, g: 190, b: 50, label: '5m' },
  { val: 7, r: 230, g: 120, b: 40, label: '7m' },
  { val: 10, r: 220, g: 30, b: 70, label: '10m+' },
];

export const PRESSURE_COLOR_RAMP: ColorStop[] = [
  { val: 980, r: 160, g: 40, b: 140, label: '980 hPa' },
  { val: 995, r: 60, g: 70, b: 180, label: '995' },
  { val: 1010, r: 50, g: 150, b: 180, label: '1010' },
  { val: 1020, r: 80, g: 180, b: 100, label: '1020' },
  { val: 1035, r: 220, g: 140, b: 40, label: '1035+' },
];

export const HUMIDITY_COLOR_RAMP: ColorStop[] = [
  { val: 10, r: 160, g: 100, b: 40, label: '10%' },
  { val: 30, r: 200, g: 170, b: 50, label: '30%' },
  { val: 50, r: 90, g: 185, b: 130, label: '50%' },
  { val: 70, r: 45, g: 155, b: 210, label: '70%' },
  { val: 85, r: 30, g: 90, b: 220, label: '85%' },
  { val: 100, r: 110, g: 40, b: 190, label: '100%' },
];

export const THUNDER_COLOR_RAMP: ColorStop[] = [
  { val: 0, r: 0, g: 0, b: 0, a: 0, label: '0%' },
  { val: 20, r: 80, g: 170, b: 80, a: 0.6, label: '20%' },
  { val: 40, r: 220, g: 200, b: 30, a: 0.8, label: '40%' },
  { val: 65, r: 240, g: 110, b: 30, a: 0.9, label: '65%' },
  { val: 85, r: 220, g: 30, b: 60, a: 0.95, label: '85%' },
  { val: 100, r: 170, g: 20, b: 210, a: 1.0, label: 'Severe' },
];

export const ANOMALY_SEVERITY_CONFIG = {
  D0: { code: 'D0', label: 'Abnormally Dry', color: '#facc15', bg: 'rgba(250, 204, 21, 0.2)', border: '#facc15', status: 'Healthy' },
  D1: { code: 'D1', label: 'Moderate Drought', color: '#fb923c', bg: 'rgba(251, 146, 60, 0.2)', border: '#fb923c', status: 'Moderate' },
  D2: { code: 'D2', label: 'Severe Drought', color: '#f97316', bg: 'rgba(249, 115, 22, 0.2)', border: '#f97316', status: 'Severe' },
  D3: { code: 'D3', label: 'Extreme Drought', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.2)', border: '#ef4444', status: 'Critical' },
  D4: { code: 'D4', label: 'Exceptional Drought', color: '#b91c1c', bg: 'rgba(185, 28, 28, 0.2)', border: '#b91c1c', status: 'Critical' },
  D5: { code: 'D5', label: 'Catastrophic Stress', color: '#7f1d1d', bg: 'rgba(127, 29, 29, 0.25)', border: '#ef4444', status: 'Critical' },
};

export function interpolateColor(ramp: ColorStop[], val: number): string {
  if (val <= ramp[0].val) {
    const s = ramp[0];
    return `rgba(${s.r}, ${s.g}, ${s.b}, ${s.a ?? 1})`;
  }
  if (val >= ramp[ramp.length - 1].val) {
    const s = ramp[ramp.length - 1];
    return `rgba(${s.r}, ${s.g}, ${s.b}, ${s.a ?? 1})`;
  }

  for (let i = 0; i < ramp.length - 1; i++) {
    const c1 = ramp[i];
    const c2 = ramp[i + 1];
    if (val >= c1.val && val <= c2.val) {
      const t = (val - c1.val) / (c2.val - c1.val);
      const r = Math.round(c1.r + t * (c2.r - c1.r));
      const g = Math.round(c1.g + t * (c2.g - c1.g));
      const b = Math.round(c1.b + t * (c2.b - c1.b));
      const a = (c1.a ?? 1) + t * ((c2.a ?? 1) - (c1.a ?? 1));
      return `rgba(${r}, ${g}, ${b}, ${a})`;
    }
  }

  return 'rgba(0,0,0,0)';
}
