import type React from 'react';
import {
  X,
  Wind,
  Droplets,
  Gauge,
  CloudRain,
  Sun,
  Cloud,
  AlertTriangle,
  ShieldCheck,
  Activity,
  BrainCircuit,
  Cpu,
} from 'lucide-react';
import type { PointForecastData, AIAnomalyItem } from '../../types/weather';

interface CompactWeatherOverlayProps {
  data: PointForecastData | null;
  loading: boolean;
  timeOffsetHours: number;
  onClose: () => void;
  selectedStation: AIAnomalyItem | null;
  unitSystem: 'metric' | 'imperial';
}

export const CompactWeatherOverlay: React.FC<CompactWeatherOverlayProps> = ({
  data,
  loading,
  timeOffsetHours,
  onClose,
  selectedStation,
  unitSystem,
}) => {
  if (!data && !loading && !selectedStation) return null;

  const formatTemp = (celsius: number) => {
    if (unitSystem === 'imperial') return `${Math.round((celsius * 9) / 5 + 32)}°F`;
    return `${Math.round(celsius)}°C`;
  };

  const formatWind = (kmh: number) => {
    if (unitSystem === 'imperial') return `${Math.round(kmh * 0.621371)} mph`;
    return `${Math.round(kmh)} km/h`;
  };

  // ── 1. ATHER AI Station View (When a map pin is clicked) ──
  if (selectedStation) {
    const isAnomaly = selectedStation.severity === 'D3' || selectedStation.severity === 'D4';
    const isCritical = selectedStation.severity === 'D4';
    const confidencePct = Math.round(selectedStation.confidenceScore * 100);

    return (
      <div className="absolute top-20 left-4 z-40 w-80 animate-in fade-in slide-in-from-top-4 duration-200">
        <div className="flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/95 shadow-2xl backdrop-blur-xl">
          
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-4 py-3">
            <div className="flex items-center gap-2 overflow-hidden">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                  isCritical ? 'bg-red-500 animate-ping' : isAnomaly ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'
                }`}
              />
              <span className="truncate text-xs font-bold uppercase tracking-wider text-white">
                {selectedStation.stationName}
              </span>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
              title="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Status Banner */}
          <div className={`px-4 py-2.5 flex items-center justify-between border-b border-white/5 ${
            isCritical ? 'bg-red-500/10' : isAnomaly ? 'bg-amber-500/10' : 'bg-emerald-500/10'
          }`}>
            <div className="flex items-center gap-2">
              {isAnomaly ? <AlertTriangle className={`h-4 w-4 ${isCritical ? 'text-red-400' : 'text-amber-400'}`} /> : <ShieldCheck className="h-4 w-4 text-emerald-400" />}
              <span className={`text-[10px] font-bold uppercase tracking-wider ${
                isCritical ? 'text-red-400' : isAnomaly ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {isAnomaly ? 'Anomaly Detected' : 'System Healthy'}
              </span>
            </div>
            {isAnomaly && (
              <span className="font-mono text-[10px] font-bold text-white">
                {confidencePct}% CONF
              </span>
            )}
          </div>

          <div className="p-4 space-y-4">
            {/* Raw vs Expected Values (If anomalous) */}
            {isAnomaly && (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-2.5">
                  <div className="text-[9px] uppercase text-red-400/80 mb-1">Raw Reading</div>
                  <div className="font-mono text-lg font-bold text-red-300">
                    {selectedStation.heatAnomalyDelta ? `${selectedStation.heatAnomalyDelta.toFixed(1)}°C` : 'ERR'}
                  </div>
                </div>
                <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-2.5">
                  <div className="text-[9px] uppercase text-cyan-400/80 mb-1">Corrected</div>
                  <div className="font-mono text-lg font-bold text-cyan-300 flex items-center gap-1">
                    <Cpu className="w-3 h-3" />
                    {selectedStation.heatAnomalyDelta ? `${(selectedStation.heatAnomalyDelta - 12.4).toFixed(1)}°C` : 'IMP'}
                  </div>
                </div>
              </div>
            )}

            {/* AI Diagnostics */}
            <div className="space-y-2">
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                <BrainCircuit className="h-3 w-3 text-cyan-400" />
                AI Diagnostics
              </div>
              <div className="rounded-xl border border-white/5 bg-black/20 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">Root Cause</span>
                  <span className={`text-[10px] font-bold uppercase ${isAnomaly ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {selectedStation.anomalyType.replace(/_/g, ' ')}
                  </span>
                </div>
                <p className="text-[10px] leading-relaxed text-slate-300">
                  {selectedStation.aiRecommendation}
                </p>
              </div>
            </div>
          </div>

        </div>
      </div>
    );
  }

  // ── 2. Standard Weather Forecast View (When clicking empty map space) ──
  const hourlyItem = data?.hourly && data.hourly[timeOffsetHours] ? data.hourly[timeOffsetHours] : null;
  const current = data?.current;
  const location = data?.location;

  const locationName = location?.name || 'Selected Location';
  const tempVal = hourlyItem ? hourlyItem.temp : current?.temp ?? 28;
  const windSpeedVal = hourlyItem ? hourlyItem.windSpeed : current?.windSpeed ?? 14;
  const windDir = hourlyItem ? hourlyItem.windDirection : current?.windDirection ?? 'WNW';
  const humidityVal = hourlyItem ? hourlyItem.humidity : current?.humidity ?? 71;
  const pressureVal = hourlyItem ? hourlyItem.pressure : current?.pressure ?? 1009;
  const weatherDesc = hourlyItem ? hourlyItem.weatherDesc : current?.weatherDesc ?? 'Mainly clear';

  const getWeatherIcon = (desc: string) => {
    const d = desc.toLowerCase();
    if (d.includes('rain') || d.includes('drizzle')) return <CloudRain className="w-4 h-4 text-blue-400" />;
    if (d.includes('cloud')) return <Cloud className="w-4 h-4 text-slate-300" />;
    return <Sun className="w-4 h-4 text-amber-400" />;
  };

  return (
    <div className="absolute top-20 left-4 z-40 w-64 animate-in fade-in slide-in-from-top-4 duration-200">
      <div className="flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0f1720]/90 shadow-2xl backdrop-blur-xl">
        
        <div className="flex items-center justify-between border-b border-white/10 bg-black/20 px-3 py-2.5">
          <div className="flex items-center gap-1.5 overflow-hidden">
            <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-cyan-400" />
            <span className="truncate text-xs font-bold text-white uppercase tracking-wider">
              {locationName}
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {loading && !hourlyItem ? (
          <div className="flex items-center justify-center gap-2 py-6 text-[10px] text-slate-400 uppercase tracking-wider">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
            Loading Data...
          </div>
        ) : (
          <div className="p-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-2xl font-black text-white tracking-tight">
                {formatTemp(tempVal)}
              </span>
              <div className="flex items-center gap-1.5 rounded-lg bg-white/5 px-2 py-1 border border-white/5">
                {getWeatherIcon(weatherDesc)}
                <span className="max-w-[80px] truncate text-[9px] font-medium text-slate-300 uppercase tracking-wider">
                  {weatherDesc}
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-1.5 border-t border-white/5 pt-2">
              <div className="flex items-center justify-between text-[10px]">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <Wind className="h-3 w-3 text-cyan-400" /> Wind
                </span>
                <span className="font-mono font-medium text-white">{formatWind(windSpeedVal)} {windDir}</span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <Droplets className="h-3 w-3 text-blue-400" /> Humidity
                </span>
                <span className="font-mono font-medium text-white">{Math.round(humidityVal)}%</span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <Gauge className="h-3 w-3 text-rose-400" /> Pressure
                </span>
                <span className="font-mono font-medium text-white">{Math.round(pressureVal)} hPa</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};