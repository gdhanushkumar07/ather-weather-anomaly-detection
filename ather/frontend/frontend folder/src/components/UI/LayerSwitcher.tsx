import type React from 'react';
import {
  Radio,
  Satellite,
  Wind,
  CloudRain,
  Thermometer,
  Cloud,
  Waves,
  Droplets,
  Zap,
} from 'lucide-react';
import type { WeatherLayerType } from '../../types/weather';

interface LayerSwitcherProps {
  activeLayer: WeatherLayerType;
  onSelectLayer: (layer: WeatherLayerType) => void;
}

export const LayerSwitcher: React.FC<LayerSwitcherProps> = ({
  activeLayer,
  onSelectLayer,
}) => {
  const layers: { id: WeatherLayerType; label: string; icon: React.ReactNode }[] = [
    { id: 'radar', label: 'Weather radar', icon: <Radio className="w-3.5 h-3.5 text-emerald-400" /> },
    { id: 'satellite', label: 'Satellite', icon: <Satellite className="w-3.5 h-3.5 text-purple-400" /> },
    { id: 'wind', label: 'Wind', icon: <Wind className="w-3.5 h-3.5 text-cyan-400" /> },
    { id: 'rain', label: 'Rain, thunder', icon: <CloudRain className="w-3.5 h-3.5 text-blue-400" /> },
    { id: 'temp', label: 'Temperature', icon: <Thermometer className="w-3.5 h-3.5 text-amber-400" /> },
    { id: 'clouds', label: 'Clouds', icon: <Cloud className="w-3.5 h-3.5 text-slate-300" /> },
    { id: 'waves', label: 'Waves', icon: <Waves className="w-3.5 h-3.5 text-teal-400" /> },
    { id: 'rain_accu', label: 'Rain accumulation', icon: <Droplets className="w-3.5 h-3.5 text-indigo-400" /> },
    { id: 'thunder', label: 'Thunderstorms', icon: <Zap className="w-3.5 h-3.5 text-violet-400" /> },
  ];

  return (
    <div className="absolute top-14 right-3 z-30 flex flex-col items-end">
      <div className="windy-glass rounded-xl p-1 shadow-2xl flex flex-col gap-0.5 w-36 sm:w-40 border border-white/10">
        {layers.map((l) => {
          const isActive = activeLayer === l.id;
          return (
            <button
              key={l.id}
              onClick={() => onSelectLayer(isActive ? 'none' : l.id)}
              className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all group ${
                isActive
                  ? 'bg-gradient-to-r from-cyan-500/30 to-blue-500/25 text-white font-semibold border border-cyan-400/40 shadow-sm shadow-cyan-500/10'
                  : 'text-slate-300 hover:bg-white/10 hover:text-white'
              }`}
            >
              <div className="flex items-center gap-2">
                <div className="transform transition-transform group-hover:scale-110 shrink-0">
                  {l.icon}
                </div>
                <span className="truncate">{l.label}</span>
              </div>

              {isActive && (
                <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-sm shadow-cyan-400 animate-pulse shrink-0 ml-1" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};
