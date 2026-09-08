import React from 'react';
import { 
  X, 
  Settings, 
  Video, 
  Compass, 
  Layers, 
  Info, 
  ShieldAlert, 
  Flame, 
  Sparkles,
  Map as MapIcon,
  Sliders,
  Check
} from 'lucide-react';
import { TempUnit, WindSpeedUnit, PressureUnit, MapBasemap, WeatherModel } from '../types';

interface MenuDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  tempUnit: TempUnit;
  onToggleTempUnit: () => void;
  windUnit: WindSpeedUnit;
  onToggleWindUnit: () => void;
  pressureUnit: PressureUnit;
  onTogglePressureUnit: () => void;
  basemap: MapBasemap;
  onSelectBasemap: (b: MapBasemap) => void;
  showWebcams: boolean;
  onToggleWebcams: () => void;
  particleDensity: number;
  onChangeParticleDensity: (val: number) => void;
}

export const MenuDrawer: React.FC<MenuDrawerProps> = ({
  isOpen,
  onClose,
  tempUnit,
  onToggleTempUnit,
  windUnit,
  onToggleWindUnit,
  pressureUnit,
  onTogglePressureUnit,
  basemap,
  onSelectBasemap,
  showWebcams,
  onToggleWebcams,
  particleDensity,
  onChangeParticleDensity,
}) => {
  if (!isOpen) return null;

  const basemaps: { id: MapBasemap; label: string }[] = [
    { id: 'dark', label: 'Dark Matter' },
    { id: 'satellite', label: 'Satellite' },
    { id: 'voyager', label: 'Voyager Light' },
    { id: 'osm', label: 'OpenStreetMap' },
  ];

  return (
    <div className="fixed inset-0 z-[1200] flex justify-end bg-black/60 backdrop-blur-sm pointer-events-auto">
      <div className="w-full max-w-sm h-full bg-[#1b2028] border-l border-white/10 shadow-2xl p-4 flex flex-col justify-between overflow-y-auto">
        <div>
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-4">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-[#e5283c] flex items-center justify-center text-white font-bold text-sm shadow">
                🌀
              </div>
              <span className="font-bold text-white tracking-wide">ATHER Settings</span>
            </div>
            <button
              id="close-menu-drawer-btn"
              onClick={onClose}
              className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-white/10 cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Unit Settings */}
          <div className="mb-5">
            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Settings className="w-3.5 h-3.5 text-sky-400" />
              <span>Unit Preferences</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button
                id="drawer-temp-unit-btn"
                onClick={onToggleTempUnit}
                className="flex flex-col items-center justify-center p-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 cursor-pointer text-center"
              >
                <span className="text-[10px] text-slate-400">Temperature</span>
                <span className="font-bold text-amber-400 text-sm">°{tempUnit.toUpperCase()}</span>
              </button>

              <button
                id="drawer-wind-unit-btn"
                onClick={onToggleWindUnit}
                className="flex flex-col items-center justify-center p-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 cursor-pointer text-center"
              >
                <span className="text-[10px] text-slate-400">Wind</span>
                <span className="font-bold text-sky-400 text-sm uppercase">{windUnit}</span>
              </button>

              <button
                id="drawer-pressure-unit-btn"
                onClick={onTogglePressureUnit}
                className="flex flex-col items-center justify-center p-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 cursor-pointer text-center"
              >
                <span className="text-[10px] text-slate-400">Pressure</span>
                <span className="font-bold text-blue-400 text-sm uppercase">{pressureUnit}</span>
              </button>
            </div>
          </div>

          {/* Basemap Styles */}
          <div className="mb-5">
            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <MapIcon className="w-3.5 h-3.5 text-emerald-400" />
              <span>Map Style</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {basemaps.map((b) => (
                <button
                  key={b.id}
                  id={`drawer-basemap-${b.id}`}
                  onClick={() => onSelectBasemap(b.id)}
                  className={`flex items-center justify-between p-2.5 rounded-xl border text-xs font-medium cursor-pointer transition-all ${
                    basemap === b.id
                      ? 'bg-sky-500/20 border-sky-400 text-sky-300'
                      : 'bg-white/5 border-white/10 text-slate-300 hover:bg-white/10'
                  }`}
                >
                  <span>{b.label}</span>
                  {basemap === b.id && <Check className="w-3.5 h-3.5 text-sky-400" />}
                </button>
              ))}
            </div>
          </div>

          {/* Animation & Density */}
          <div className="mb-5">
            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-purple-400" />
              <span>Particle Flow Density ({particleDensity}x)</span>
            </div>
            <input
              id="drawer-particle-slider"
              type="range"
              min="0.5"
              max="2.0"
              step="0.25"
              value={particleDensity}
              onChange={(e) => onChangeParticleDensity(parseFloat(e.target.value))}
              className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-sky-400"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>Performance</span>
              <span>Balanced</span>
              <span>Ultra Density</span>
            </div>
          </div>

          {/* Live Webcams toggle */}
          <div className="mb-5 p-3 rounded-xl bg-white/5 border border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Video className="w-4 h-4 text-sky-400" />
              <div>
                <div className="text-xs font-semibold text-white">Live Webcams</div>
                <div className="text-[10px] text-slate-400">Display global weather station cameras</div>
              </div>
            </div>
            <button
              id="drawer-webcams-toggle"
              onClick={onToggleWebcams}
              className={`px-3 py-1 rounded-full text-xs font-bold cursor-pointer transition-colors ${
                showWebcams ? 'bg-sky-500 text-white' : 'bg-slate-700 text-slate-400'
              }`}
            >
              {showWebcams ? 'ON' : 'OFF'}
            </button>
          </div>

          {/* SIH AI Anomaly Detection */}
          <div className="p-3 rounded-xl bg-gradient-to-br from-red-950/40 to-slate-900 border border-red-500/20">
            <div className="flex items-center gap-2 mb-1">
              <ShieldAlert className="w-4 h-4 text-red-400" />
              <span className="text-xs font-bold text-red-300">SIH AI Anomaly Engine</span>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed">
              Real-time classification of atmospheric anomalies (D0 Abnormally Dry to D5 Exceptional Cyclonic Surge) powered by meteorological vectors and Gemini AI.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-white/10 text-center text-[10px] text-slate-500">
          ATHER Environmental Intelligence Interface • NOAA & Open-Meteo Global Network
        </div>
      </div>
    </div>
  );
};
