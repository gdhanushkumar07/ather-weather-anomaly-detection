import React, { useState } from 'react';
import { 
  Plus, 
  Minus, 
  Box, 
  Info, 
  Maximize2, 
  Minimize2, 
  Wind, 
  Thermometer, 
  CloudRain, 
  Video, 
  Plane, 
  Cloud,
  ChevronDown,
  Activity,
  X,
  Compass
} from 'lucide-react';
import { WeatherLayer, WeatherModel, StationType, WindSpeedUnit, TempUnit } from '../types';

interface BottomControlBarProps {
  onZoomIn: () => void;
  onZoomOut: () => void;
  is3D: boolean;
  onToggle3D: () => void;
  showParticles: boolean;
  onToggleParticles: () => void;
  showPressureIsolines: boolean;
  onTogglePressureIsolines: () => void;
  selectedModel: WeatherModel;
  onSelectModel: (model: WeatherModel) => void;
  activeLayer: WeatherLayer;
  onSelectLayer: (layer: WeatherLayer) => void;
  stationType: StationType | null;
  onSelectStationType: (type: StationType | null) => void;
  onOpenInfo: () => void;
  onFocusStorm: () => void;
  windUnit: WindSpeedUnit;
  onToggleWindUnit: () => void;
  tempUnit: TempUnit;
  onToggleTempUnit: () => void;
}

