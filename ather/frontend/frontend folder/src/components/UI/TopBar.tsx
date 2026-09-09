import { useState, useEffect, useRef } from 'react';
import type React from 'react';
import { Search, X, MapPin, Camera, AlertTriangle, CloudSun, Menu, Sliders } from 'lucide-react';
import { searchLocations, type GeocodeResult } from '../../utils/api';
import type { LocationCoords } from '../../types/weather';

interface TopBarProps {
  onSelectLocation: (loc: LocationCoords) => void;
  showWebcams: boolean;
  onToggleWebcams: () => void;
  onSelectAnomalies: () => void;
  isAnomalyActive: boolean;
  unitSystem: 'metric' | 'imperial';
  onToggleUnitSystem: () => void;
  particleDensity: number;
  onDensityChange: (val: number) => void;
  speedMultiplier: number;
  onSpeedChange: (val: number) => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  onSelectLocation,
  showWebcams,
  onToggleWebcams,
  onSelectAnomalies,
  isAnomalyActive,
  unitSystem,
  onToggleUnitSystem,
  particleDensity,
  onDensityChange,
  speedMultiplier,
  onSpeedChange,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showMenuDropdown, setShowMenuDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const quickCities = [
    { name: 'Mumbai', lat: 19.076, lon: 72.8777, country: 'India' },
    { name: 'Delhi', lat: 28.6139, lon: 77.209, country: 'India' },
    { name: 'Bengaluru', lat: 12.9716, lon: 77.5946, country: 'India' },
    { name: 'Hyderabad', lat: 17.385, lon: 78.4867, country: 'India' },
  ];

  // Debounced search
  useEffect(() => {
    if (!query || query.trim().length < 2) {
      setResults([]);
      setShowDropdown(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      const res = await searchLocations(query);
      setResults(res);
      setIsSearching(false);
      setShowDropdown(true);
    }, 350);

    return () => clearTimeout(timer);
  }, [query]);

  // Click outside listener
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenuDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handlePickCity = (loc: LocationCoords) => {
    onSelectLocation(loc);
    setShowDropdown(false);
    setQuery(loc.name || '');
  };

