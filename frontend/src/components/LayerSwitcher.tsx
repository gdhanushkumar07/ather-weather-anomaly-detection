import React, { useState } from 'react';
import { 
  Plane,
  X,
  AlertTriangle,
  Layers,
  Activity,
  HeartPulse,
  EyeOff,
  Info
} from 'lucide-react';
import { WeatherLayer, AltitudeLevel, AtherMapMode } from '../types';

interface LayerSwitcherProps {
  activeLayer: WeatherLayer;
  onSelectLayer: (layer: WeatherLayer) => void;
  altitudeLevel: AltitudeLevel;
  onSelectAltitude: (alt: AltitudeLevel) => void;
  showAwsStations?: boolean;
  onToggleAwsStations?: () => void;
  mapMode: AtherMapMode;
  onSelectMapMode: (mode: AtherMapMode) => void;
}

export const LayerSwitcher: React.FC<LayerSwitcherProps> = ({
  activeLayer,
  onSelectLayer,
  altitudeLevel,
  onSelectAltitude,
  showAwsStations = true,
  onToggleAwsStations,
  mapMode,
  onSelectMapMode,
}) => {
  const [isAltitudeOpen, setIsAltitudeOpen] = useState(false);
  const [showContextual, setShowContextual] = useState(true);

  // 1. Primary Atmospheric Layers (Core ATHER Inputs to Anomaly Engine)
  const primaryAtherLayers: { 
    id: WeatherLayer; 
    label: string; 
    thumbClass: string; 
    iconSymbol: string;
    description: string;
  }[] = [
    {
      id: 'temperature',
      label: 'Temperature',
      thumbClass: 'from-indigo-600 via-amber-400 to-red-500',
      iconSymbol: '🌡️',
      description: 'Surface Dry-Bulb Temperature (°C)',
    },
    {
      id: 'pressure',
      label: 'Pressure',
      thumbClass: 'from-indigo-900 via-blue-700 to-teal-500',
      iconSymbol: '🧭',
      description: 'Atmospheric Pressure & Isobars (hPa)',
    },
    {
      id: 'humidity',
      label: 'Relative Humidity',
      thumbClass: 'from-teal-800 via-cyan-600 to-blue-400',
      iconSymbol: '💧',
      description: 'Psychrometric Moisture Content (%)',
    },
  ];

  // 2. Contextual Meteorological Layers (Kept as environmental background context, not anomaly inputs)
  const contextualLayers: { 
    id: WeatherLayer; 
    label: string; 
    thumbClass: string; 
    iconSymbol: string;
  }[] = [
    {
      id: 'wind',
      label: 'Wind Streamlines',
      thumbClass: 'from-emerald-600 via-teal-400 to-sky-400',
      iconSymbol: '∿',
    },
    {
      id: 'rain',
      label: 'Precipitation',
      thumbClass: 'from-slate-800 via-blue-600 to-cyan-400',
      iconSymbol: '🌧️',
    },
    {
      id: 'radar',
      label: 'Doppler Radar',
      thumbClass: 'from-emerald-500 via-yellow-400 to-red-500',
      iconSymbol: '📡',
    },
    {
      id: 'satellite',
      label: 'Satellite Imagery',
      thumbClass: 'from-blue-950 via-slate-700 to-sky-400',
      iconSymbol: '🛰️',
    },
    {
      id: 'clouds',
      label: 'Cloud Cover',
      thumbClass: 'from-slate-700 via-slate-400 to-white',
      iconSymbol: '☁️',
    },
  ];

  const altitudes: { id: AltitudeLevel; label: string; desc: string }[] = [
    { id: 'surface', label: 'Surface', desc: '10 m' },
    { id: '100m', label: '100 m', desc: 'Boundary' },
    { id: '900m', label: '900 m', desc: '850 hPa' },
    { id: '3000m', label: '3000 m', desc: '700 hPa' },
    { id: '5500m', label: '5500 m', desc: '500 hPa' },
    { id: '9000m', label: '9000 m', desc: '300 hPa' },
    { id: 'jetstream', label: 'Jet stream', desc: '250 hPa' },
  ];

  return (
    <aside className="fixed top-14 right-3 z-[995] flex flex-col items-end gap-2 pointer-events-auto select-none max-h-[calc(100vh-80px)] overflow-y-auto pr-0.5">
      {/* Active Layer Status / Clear Button */}
      {activeLayer !== 'none' ? (
        <button
          id="btn-clear-layer-to-none"
          onClick={() => onSelectLayer('none')}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-950/90 border border-sky-400/70 text-sky-200 hover:text-white text-[11px] font-semibold backdrop-blur-md shadow-lg transition-all hover:bg-sky-900 cursor-pointer"
          title="Click to clear active weather field"
        >
          <EyeOff className="w-3.5 h-3.5 text-sky-400" />
          <span>Active: <strong className="text-white capitalize">{activeLayer}</strong> (Clear)</span>
        </button>
      ) : (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#181d26]/80 border border-white/10 text-slate-300 text-[10.5px] font-mono backdrop-blur-md">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Basemap Clean (No Field)</span>
        </div>
      )}

      {/* SECTION 1: PRIMARY ATMOSPHERIC LAYERS (ATHER Core Inputs) */}
      <div className="flex flex-col items-end gap-1.5 mt-1">
        <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider pr-1">
          ATHER Core Inputs
        </div>

        {primaryAtherLayers.map((l) => {
          const isActive = activeLayer === l.id;
          return (
            <button
              key={l.id}
              id={`sidebar-layer-${l.id}`}
              onClick={() => onSelectLayer(isActive ? 'none' : l.id)}
              className="group flex items-center justify-end gap-2 transition-transform active:scale-95 cursor-pointer text-right"
              title={`${l.description} - ${isActive ? 'Deactivate' : 'Activate'}`}
            >
              <span
                className={`text-[11.5px] transition-all px-2.5 py-1 rounded-lg shadow-md whitespace-nowrap backdrop-blur-md flex items-center gap-1.5 ${
                  isActive
                    ? 'text-white font-bold bg-sky-950/90 border border-sky-400/80 shadow-sky-500/20'
                    : 'text-slate-200 group-hover:text-white bg-[#181d26]/80 group-hover:bg-[#181d26]/95 border border-white/10'
                }`}
              >
                <span className={isActive ? 'text-sky-400 font-bold text-xs' : 'text-slate-400 text-xs'}>
                  {isActive ? '◉' : '○'}
                </span>
                <span>{l.label}</span>
              </span>

              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center transition-all shadow-lg border relative overflow-hidden bg-gradient-to-br ${l.thumbClass} ${
                  isActive
                    ? 'ring-2 ring-sky-400 ring-offset-2 ring-offset-[#12151b] scale-105 border-white shadow-sky-500/30'
                    : 'border-white/30 opacity-85 group-hover:opacity-100 group-hover:scale-105'
                }`}
              >
                <span className="text-[12px] drop-shadow-sm select-none">{l.iconSymbol}</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* SECTION 2: CONTEXTUAL METEOROLOGICAL LAYERS */}
      <div className="flex flex-col items-end gap-1.5 mt-2">
        <div className="flex items-center justify-end gap-1 pr-1">
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            Contextual Weather
          </span>
          <button
            onClick={() => setShowContextual(!showContextual)}
            className="text-slate-400 hover:text-white text-[10px]"
          >
            {showContextual ? '▼' : '▶'}
          </button>
        </div>

        {showContextual && (
          <div className="flex flex-col items-end gap-1.5">
            {contextualLayers.map((l) => {
              const isActive = activeLayer === l.id;
              return (
                <button
                  key={l.id}
                  id={`sidebar-layer-${l.id}`}
                  onClick={() => onSelectLayer(isActive ? 'none' : l.id)}
                  className="group flex items-center justify-end gap-2 transition-transform active:scale-95 cursor-pointer text-right"
                  title={`${l.label} (Contextual overlay)`}
                >
                  <span
                    className={`text-[11.5px] transition-all px-2.5 py-1 rounded-lg shadow-md whitespace-nowrap backdrop-blur-md flex items-center gap-1.5 ${
                      isActive
                        ? 'text-white font-bold bg-sky-950/90 border border-sky-400/80 shadow-sky-500/20'
                        : 'text-slate-300 group-hover:text-white bg-[#181d26]/75 group-hover:bg-[#181d26]/90 border border-white/10'
                    }`}
                  >
                    <span className={isActive ? 'text-sky-400 font-bold text-xs' : 'text-slate-500 text-xs'}>
                      {isActive ? '◉' : '○'}
                    </span>
                    <span>{l.label}</span>
                  </span>

                  <div
                    className={`w-7 h-7 rounded-full flex items-center justify-center transition-all shadow-lg border relative overflow-hidden bg-gradient-to-br ${l.thumbClass} ${
                      isActive
                        ? 'ring-2 ring-sky-400 ring-offset-2 ring-offset-[#12151b] scale-105 border-white shadow-sky-500/30'
                        : 'border-white/30 opacity-75 group-hover:opacity-100 group-hover:scale-105'
                    }`}
                  >
                    <span className="text-[11px] drop-shadow-sm select-none">{l.iconSymbol}</span>
                  </div>
                </button>
              );
            })}

            {/* Altitude Button */}
            <div className="relative mt-1 flex items-center justify-end">
              <button
                id="sidebar-altitude-btn"
                onClick={() => setIsAltitudeOpen(!isAltitudeOpen)}
                className="group flex items-center justify-end gap-2 transition-transform active:scale-95 cursor-pointer"
                title="Atmospheric Altitude Levels"
              >
                <span className="text-[11px] font-bold text-white bg-[#181d26]/75 group-hover:bg-[#181d26]/90 border border-white/10 px-2 py-1 rounded-lg shadow-md backdrop-blur-md">
                  Altitude ({altitudes.find((a) => a.id === altitudeLevel)?.label})
                </span>
                <div className="w-7 h-7 rounded-full bg-[#e0633b] hover:bg-[#cf552e] text-white flex items-center justify-center shadow-lg border border-white/30 transition-all group-hover:scale-105">
                  <Plane className="w-3.5 h-3.5 rotate-45" />
                </div>
              </button>

              {isAltitudeOpen && (
                <div className="absolute top-0 right-full mr-3 w-40 bg-[#181d26]/95 backdrop-blur-xl border border-white/15 rounded-xl shadow-2xl p-1.5 flex flex-col gap-1 z-[1100]">
                  <div className="flex items-center justify-between px-2 py-1 text-[10px] font-bold text-slate-400 uppercase border-b border-white/10">
                    <span>Altitude</span>
                    <button onClick={() => setIsAltitudeOpen(false)} className="text-slate-400 hover:text-white">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                  {altitudes.map((alt) => (
                    <button
                      key={alt.id}
                      id={`altitude-opt-${alt.id}`}
                      onClick={() => {
                        onSelectAltitude(alt.id);
                        setIsAltitudeOpen(false);
                      }}
                      className={`w-full flex items-center justify-between px-2 py-1.5 text-xs rounded-lg transition-colors cursor-pointer ${
                        altitudeLevel === alt.id ? 'bg-[#e0633b] text-white font-bold' : 'text-slate-200 hover:bg-white/10'
                      }`}
                    >
                      <span>{alt.label}</span>
                      <span className="text-[10px] text-slate-400">{alt.desc}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Network Station Marker Quick Toggle */}
      <div className="mt-2 flex flex-col items-end gap-1">
        <button
          id="toggle-aws-stations-btn"
          onClick={onToggleAwsStations}
          className={`flex items-center gap-2 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all shadow-md backdrop-blur-md border cursor-pointer ${
            showAwsStations
              ? 'bg-[#181d26]/90 border-emerald-400/60 text-emerald-300'
              : 'bg-[#181d26]/60 border-white/10 text-slate-400 hover:text-white'
          }`}
          title="Toggle AWS Stations on/off"
        >
          <span className={`w-2 h-2 rounded-full ${showAwsStations ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
          <span>AWS Markers ({showAwsStations ? 'ON' : 'OFF'})</span>
        </button>
      </div>
    </aside>
  );
};
