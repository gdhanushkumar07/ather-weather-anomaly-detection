import React from 'react';
import { WeatherLayer, WindSpeedUnit, TempUnit } from '../types';

interface LegendScaleProps {
  layer: WeatherLayer;
  windUnit: WindSpeedUnit;
  onToggleWindUnit: () => void;
  tempUnit: TempUnit;
  onToggleTempUnit: () => void;
}

export const LegendScale: React.FC<LegendScaleProps> = ({
  layer,
  windUnit,
  onToggleWindUnit,
  tempUnit,
  onToggleTempUnit,
}) => {
  const renderScale = () => {
    switch (layer) {
      case 'wind':
      case 'gusts': {
        const stops = windUnit === 'kt'
          ? [0, 5, 10, 15, 20, 25, 30, 40, 50, 60]
          : [0, 10, 20, 30, 45, 60, 80, 100, 120, 140];
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">
                {layer === 'gusts' ? 'Wind Gusts' : 'Wind Velocity'}
              </span>
              <button
                id="legend-wind-unit-btn"
                onClick={onToggleWindUnit}
                className="hover:text-sky-300 underline cursor-pointer font-bold"
              >
                {windUnit}
              </button>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#a5d6ff]" />
              <div className="flex-1 bg-[#38bdf8]" />
              <div className="flex-1 bg-[#34d399]" />
              <div className="flex-1 bg-[#facc15]" />
              <div className="flex-1 bg-[#fb923c]" />
              <div className="flex-1 bg-[#ef4444]" />
              <div className="flex-1 bg-[#d946ef]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              {stops.filter((_, i) => i % 2 === 0).map((val, idx) => (
                <span key={idx}>{val}</span>
              ))}
            </div>
          </div>
        );
      }

      case 'temperature': {
        const stops = tempUnit === 'c' 
          ? [-15, -5, 5, 15, 25, 35, 45]
          : [5, 23, 41, 59, 77, 95, 113];
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Temperature</span>
              <button
                id="legend-temp-unit-btn"
                onClick={onToggleTempUnit}
                className="hover:text-amber-300 underline cursor-pointer font-bold"
              >
                °{tempUnit.toUpperCase()}
              </button>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#a855f7]" />
              <div className="flex-1 bg-[#6366f1]" />
              <div className="flex-1 bg-[#3b82f6]" />
              <div className="flex-1 bg-[#2dd4bf]" />
              <div className="flex-1 bg-[#4ade80]" />
              <div className="flex-1 bg-[#facc15]" />
              <div className="flex-1 bg-[#fb923c]" />
              <div className="flex-1 bg-[#ef4444]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              {stops.map((val, idx) => (
                <span key={idx}>{val}°</span>
              ))}
            </div>
          </div>
        );
      }

      case 'rain':
      case 'rain_accum': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">
                {layer === 'rain_accum' ? 'Rain Accumulation' : 'Rain Rate'}
              </span>
              <span className="font-bold text-emerald-400">mm / h</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#38bdf8]" />
              <div className="flex-1 bg-[#22c55e]" />
              <div className="flex-1 bg-[#eab308]" />
              <div className="flex-1 bg-[#f97316]" />
              <div className="flex-1 bg-[#ef4444]" />
              <div className="flex-1 bg-[#d946ef]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>0.5</span>
              <span>2</span>
              <span>6</span>
              <span>15</span>
              <span>30</span>
              <span>50+</span>
            </div>
          </div>
        );
      }

      case 'radar': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Weather Radar</span>
              <span className="font-bold text-sky-400">dBZ</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#4ade80]" />
              <div className="flex-1 bg-[#facc15]" />
              <div className="flex-1 bg-[#fb923c]" />
              <div className="flex-1 bg-[#ef4444]" />
              <div className="flex-1 bg-[#d946ef]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>15 Lgt</span>
              <span>30 Mod</span>
              <span>45 Hvy</span>
              <span>60+ Ext</span>
            </div>
          </div>
        );
      }

      case 'pressure': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Atmospheric Pressure</span>
              <span className="font-bold text-blue-400">hPa</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#ef4444]" />
              <div className="flex-1 bg-[#fb923c]" />
              <div className="flex-1 bg-slate-400" />
              <div className="flex-1 bg-[#3b82f6]" />
              <div className="flex-1 bg-[#1e40af]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>980 Low</span>
              <span>1000</span>
              <span>1013 Norm</span>
              <span>1025</span>
              <span>1035 High</span>
            </div>
          </div>
        );
      }

      case 'clouds': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Cloud Coverage</span>
              <span className="font-bold text-slate-300">%</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-slate-700/60" />
              <div className="flex-1 bg-slate-500" />
              <div className="flex-1 bg-slate-300" />
              <div className="flex-1 bg-slate-100" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>0% Clear</span>
              <span>30% Scat</span>
              <span>70% Bkn</span>
              <span>100% Ovc</span>
            </div>
          </div>
        );
      }

      case 'humidity': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Relative Humidity</span>
              <span className="font-bold text-cyan-400">%</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#d97706]" />
              <div className="flex-1 bg-[#eab308]" />
              <div className="flex-1 bg-[#0d9488]" />
              <div className="flex-1 bg-[#2563eb]" />
              <div className="flex-1 bg-[#1d4ed8]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>15% Arid</span>
              <span>40%</span>
              <span>65% Mod</span>
              <span>85%</span>
              <span>98% Sat</span>
            </div>
          </div>
        );
      }

      case 'thunderstorms': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-amber-400">Storm Instability</span>
              <span className="font-bold text-amber-400">CAPE (J/kg)</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-emerald-500" />
              <div className="flex-1 bg-yellow-400" />
              <div className="flex-1 bg-orange-500" />
              <div className="flex-1 bg-fuchsia-600" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-300 px-0.5">
              <span>0 Stable</span>
              <span>1000 Mod</span>
              <span>2000 High</span>
              <span>3000+ Severe</span>
            </div>
          </div>
        );
      }

      case 'waves': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-slate-400">Wave Height</span>
              <span className="font-bold text-cyan-300">m</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-[#0ea5e9]" />
              <div className="flex-1 bg-[#0d9488]" />
              <div className="flex-1 bg-[#eab308]" />
              <div className="flex-1 bg-[#ef4444]" />
            </div>
            <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
              <span>0.5m Calm</span>
              <span>2.0m Mod</span>
              <span>4.0m Rough</span>
              <span>7.0m+ High</span>
            </div>
          </div>
        );
      }

      case 'satellite': {
        return (
          <div className="flex items-center gap-2 text-[10px] font-mono text-slate-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-semibold text-slate-300">Real Earth Satellite Imagery</span>
            <span className="text-slate-500">(Esri / NASA)</span>
          </div>
        );
      }

      case 'anomaly': {
        return (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[10px] text-slate-300 font-mono">
              <span className="font-semibold uppercase text-red-400">AI Anomaly Index</span>
              <span className="font-bold text-red-400">D0 - D5</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden flex w-48 sm:w-60 shadow-inner">
              <div className="flex-1 bg-emerald-500" />
              <div className="flex-1 bg-yellow-400" />
              <div className="flex-1 bg-orange-400" />
              <div className="flex-1 bg-red-500" />
              <div className="flex-1 bg-purple-600" />
            </div>
            <div className="flex justify-between text-[9px] font-bold text-slate-300 px-0.5">
              <span>D0 Normal</span>
              <span>D2 Mod</span>
              <span>D4 Sev</span>
              <span className="text-red-400">D5 Extreme</span>
            </div>
          </div>
        );
      }

      default:
        return null;
    }
  };

  const content = renderScale();
  if (!content) return null;

  return (
    <div 
      id="ather-color-legend"
      className="absolute bottom-28 left-4 z-[990] bg-[#1e222a]/90 backdrop-blur-md border border-white/10 rounded-xl p-2.5 shadow-xl pointer-events-auto select-none"
    >
      {content}
    </div>
  );
};