  return (
    <>
      {/* Top-Left Floating Controls: ATHER Logo, Search, Quick Locations */}
      <div className="absolute top-3 left-3 z-30 flex items-center gap-2 max-w-[calc(100vw-260px)]">
        {/* ATHER Logo Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gradient-to-r from-cyan-600 via-blue-600 to-indigo-600 shadow-xl border border-white/20 select-none shrink-0 cursor-pointer hover:opacity-95 transition-opacity">
          <CloudSun className="w-4 h-4 text-white animate-pulse" />
          <span className="font-extrabold tracking-wider text-xs sm:text-sm text-white drop-shadow">
            ATHER
          </span>
        </div>

        {/* Floating Search Bar */}
        <div className="relative shrink-0" ref={dropdownRef}>
          <div className="flex items-center windy-glass rounded-full px-3 py-1.5 w-44 sm:w-56 md:w-64 shadow-2xl focus-within:border-cyan-400/70 transition-all border border-white/10">
            {isSearching ? (
              <div className="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin shrink-0 mr-2" />
            ) : (
              <Search className="w-3.5 h-3.5 text-slate-400 shrink-0 mr-2" />
            )}
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => results.length > 0 && setShowDropdown(true)}
              placeholder="Search location or coordinates..."
              className="bg-transparent border-none outline-none text-xs text-white placeholder-slate-400 w-full"
            />
            {query && (
              <button
                onClick={() => {
                  setQuery('');
                  setResults([]);
                }}
                className="text-slate-400 hover:text-white ml-1 p-0.5"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Autocomplete Dropdown */}
          {showDropdown && results.length > 0 && (
            <div className="absolute top-10 left-0 w-72 windy-glass rounded-2xl p-1.5 shadow-2xl z-40 flex flex-col gap-1 max-h-72 overflow-y-auto border border-white/10">
              {results.map((item, idx) => (
                <button
                  key={idx}
                  onClick={() =>
                    handlePickCity({
                      lat: parseFloat(item.lat),
                      lon: parseFloat(item.lon),
                      name: item.name || item.display_name.split(',')[0],
                      country: item.address?.country,
                    })
                  }
                  className="flex items-start gap-2 px-3 py-2 rounded-xl text-left hover:bg-white/10 transition-colors text-xs text-slate-200"
                >
                  <MapPin className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" />
                  <div className="overflow-hidden">
                    <div className="font-medium text-white truncate">
                      {item.name || item.display_name.split(',')[0]}
                    </div>
                    <div className="text-[10px] text-slate-400 truncate">
                      {item.display_name}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Quick Location Pills */}
        <div className="hidden lg:flex items-center gap-1 shrink-0">
          {quickCities.map((city) => (
            <button
              key={city.name}
              onClick={() => handlePickCity(city)}
              className="text-[11px] font-medium px-2.5 py-1 rounded-full windy-glass text-slate-300 hover:text-cyan-300 hover:bg-white/15 transition-all border border-white/10 active:scale-95"
            >
              {city.name}
            </button>
          ))}
        </div>
      </div>

      {/* Top-Right Floating Controls: AI Anomalies, Webcams, Units, Menu */}
      <div className="absolute top-3 right-3 z-30 flex items-center gap-1.5 sm:gap-2">
        {/* ATHER Anomaly Layer Button */}
        <button
          onClick={onSelectAnomalies}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all shadow-xl border ${
            isAnomalyActive
              ? 'bg-amber-500/30 text-amber-300 border-amber-400/50 shadow-amber-500/20'
              : 'windy-glass text-slate-300 hover:text-amber-300 hover:bg-white/15 border-white/10'
          }`}
          title="ATHER — 5-Layer AWS Anomaly Detection"
        >
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="hidden sm:inline">ATHER Anomalies</span>
        </button>

        {/* Webcams Toggle Button */}
        <button
          onClick={onToggleWebcams}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all shadow-xl border ${
            showWebcams
              ? 'bg-blue-500/30 text-blue-300 border-blue-400/50'
              : 'windy-glass text-slate-300 hover:text-blue-300 hover:bg-white/15 border-white/10'
          }`}
          title="Toggle live coastal and city webcams"
        >
          <Camera className="w-3.5 h-3.5 shrink-0" />
          <span className="hidden sm:inline">Webcams</span>
        </button>

        {/* Unit Toggle Button */}
        <button
          onClick={onToggleUnitSystem}
          className="text-xs font-semibold px-2.5 py-1.5 rounded-full windy-glass text-slate-300 hover:text-cyan-300 hover:bg-white/15 transition-all shadow-xl border border-white/10 active:scale-95"
          title="Toggle units (°C / °F)"
        >
          {unitSystem === 'metric' ? '°C' : '°F'}
        </button>

        {/* Menu & Particle Settings Button */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowMenuDropdown(!showMenuDropdown)}
            className="w-8 h-8 rounded-full windy-glass flex items-center justify-center text-slate-300 hover:text-white hover:bg-white/15 transition-all shadow-xl border border-white/10 active:scale-95"
            title="Menu & Settings"
          >
            <Menu className="w-4 h-4" />
          </button>

          {showMenuDropdown && (
            <div className="absolute right-0 top-10 w-56 windy-glass rounded-2xl p-3 shadow-2xl z-40 border border-white/10 flex flex-col gap-2.5 animate-in fade-in slide-in-from-top-2">
              <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1.5 pb-1 border-b border-white/10">
                <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                <span>Simulation Parameters</span>
              </div>

              <div>
                <div className="flex justify-between text-xs text-slate-300 mb-1">
                  <span>Particle Density</span>
                  <span className="text-cyan-400 font-mono">{Math.round(particleDensity * 100)}%</span>
                </div>
                <input
                  type="range"
                  min="0.4"
                  max="2.0"
                  step="0.1"
                  value={particleDensity}
                  onChange={(e) => onDensityChange(parseFloat(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs text-slate-300 mb-1">
                  <span>Flow Velocity</span>
                  <span className="text-cyan-400 font-mono">{Math.round(speedMultiplier * 100)}%</span>
                </div>
                <input
                  type="range"
                  min="0.5"
                  max="2.5"
                  step="0.1"
                  value={speedMultiplier}
                  onChange={(e) => onSpeedChange(parseFloat(e.target.value))}
                  className="w-full accent-cyan-400 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
