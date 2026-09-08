import React from 'react';
import { GlobalWeatherStation, StationLiveWeather, TempUnit, PressureUnit, WindSpeedUnit } from '../types';
import { 
  X, 
  MapPin, 
  Wind, 
  Gauge, 
  Droplets, 
  Thermometer, 
  RefreshCw, 
  AlertCircle, 
  Compass, 
  Clock,
  Radio
} from 'lucide-react';
import { formatCoordinates } from '../services/stationService';

interface GlobalStationDrawerProps {
  station: GlobalWeatherStation | null;
  weather: StationLiveWeather | null;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh?: () => void;
  tempUnit: TempUnit;
  pressureUnit: PressureUnit;
  windUnit: WindSpeedUnit;
}

export const GlobalStationDrawer: React.FC<GlobalStationDrawerProps> = ({
  station,
  weather,
  isLoading,
  error,
  onClose,
  onRefresh,
  tempUnit,
  pressureUnit,
  windUnit,
}) => {
  if (!station) return null;

  const { latStr, lonStr } = formatCoordinates(station.lat, station.lon);

  // Unit conversion helpers
  const displayTemp = (c: number) => {
    if (tempUnit === 'f') return `${((c * 9) / 5 + 32).toFixed(1)} °F`;
    return `${c.toFixed(1)} °C`;
  };

  const displayPress = (p: number) => {
    if (pressureUnit === 'inhg') return `${(p * 0.02953).toFixed(2)} inHg`;
    if (pressureUnit === 'mmhg') return `${Math.round(p * 0.75006)} mmHg`;
    return `${p.toFixed(1)} hPa`;
  };

  const displayWind = (kmh: number) => {
    if (windUnit === 'kt') return `${(kmh * 0.539957).toFixed(1)} kt`;
    if (windUnit === 'ms') return `${(kmh / 3.6).toFixed(1)} m/s`;
    if (windUnit === 'mph') return `${(kmh * 0.621371).toFixed(1)} mph`;
    return `${kmh.toFixed(1)} km/h`;
  };

  const formatLastFetched = (iso?: string) => {
    if (!iso) return 'Just now';
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return 'Recent';
    }
  };

  return (
    <div
      id="ather-station-information-panel"
      className="fixed bottom-20 left-4 md:left-6 z-[950] w-[340px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-140px)] overflow-y-auto rounded-2xl bg-[#141822]/95 backdrop-blur-xl border border-white/10 shadow-2xl text-slate-100 text-xs select-none transition-all duration-300 animate-in fade-in slide-in-from-bottom-4"
      style={{
        boxShadow: '0 20px 45px -10px rgba(0, 0, 0, 0.75), 0 0 1px 1px rgba(255, 255, 255, 0.08)',
      }}
    >
      {/* 1. Header: Station Title & Close */}
      <div className="p-3.5 border-b border-white/10 bg-[#181e2b]/90 flex items-start justify-between">
        <div className="min-w-0 pr-2">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
            <span className="text-[9.5px] font-mono font-bold tracking-widest text-sky-400 uppercase">
              NOAA ISD WEATHER STATION
            </span>
          </div>
          <h2 className="font-extrabold text-sm text-white tracking-tight truncate max-w-[240px]" title={station.name}>
            {station.name}
          </h2>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400 font-mono">
            <span className="text-slate-300 font-semibold">{station.country || 'GLOBAL'}</span>
            {station.state && (
              <>
                <span>•</span>
                <span>{station.state}</span>
              </>
            )}
            {station.icao && (
              <>
                <span>•</span>
                <span className="px-1.5 py-0.2 rounded bg-sky-950/80 border border-sky-400/40 text-sky-300 text-[10px] font-bold">
                  {station.icao}
                </span>
              </>
            )}
          </div>
        </div>

        <button
          id="close-station-panel-btn"
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer shrink-0"
          title="Close station panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* 2. Metadata Section: STATION & LOCATION */}
      <div className="p-3.5 border-b border-white/5 bg-[#121620]/60 space-y-3">
        {/* Station Identification */}
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="p-2 rounded-xl bg-[#191f2c]/60 border border-white/5">
            <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400 block mb-0.5">
              Station ID (USAF-WBAN)
            </span>
            <span className="font-mono font-bold text-slate-200">
              {station.id}
            </span>
          </div>

          <div className="p-2 rounded-xl bg-[#191f2c]/60 border border-white/5">
            <span className="text-[9px] font-mono uppercase tracking-wider text-slate-400 block mb-0.5">
              Elevation
            </span>
            <span className="font-mono font-bold text-slate-200">
              {station.elev !== undefined && station.elev !== -999.9 ? `${station.elev} m` : 'Sea level'}
            </span>
          </div>
        </div>

        {/* Geographic Coordinates */}
        <div className="p-2.5 rounded-xl bg-[#191f2c]/60 border border-white/5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[9.5px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1">
              <MapPin size={11} className="text-sky-400" />
              Location Coordinates
            </span>
            <span className="text-[9px] font-mono text-slate-500">WGS84</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center font-mono">
            <div className="bg-[#141822] py-1 rounded border border-white/5 text-slate-200 font-bold">
              {latStr}
            </div>
            <div className="bg-[#141822] py-1 rounded border border-white/5 text-slate-200 font-bold">
              {lonStr}
            </div>
          </div>
        </div>
      </div>

      {/* 3. CURRENT CONDITIONS (Live Open-Meteo) */}
      <div className="p-3.5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
            <Radio size={12} className="text-sky-400" />
            Current Conditions
          </span>

          {onRefresh && !isLoading && (
            <button
              onClick={onRefresh}
              className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 cursor-pointer transition-colors"
              title="Refresh meteorological observation"
            >
              <RefreshCw size={11} />
              <span>Refresh</span>
            </button>
          )}
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="p-4 rounded-xl bg-[#191f2c]/60 border border-white/5 flex flex-col items-center justify-center gap-2 py-6">
            <RefreshCw size={20} className="text-sky-400 animate-spin" />
            <span className="text-[11px] text-slate-300 font-mono">Fetching Open-Meteo telemetry...</span>
            <span className="text-[9.5px] text-slate-500">Querying real-time global atmospheric sensors</span>
          </div>
        )}

        {/* Error State */}
        {!isLoading && error && (
          <div className="p-3 rounded-xl bg-rose-950/30 border border-rose-500/30 text-rose-300 space-y-1.5">
            <div className="flex items-center gap-1.5 font-bold text-xs text-rose-200">
              <AlertCircle size={14} className="text-rose-400 shrink-0" />
              <span>Weather data unavailable</span>
            </div>
            <p className="text-[10.5px] text-rose-300/80 leading-relaxed">
              Could not retrieve live observations for this station. Coordinates and station identifiers remain preserved.
            </p>
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="mt-1 px-2.5 py-1 rounded bg-rose-900/60 hover:bg-rose-800 text-rose-100 text-[10px] font-semibold transition-colors cursor-pointer flex items-center gap-1"
              >
                <RefreshCw size={10} />
                <span>Retry Request</span>
              </button>
            )}
          </div>
        )}

        {/* Telemetry Grid */}
        {!isLoading && !error && weather && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              {/* Temperature */}
              <div className="p-2.5 rounded-xl bg-[#191f2c] border border-white/5 flex flex-col">
                <div className="flex items-center justify-between text-slate-400 mb-1">
                  <span className="text-[9.5px] uppercase font-mono tracking-wider">Temperature</span>
                  <Thermometer size={13} className="text-amber-400" />
                </div>
                <span className="font-mono text-lg font-black text-white">
                  {displayTemp(weather.temperature)}
                </span>
                <span className="text-[9px] text-slate-500 font-mono mt-0.5">2m dry-bulb</span>
              </div>

              {/* Relative Humidity */}
              <div className="p-2.5 rounded-xl bg-[#191f2c] border border-white/5 flex flex-col">
                <div className="flex items-center justify-between text-slate-400 mb-1">
                  <span className="text-[9.5px] uppercase font-mono tracking-wider">Humidity</span>
                  <Droplets size={13} className="text-teal-400" />
                </div>
                <span className="font-mono text-lg font-black text-white">
                  {weather.humidity.toFixed(0)} %
                </span>
                <span className="text-[9px] text-slate-500 font-mono mt-0.5">Relative psychrometric</span>
              </div>

              {/* Wind Speed */}
              <div className="p-2.5 rounded-xl bg-[#191f2c] border border-white/5 flex flex-col">
                <div className="flex items-center justify-between text-slate-400 mb-1">
                  <span className="text-[9.5px] uppercase font-mono tracking-wider">Wind</span>
                  <Wind size={13} className="text-sky-400" />
                </div>
                <span className="font-mono text-lg font-black text-white">
                  {displayWind(weather.windSpeed)}
                </span>
                <span className="text-[9px] text-slate-500 font-mono mt-0.5">10m anemometer</span>
              </div>

              {/* Atmospheric Pressure */}
              <div className="p-2.5 rounded-xl bg-[#191f2c] border border-white/5 flex flex-col">
                <div className="flex items-center justify-between text-slate-400 mb-1">
                  <span className="text-[9.5px] uppercase font-mono tracking-wider">Pressure</span>
                  <Gauge size={13} className="text-indigo-400" />
                </div>
                <span className="font-mono text-lg font-black text-white">
                  {displayPress(weather.pressure)}
                </span>
                <span className="text-[9px] text-slate-500 font-mono mt-0.5">Mean sea level</span>
              </div>
            </div>

            {/* Last Fetched Time Footer */}
            <div className="pt-2 border-t border-white/5 flex items-center justify-between text-[10px] text-slate-400 font-mono">
              <span className="flex items-center gap-1">
                <Clock size={11} className="text-slate-500" />
                <span>Last fetched: {formatLastFetched(weather.fetchedAt)}</span>
              </span>
              <span className="text-[9.5px] text-slate-500">Open-Meteo v1</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