export const BottomControlBar: React.FC<BottomControlBarProps> = ({
  onZoomIn,
  onZoomOut,
  is3D,
  onToggle3D,
  showParticles,
  onToggleParticles,
  showPressureIsolines,
  onTogglePressureIsolines,
  selectedModel,
  onSelectModel,
  activeLayer,
  onSelectLayer,
  stationType,
  onSelectStationType,
  onOpenInfo,
  onFocusStorm,
  windUnit,
  onToggleWindUnit,
  tempUnit,
  onToggleTempUnit,
}) => {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isMoreModelsOpen, setIsMoreModelsOpen] = useState(false);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
        setIsFullscreen(false);
      }
    }
  };

  const models: { id: WeatherModel; name: string; res: string }[] = [
    { id: 'ecmwf', name: 'ECMWF', res: '9km' },
    { id: 'gfs', name: 'GFS', res: '22km' },
    { id: 'icon', name: 'ICON', res: '13km' },
  ];

  return (
    <div className="fixed bottom-[68px] sm:bottom-[72px] right-3 z-[990] flex flex-col items-end gap-1.5 pointer-events-auto select-none">
      {/* 1. Toggle Switches: Pressure & Particles Animation */}
      <div className="flex items-center gap-2.5 text-[11px] text-slate-300">
        {/* Pressure Isolines Switch */}
        <button
          id="toggle-pressure-isolines-btn"
          onClick={onTogglePressureIsolines}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#181d26]/80 backdrop-blur-md border border-white/10 shadow-lg transition-all cursor-pointer ${
            showPressureIsolines ? 'text-white font-semibold border-sky-400/40' : 'text-slate-400 hover:text-slate-200'
          }`}
          title="Toggle atmospheric pressure isobars"
        >
          <div className={`w-3 h-3 rounded-full border flex items-center justify-center transition-colors ${
            showPressureIsolines ? 'border-sky-400 bg-sky-500 shadow-sm' : 'border-slate-500'
          }`}>
            {showPressureIsolines && <div className="w-1 h-1 rounded-full bg-white" />}
          </div>
          <span>pressure</span>
        </button>

        {/* Particles Animation Switch */}
        <button
          id="toggle-particles-btn"
          onClick={() => {
            if (activeLayer !== 'wind') {
              onSelectLayer('wind');
            } else {
              onToggleParticles();
            }
          }}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#181d26]/80 backdrop-blur-md border border-white/10 shadow-lg transition-all cursor-pointer ${
            activeLayer === 'wind' && showParticles ? 'text-white font-semibold border-sky-400/60 bg-sky-950/40' : 'text-slate-400 hover:text-slate-200'
          }`}
          title={activeLayer === 'wind' ? "Toggle animated wind particle flow" : "Activate Wind layer with particles"}
        >
          <div className={`w-3 h-3 rounded-full border flex items-center justify-center transition-colors ${
            activeLayer === 'wind' && showParticles ? 'border-sky-400 bg-sky-500 shadow-sm' : 'border-slate-500'
          }`}>
            {activeLayer === 'wind' && showParticles && <div className="w-1 h-1 rounded-full bg-white" />}
          </div>
          <span>particles animation</span>
        </button>
      </div>

      {/* 2. Floating Action Button Bar: + | - | 3D | (i) | 📍 | ⛶ */}
      <div className="flex items-center bg-[#181d26]/85 backdrop-blur-md rounded-xl border border-white/10 shadow-xl overflow-hidden divide-x divide-white/10 text-slate-200 text-xs">
        <button
          id="control-zoom-in-btn"
          onClick={onZoomIn}
          className="w-7 h-7 flex items-center justify-center hover:bg-white/15 hover:text-white transition-colors cursor-pointer active:scale-95"
          title="Zoom In"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button
          id="control-zoom-out-btn"
          onClick={onZoomOut}
          className="w-7 h-7 flex items-center justify-center hover:bg-white/15 hover:text-white transition-colors cursor-pointer active:scale-95"
          title="Zoom Out"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button
          id="control-3d-btn"
          onClick={onToggle3D}
          className={`px-2 h-7 flex items-center justify-center transition-colors cursor-pointer font-bold text-[11px] ${
            is3D ? 'bg-sky-500 text-white shadow-inner' : 'hover:bg-white/15 hover:text-white text-slate-300'
          }`}
          title="Toggle 3D Perspective Tilt"
        >
          3D
        </button>
        <button
          id="control-info-btn"
          onClick={onOpenInfo}
          className="w-7 h-7 flex items-center justify-center hover:bg-white/15 hover:text-white transition-colors cursor-pointer"
          title="Meteorological Information"
        >
          <Info className="w-3.5 h-3.5" />
        </button>
        <button
          id="control-cyclone-btn"
          onClick={onFocusStorm}
          className="w-7 h-7 flex items-center justify-center hover:bg-white/15 hover:text-red-400 transition-colors cursor-pointer text-red-400"
          title="Focus on Active Tropical Cyclone"
        >
          <Compass className="w-3.5 h-3.5" />
        </button>
        <button
          id="control-fullscreen-btn"
          onClick={toggleFullscreen}
          className="w-7 h-7 flex items-center justify-center hover:bg-white/15 hover:text-white transition-colors cursor-pointer"
          title="Toggle Fullscreen"
        >
          {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* 3. Observation / Station Icons Bar: ☁ | 🚩 | ✈ | 📹 | ✕ | ··· */}
      <div className="flex items-center bg-[#181d26]/85 backdrop-blur-md px-1.5 py-1 rounded-xl border border-white/10 shadow-xl gap-1 text-xs">
        <button
          id="station-cloud-btn"
          onClick={() => onSelectLayer('clouds')}
          className={`p-1 rounded-lg transition-colors cursor-pointer ${
            activeLayer === 'clouds' ? 'text-sky-300 bg-white/15' : 'text-slate-400 hover:text-white'
          }`}
          title="Clouds Layer"
        >
          <Cloud className="w-3.5 h-3.5" />
        </button>
        <button
          id="station-wind-btn"
          onClick={() => onSelectStationType(stationType === 'wmo' ? null : 'wmo')}
          className={`p-1 rounded-lg transition-colors cursor-pointer ${
            stationType === 'wmo' ? 'text-amber-400 bg-white/15' : 'text-slate-400 hover:text-white'
          }`}
          title="WMO Weather Stations"
        >
          <Wind className="w-3.5 h-3.5" />
        </button>
        <button
          id="station-airp-btn"
          onClick={() => onSelectStationType(stationType === 'airp' ? null : 'airp')}
          className={`p-1 rounded-lg transition-colors cursor-pointer ${
            stationType === 'airp' ? 'text-sky-400 bg-white/15' : 'text-slate-400 hover:text-white'
          }`}
          title="Airport Weather Stations"
        >
          <Plane className="w-3.5 h-3.5 rotate-45" />
        </button>
        <button
          id="station-webcam-btn"
          onClick={() => onSelectStationType(stationType === 'buoy' ? null : 'buoy')}
          className={`p-1 rounded-lg transition-colors cursor-pointer ${
            stationType === 'buoy' ? 'text-rose-400 bg-white/15' : 'text-slate-400 hover:text-white'
          }`}
          title="Buoys & Webcams"
        >
          <Video className="w-3.5 h-3.5" />
        </button>
        <span className="text-white/15">|</span>
        <button
          id="station-clear-btn"
          onClick={() => onSelectStationType(null)}
          className="p-1 rounded-lg text-slate-400 hover:text-white transition-colors cursor-pointer"
          title="Clear Stations"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* 4. Forecast Model Selector Bar: ECMWF 9km | GFS 22km | ICON 13km | 1 more... */}
      <div className="flex items-center bg-[#181d26]/90 backdrop-blur-md rounded-xl border border-white/10 shadow-xl overflow-hidden p-0.5 text-xs">
        {models.map((m) => {
          const isActive = selectedModel === m.id;
          return (
            <button
              key={m.id}
              id={`model-tab-${m.id}`}
              onClick={() => onSelectModel(m.id)}
              className={`px-3 py-1 rounded-lg font-bold text-[11px] transition-all cursor-pointer flex items-center gap-1 ${
                isActive
                  ? 'bg-amber-500 text-slate-950 shadow-md font-extrabold'
                  : 'text-slate-300 hover:bg-white/10 hover:text-white'
              }`}
            >
              <span>{m.name}</span>
              <span className={`text-[9.5px] font-normal ${isActive ? 'text-slate-900' : 'text-slate-400'}`}>{m.res}</span>
            </button>
          );
        })}

        {/* More models dropdown */}
        <div className="relative">
          <button
            id="more-models-btn"
            onClick={() => setIsMoreModelsOpen(!isMoreModelsOpen)}
            className="px-2 py-1 text-[11px] text-slate-400 hover:text-white hover:bg-white/10 rounded-lg flex items-center gap-0.5 cursor-pointer"
          >
            <span>1 more...</span>
            <ChevronDown className="w-3 h-3" />
          </button>

          {isMoreModelsOpen && (
            <div className="absolute bottom-full right-0 mb-2 w-40 bg-[#181d26]/95 backdrop-blur-xl border border-white/15 rounded-xl shadow-2xl p-1 flex flex-col gap-1 z-[1100]">
              <button
                id="model-meteoblue-btn"
                onClick={() => {
                  onSelectModel('meteoblue');
                  setIsMoreModelsOpen(false);
                }}
                className={`w-full text-left px-2.5 py-1.5 text-xs rounded-lg flex items-center justify-between cursor-pointer ${
                  selectedModel === 'meteoblue' ? 'bg-amber-500 text-slate-950 font-bold' : 'text-slate-300 hover:bg-white/10'
                }`}
              >
                <span>Meteoblue</span>
                <span className="text-[10px] text-slate-400">4km</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 5. Dynamic Layer Color Scale Legend in Bottom Right */}
      {activeLayer === 'none' ? null : activeLayer === 'wind' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <button
            id="legend-unit-toggle-btn"
            onClick={onToggleWindUnit}
            className="font-bold text-sky-400 hover:text-white uppercase cursor-pointer"
            title="Click to toggle wind speed unit"
          >
            {windUnit === 'kt' ? 'kt' : 'km/h'}
          </button>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-blue-700 via-teal-400 via-amber-400 to-rose-600" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>0</span>
            <span>10</span>
            <span>20</span>
            <span>40</span>
            <span>60+</span>
          </div>
        </div>
      ) : activeLayer === 'temperature' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <button
            id="legend-temp-unit-toggle-btn"
            onClick={onToggleTempUnit}
            className="font-bold text-amber-400 hover:text-white uppercase cursor-pointer"
            title="Click to toggle temperature unit"
          >
            °{tempUnit.toUpperCase()}
          </button>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-indigo-800 via-cyan-400 via-emerald-400 via-amber-400 to-rose-600" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>{tempUnit === 'c' ? '-20°' : '-4°'}</span>
            <span>{tempUnit === 'c' ? '0°' : '32°'}</span>
            <span>{tempUnit === 'c' ? '20°' : '68°'}</span>
            <span>{tempUnit === 'c' ? '35°' : '95°'}</span>
            <span>{tempUnit === 'c' ? '45°+' : '113°+'}</span>
          </div>
        </div>
      ) : activeLayer === 'rain' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <span className="font-bold text-cyan-400 font-mono">mm/h</span>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-sky-400 via-emerald-400 via-amber-400 to-rose-600" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>0.2</span>
            <span>2</span>
            <span>6</span>
            <span>15</span>
            <span>35+</span>
          </div>
        </div>
      ) : activeLayer === 'pressure' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <span className="font-bold text-indigo-400 font-mono">hPa</span>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-rose-500 via-amber-400 via-teal-400 to-blue-600" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>980</span>
            <span>1000</span>
            <span>1013</span>
            <span>1028+</span>
          </div>
        </div>
      ) : activeLayer === 'humidity' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <span className="font-bold text-teal-400 font-mono">%</span>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-amber-600 via-teal-400 to-blue-500" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>15%</span>
            <span>40%</span>
            <span>70%</span>
            <span>95%</span>
          </div>
        </div>
      ) : activeLayer === 'radar' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <span className="font-bold text-lime-400 font-mono">dBZ</span>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-green-500 via-yellow-400 via-orange-500 to-fuchsia-600" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>15</span>
            <span>30</span>
            <span>45</span>
            <span>60+</span>
          </div>
        </div>
      ) : activeLayer === 'clouds' ? (
        <div 
          id="ather-bottom-legend"
          className="flex items-center gap-2 bg-[#181d26]/85 backdrop-blur-md px-2.5 py-1 rounded-xl border border-white/10 shadow-xl text-[10px] text-slate-300"
        >
          <span className="font-bold text-slate-300 font-mono">%</span>
          <div className="flex items-center gap-1">
            <div className="w-36 sm:w-48 h-2 rounded-full overflow-hidden flex shadow-inner bg-gradient-to-r from-transparent via-slate-400 to-white" />
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span>0%</span>
            <span>25%</span>
            <span>50%</span>
            <span>75%</span>
            <span>100%</span>
          </div>
        </div>
      ) : null}
    </div>
  );
};
