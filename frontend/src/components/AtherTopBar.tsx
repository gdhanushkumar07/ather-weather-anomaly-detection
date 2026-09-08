import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  MapPin, 
  Navigation, 
  X, 
  ShieldAlert, 
  Activity, 
  HeartPulse, 
  Radio, 
  Play, 
  Pause, 
  ChevronDown, 
  Cpu, 
  Zap, 
  Flame, 
  Snowflake, 
  TrendingDown, 
  AlertCircle, 
  ShieldCheck, 
  Info, 
  Menu
} from 'lucide-react';
import { LocationCoords, AtherMapMode, AtherDemoScenario, AwsStation, GlobalWeatherStation } from '../types';
import { searchCities } from '../utils/weatherApi';
import { searchStations } from '../services/stationService';

interface AtherTopBarProps {
  onSelectLocation: (coords: LocationCoords) => void;
  onLocateMe: () => void;
  selectedLocationName: string;
  mapMode: AtherMapMode;
  onSelectMapMode: (mode: AtherMapMode) => void;
  isStreaming: boolean;
  onToggleStreaming: () => void;
  currentScenario: AtherDemoScenario;
  onSelectScenario: (sc: AtherDemoScenario) => void;
  criticalStation: AwsStation | null;
  onInvestigateStation: (st: AwsStation) => void;
  onOpenArchitectureModal: () => void;
  onOpenMenu: () => void;
  globalStations?: GlobalWeatherStation[];
  onSelectGlobalStation?: (station: GlobalWeatherStation) => void;
  onFlyToGlobalStation?: (station: GlobalWeatherStation) => void;
}

