import type React from 'react';
import type { WeatherLayerType } from '../../types/weather';
import {
  WIND_COLOR_RAMP,
  TEMP_COLOR_RAMP,
  RAIN_COLOR_RAMP,
  CLOUDS_COLOR_RAMP,
  WAVES_COLOR_RAMP,
  PRESSURE_COLOR_RAMP,
  HUMIDITY_COLOR_RAMP,
  THUNDER_COLOR_RAMP,
  type ColorStop,
} from '../../utils/colorScales';

interface ColorScaleLegendProps {
  layer: WeatherLayerType;
  unitSystem: 'metric' | 'imperial';
}

export const ColorScaleLegend: React.FC<ColorScaleLegendProps> = ({
  layer,
  unitSystem,
}) => {
  let ramp: ColorStop[] = WIND_COLOR_RAMP;
  let unitLabel = unitSystem === 'metric' ? 'km/h' : 'kt';

  if (layer === 'temp') {
    ramp = TEMP_COLOR_RAMP;
    unitLabel = unitSystem === 'metric' ? '°C' : '°F';
  } else if (layer === 'rain' || layer === 'radar') {
    ramp = RAIN_COLOR_RAMP;
    unitLabel = 'mm/h';
  } else if (layer === 'thunder') {
    ramp = THUNDER_COLOR_RAMP;
    unitLabel = 'dBZ';
  } else if (layer === 'humidity') {
    ramp = HUMIDITY_COLOR_RAMP;
    unitLabel = '%';
  } else if (layer === 'clouds' || layer === 'satellite') {
    ramp = CLOUDS_COLOR_RAMP;
    unitLabel = '%';
  } else if (layer === 'waves') {
    ramp = WAVES_COLOR_RAMP;
    unitLabel = 'm';
  } else if (layer === 'pressure') {
    ramp = PRESSURE_COLOR_RAMP;
    unitLabel = 'hPa';
  } else if (layer === 'none' || layer === 'anomalies') {
    return null;
  }

  // Create CSS linear-gradient string
  const stopsStr = ramp
    .map((s, idx) => {
      const pct = (idx / (ramp.length - 1)) * 100;
      return `rgb(${s.r}, ${s.g}, ${s.b}) ${pct}%`;
    })
    .join(', ');

  return (
    <div className="absolute bottom-24 right-3 z-30 hidden sm:flex flex-col gap-1 items-end">
      <div className="windy-glass rounded-xl px-2 py-1.5 shadow-xl flex flex-col gap-1">
        <div className="text-[10px] text-slate-400 font-bold uppercase tracking-wider flex items-center justify-between gap-3">
          <span>{layer}</span>
          <span className="text-cyan-400">{unitLabel}</span>
        </div>

        {/* Gradient Bar */}
        <div
          className="w-36 h-2.5 rounded-full border border-white/20 shadow-inner"
          style={{ background: `linear-gradient(to right, ${stopsStr})` }}
        />

        {/* Numeric Labels */}
        <div className="flex justify-between w-36 text-[9px] text-slate-400 font-medium px-0.5">
          <span>{ramp[0].label}</span>
          <span>{ramp[Math.floor(ramp.length / 2)].label}</span>
          <span>{ramp[ramp.length - 1].label}</span>
        </div>
      </div>
    </div>
  );
};