export const AtherTopBar: React.FC<AtherTopBarProps> = ({
  onSelectLocation,
  onLocateMe,
  selectedLocationName,
  mapMode,
  onSelectMapMode,
  isStreaming,
  onToggleStreaming,
  currentScenario,
  onSelectScenario,
  criticalStation,
  onInvestigateStation,
  onOpenArchitectureModal,
  onOpenMenu,
  globalStations = [],
  onSelectGlobalStation,
  onFlyToGlobalStation,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<LocationCoords[]>([]);
  const [stationResults, setStationResults] = useState<GlobalWeatherStation[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isScenarioDropdownOpen, setIsScenarioDropdownOpen] = useState(false);
  const [isAlertDismissed, setIsAlertDismissed] = useState(false);

  const searchContainerRef = useRef<HTMLDivElement>(null);
  const scenarioContainerRef = useRef<HTMLDivElement>(null);

  const scenarios: {
    id: AtherDemoScenario;
    label: string;
    icon: React.ReactNode;
    tag: string;
    desc: string;
  }[] = [
    {
      id: 'hyd_spike',
      label: 'Sensor Spike (Hyd)',
      icon: <Zap size={13} className="text-rose-400" />,
      tag: 'Fault',
      desc: 'Isolated 55°C sensor jump vs 29°C neighbors',
    },
    {
      id: 'genuine_heatwave',
      label: 'Genuine Heatwave',
      icon: <Flame size={13} className="text-amber-400" />,
      tag: 'Consensus',
      desc: 'Spatially consistent heat across Telangana & Rajasthan',
    },
    {
      id: 'frozen_sensor',
      label: 'Frozen Sensor (DEL)',
      icon: <Snowflake size={13} className="text-cyan-400" />,
      tag: 'Flatline',
      desc: 'Zero temporal variance over 8 hours',
    },
    {
      id: 'sensor_drift',
      label: 'Calibration Drift (BOM)',
      icon: <TrendingDown size={13} className="text-purple-400" />,
      tag: 'Creep',
      desc: 'Gradual linear calibration decay (+0.22°C/hr)',
    },
    {
      id: 'unphysical_combo',
      label: 'Unphysical State (CCU)',
      icon: <AlertCircle size={13} className="text-yellow-400" />,
      tag: 'Physics',
      desc: 'Thermodynamic mismatch (42°C at 98% RH)',
    },
    {
      id: 'normal',
      label: 'Nominal Network',
      icon: <ShieldCheck size={13} className="text-emerald-400" />,
      tag: 'Healthy',
      desc: 'All 24 Indian AWS stations within normal limits',
    },
  ];

  const currentScenarioObj = scenarios.find((s) => s.id === currentScenario) || scenarios[0];

  // Re-open alert whenever current scenario changes
  useEffect(() => {
    setIsAlertDismissed(false);
  }, [currentScenario]);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setStationResults([]);
      setIsLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      // 1. Search indexed NOAA ISD stations
      if (globalStations && globalStations.length > 0) {
        const matched = searchStations(trimmed, globalStations, 10);
        setStationResults(matched);
      } else {
        setStationResults([]);
      }

      // 2. Search cities via geocoding API
      try {
        const res = await searchCities(trimmed);
        setResults(res);
      } catch (e) {
        console.warn('City geocoding search failed:', e);
      } finally {
        setIsLoading(false);
      }
    }, 280);

    return () => clearTimeout(timer);
  }, [query, globalStations]);

  // Click outside listener
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setIsSearchOpen(false);
      }
      if (scenarioContainerRef.current && !scenarioContainerRef.current.contains(e.target as Node)) {
        setIsScenarioDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelectCity = (city: LocationCoords) => {
    onSelectLocation(city);
    setQuery(city.name || '');
    setIsSearchOpen(false);
  };

  const handleSelectStation = (station: GlobalWeatherStation) => {
    if (onSelectGlobalStation) {
      onSelectGlobalStation(station);
    }
    if (onFlyToGlobalStation) {
      onFlyToGlobalStation(station);
    }
    setQuery(station.name || station.id);
    setIsSearchOpen(false);
  };

  const hasAnyResults = stationResults.length > 0 || results.length > 0;

  return (
    <header className="fixed top-3 left-0 right-0 z-[1000] px-3 pointer-events-none flex flex-col items-center gap-2">
      {/* 1. Main Navigation Bar */}
      <div className="w-full max-w-7xl flex items-center justify-between pointer-events-auto">
        {/* Left Section: Brand & Search */}
        <div className="flex items-center gap-2.5">
          {/* ATHER Logo */}
          <div
            id="ather-brand-pill"
            className="flex items-center gap-2 bg-[#141822]/90 hover:bg-[#1b212e] backdrop-blur-md border border-white/10 text-white px-3.5 py-1.5 rounded-full shadow-xl select-none transition-colors"
          >
            <div className="w-5 h-5 rounded-full bg-gradient-to-tr from-cyan-400 via-sky-500 to-indigo-500 flex items-center justify-center text-[10px] shadow-sm font-black text-white">
              ⚡
            </div>
            <span className="font-extrabold tracking-wider text-sm text-slate-100 flex items-center gap-1.5">
              <span>ATHER</span>
              <span className="text-[9px] font-mono font-bold tracking-widest text-sky-400 bg-sky-500/10 px-1.5 py-0.5 rounded border border-sky-400/30">
                GLOBAL
              </span>
            </span>
          </div>

          {/* Search Pill */}
          <div ref={searchContainerRef} className="relative w-48 sm:w-64">
            <div className="flex items-center bg-[#141822]/90 hover:bg-[#1b212e] backdrop-blur-md text-white px-3 py-1.5 rounded-full border border-white/10 shadow-xl transition-all">
              <Search className="w-3.5 h-3.5 text-slate-400 mr-2 shrink-0" />
              <input
                id="search-station-city-input"
                type="text"
                className="bg-transparent border-none outline-none text-[12.5px] w-full placeholder:text-slate-400 text-slate-100 font-medium"
                placeholder={selectedLocationName || 'Search station, city, ID, lat/lon...'}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setIsSearchOpen(true);
                }}
                onFocus={() => setIsSearchOpen(true)}
              />
              {query && (
                <button
                  onClick={() => {
                    setQuery('');
                    setResults([]);
                    setStationResults([]);
                  }}
                  className="text-slate-400 hover:text-white p-0.5 rounded cursor-pointer mr-1"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
              <button
                onClick={onLocateMe}
                title="Locate me"
                className="text-slate-400 hover:text-sky-400 p-0.5 transition-colors cursor-pointer shrink-0"
              >
                <Navigation className="w-3 h-3" />
              </button>
            </div>

            {/* Dropdown Results */}
            {isSearchOpen && query.trim().length >= 2 && (
              <div className="absolute top-full left-0 mt-2 w-72 sm:w-80 bg-[#141822]/98 backdrop-blur-xl border border-white/15 rounded-2xl shadow-2xl overflow-hidden z-[1050] max-h-[380px] overflow-y-auto divide-y divide-white/5">
                {isLoading && (
                  <div className="p-3 text-xs text-slate-400 flex items-center justify-center gap-2">
                    <div className="w-3 h-3 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
                    Searching meteorological registry...
                  </div>
                )}

                {/* 1. NOAA ISD Stations Group */}
                {stationResults.length > 0 && (
                  <div>
                    <div className="px-3 py-1.5 bg-[#181e2b]/90 text-[10px] font-mono font-bold tracking-wider text-sky-400 uppercase flex items-center gap-1.5">
                      <Radio size={11} />
                      <span>NOAA Weather Stations ({stationResults.length})</span>
                    </div>
                    {stationResults.map((st) => (
                      <button
                        key={`station-${st.id}`}
                        onClick={() => handleSelectStation(st)}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-white/10 flex flex-col gap-0.5 transition-colors border-b border-white/5 cursor-pointer group"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-100 group-hover:text-sky-300 truncate max-w-[180px]">
                            {st.name}
                          </span>
                          <span className="text-[9.5px] font-mono text-sky-400 bg-sky-950/80 px-1 py-0.2 rounded border border-sky-400/30">
                            {st.id}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono">
                          <span>{st.country || 'Global'}{st.state ? `, ${st.state}` : ''} {st.icao ? `(${st.icao})` : ''}</span>
                          <span>{st.lat.toFixed(2)}°, {st.lon.toFixed(2)}°</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {/* 2. Cities & Geocoded Locations Group */}
                {results.length > 0 && (
                  <div>
                    <div className="px-3 py-1.5 bg-[#181e2b]/90 text-[10px] font-mono font-bold tracking-wider text-slate-400 uppercase flex items-center gap-1.5">
                      <MapPin size={11} />
                      <span>Cities & Regions ({results.length})</span>
                    </div>
                    {results.map((loc, idx) => (
                      <button
                        key={`city-${idx}`}
                        onClick={() => handleSelectCity(loc)}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-white/10 flex items-center justify-between transition-colors border-b border-white/5 cursor-pointer group"
                      >
                        <span className="font-medium text-slate-200 group-hover:text-white">{loc.name}, {loc.country}</span>
                        <span className="text-[10px] text-slate-400 font-mono">{loc.lat.toFixed(1)}°, {loc.lon.toFixed(1)}°</span>
                      </button>
                    ))}
                  </div>
                )}

                {/* No results fallback */}
                {!isLoading && !hasAnyResults && (
                  <div className="p-4 text-xs text-slate-400 text-center font-mono">
                    No stations or locations matching &ldquo;{query}&rdquo;
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Center Section: Core ATHER Modes (Requirement 10) */}
        <div className="hidden md:flex items-center gap-1 bg-[#141822]/90 backdrop-blur-md p-1 rounded-full border border-white/10 shadow-xl select-none">
          <button
            id="nav-mode-network"
            onClick={() => onSelectMapMode('monitoring')}
            className={`px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              mapMode === 'monitoring'
                ? 'bg-sky-600 text-white shadow-md'
                : 'text-slate-300 hover:text-white hover:bg-white/5'
            }`}
          >
            <Activity size={13} />
            <span>Network</span>
          </button>

          <button
            id="nav-mode-anomalies"
            onClick={() => onSelectMapMode('anomalies')}
            className={`px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              mapMode === 'anomalies'
                ? 'bg-rose-600 text-white shadow-md'
                : 'text-slate-300 hover:text-white hover:bg-white/5'
            }`}
          >
            <ShieldAlert size={13} />
            <span>Anomalies</span>
          </button>

          <button
            id="nav-mode-health"
            onClick={() => onSelectMapMode('health')}
            className={`px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
              mapMode === 'health'
                ? 'bg-emerald-600 text-white shadow-md'
                : 'text-slate-300 hover:text-white hover:bg-white/5'
            }`}
          >
            <HeartPulse size={13} />
            <span>Sensor Health</span>
          </button>
        </div>

        {/* Right Section: Live Telemetry & Demo Scenarios & Menu */}
        <div className="flex items-center gap-2">
          {/* Live Telemetry Streaming Pill */}
          <button
            id="live-telemetry-toggle-btn"
            onClick={onToggleStreaming}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-mono font-semibold backdrop-blur-md shadow-xl transition-all cursor-pointer ${
              isStreaming
                ? 'bg-emerald-950/80 border-emerald-500/50 text-emerald-300 hover:bg-emerald-900/80'
                : 'bg-slate-900/80 border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
            title={isStreaming ? 'Streaming live AWS telemetry (Click to pause)' : 'Paused (Click to resume)'}
          >
            <span className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-emerald-400 animate-ping' : 'bg-slate-500'}`} />
            <span>{isStreaming ? 'LIVE' : 'PAUSED'}</span>
          </button>

          {/* Compact Demo Scenario Dropdown */}
          <div ref={scenarioContainerRef} className="relative">
            <button
              id="demo-scenario-dropdown-btn"
              onClick={() => setIsScenarioDropdownOpen(!isScenarioDropdownOpen)}
              className="flex items-center gap-1.5 bg-[#141822]/90 hover:bg-[#1c2230] border border-white/10 px-3 py-1.5 rounded-full text-xs font-semibold text-slate-200 shadow-xl transition-colors cursor-pointer"
            >
              {currentScenarioObj.icon}
              <span className="max-w-[110px] sm:max-w-[140px] truncate">{currentScenarioObj.label}</span>
              <ChevronDown size={13} className="text-slate-400" />
            </button>

            {isScenarioDropdownOpen && (
              <div className="absolute right-0 top-full mt-2 w-72 bg-[#161b25]/95 backdrop-blur-xl border border-white/15 rounded-2xl shadow-2xl p-1.5 z-[1050] space-y-1">
                <div className="px-2.5 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Select SIH Demonstration Scenario
                </div>
                {scenarios.map((sc) => {
                  const isSelected = sc.id === currentScenario;
                  return (
                    <button
                      key={sc.id}
                      onClick={() => {
                        onSelectScenario(sc.id);
                        setIsScenarioDropdownOpen(false);
                      }}
                      className={`w-full text-left p-2 rounded-xl transition-colors flex items-start gap-2.5 cursor-pointer ${
                        isSelected ? 'bg-sky-600/30 border border-sky-400/40 text-white' : 'hover:bg-white/5 text-slate-300'
                      }`}
                    >
                      <div className="mt-0.5">{sc.icon}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-xs text-slate-100">{sc.label}</span>
                          <span className="text-[9.5px] font-mono px-1 rounded bg-black/40 text-slate-400">{sc.tag}</span>
                        </div>
                        <p className="text-[10px] text-slate-400 leading-tight mt-0.5">{sc.desc}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Architecture Modal Button */}
          <button
            id="architecture-info-btn"
            onClick={onOpenArchitectureModal}
            className="p-1.5 rounded-full bg-[#141822]/90 hover:bg-[#1c2230] border border-white/10 text-slate-300 hover:text-white shadow-xl transition-colors cursor-pointer"
            title="View ATHER 5-Layer AI Architecture"
          >
            <Cpu size={15} />
          </button>

          {/* Menu Button */}
          <button
            id="top-menu-btn"
            onClick={onOpenMenu}
            className="p-1.5 rounded-full bg-[#141822]/90 hover:bg-[#1c2230] border border-white/10 text-slate-300 hover:text-white shadow-xl transition-colors cursor-pointer"
            title="Settings and layers menu"
          >
            <Menu size={15} />
          </button>
        </div>
      </div>

      {/* 2. Map-First Anomaly Alert Banner (Requirement 14) */}
      {criticalStation && !isAlertDismissed && (
        <div
          id="map-first-anomaly-alert"
          className="pointer-events-auto flex items-center gap-3 bg-rose-950/90 hover:bg-rose-900/90 border border-rose-500/50 backdrop-blur-md text-white px-3.5 py-1.5 rounded-full shadow-2xl animate-bounce duration-1000 transition-all select-none"
        >
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-400 animate-ping" />
            <span className="font-mono font-black text-rose-300 text-xs">
              {criticalStation.id}
            </span>
            <span className="text-slate-300 text-xs font-medium">
              Critical Anomaly Detected ({criticalStation.currentObs.temperature.toFixed(1)}°C)
            </span>
          </div>

          <button
            id="investigate-anomaly-btn"
            onClick={() => onInvestigateStation(criticalStation)}
            className="px-2.5 py-0.5 rounded-full bg-rose-600 hover:bg-rose-500 text-white font-bold text-[11px] shadow transition-colors cursor-pointer"
          >
            Investigate on Map →
          </button>

          <button
            onClick={() => setIsAlertDismissed(true)}
            className="text-rose-400 hover:text-white p-0.5 rounded cursor-pointer"
            title="Dismiss alert"
          >
            <X size={13} />
          </button>
        </div>
      )}
    </header>
  );
};
