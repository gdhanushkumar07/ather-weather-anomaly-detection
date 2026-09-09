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
  Shield,
  Activity,
  Thermometer,
} from 'lucide-react';
import type { PointForecastData, AIAnomalyItem } from '../../types/weather';

interface CompactWeatherOverlayProps {
  data: PointForecastData | null;
  loading: boolean;
  timeOffsetHours: number;
  onClose: () => void;
  selectedStation: (AIAnomalyItem & { atherData?: any }) | null;
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

  const atherData = selectedStation?.atherData;

  // ── ATHER Station View ──
  if (atherData && atherData.weather && atherData.anomaly) {
    const { weather, anomaly } = atherData;
    const isAnomaly = anomaly.is_anomaly;
    const severityPct = Math.round(anomaly.severity_score * 100);
    const healthPct = Math.round(anomaly.sensor_health_index);

    // Dominant detection layer
    const layerScores = anomaly.layer_scores || {};
    const dominantLayer = Object.entries(layerScores).sort(
      ([, a]: any, [, b]: any) => b - a
    )[0];

    return (
      <div className="absolute top-14 left-3 z-30 w-72 animate-in fade-in slide-in-from-top-1 duration-150">
        <div className="windy-glass rounded-xl p-3 shadow-2xl border border-white/10 flex flex-col gap-2">
          {/* Header */}
          <div className="flex items-center justify-between pb-1 border-b border-white/10">
            <div className="flex items-center gap-1.5 overflow-hidden">
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  isAnomaly ? 'bg-red-400 animate-pulse' : 'bg-emerald-400'
                }`}
              />
              <span className="font-bold text-sm text-white truncate">
                {atherData.name || selectedStation?.stationName || 'Station'}
              </span>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
              title="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Weather Values */}
          <div className="flex items-center justify-between">
            <span className="text-2xl font-black text-white tracking-tight">
              {weather.temperature_c.toFixed(1)}°C
            </span>
            <div
              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-md font-semibold ${
                isAnomaly
                  ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                  : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
              }`}
            >
              {isAnomaly ? (
                <AlertTriangle className="w-3 h-3" />
              ) : (
                <Shield className="w-3 h-3" />
              )}
              <span>{isAnomaly ? 'ANOMALY' : 'NORMAL'}</span>
            </div>
          </div>

          {/* Weather Metrics */}
          <div className="flex flex-col gap-1 text-xs text-slate-300 pt-1 border-t border-white/5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1 text-slate-400">
                <Thermometer className="w-3 h-3 text-orange-400" /> Temperature
              </span>
              <span className="font-medium text-white">
                {weather.temperature_c.toFixed(1)}°C
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1 text-slate-400">
                <Gauge className="w-3 h-3 text-rose-400" /> Pressure
              </span>
              <span className="font-medium text-white">
                {weather.pressure_hpa.toFixed(1)} hPa
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1 text-slate-400">
                <Droplets className="w-3 h-3 text-blue-400" /> Humidity
              </span>
              <span className="font-medium text-white">
                {weather.humidity_pct.toFixed(1)}%
              </span>
            </div>
          </div>

          {/* ATHER Anomaly Details */}
          <div className="flex flex-col gap-1.5 text-xs pt-1.5 border-t border-white/10">
            <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1">
              <Activity className="w-3 h-3 text-cyan-400" />
              ATHER Detection
            </div>

            {/* Severity Bar */}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Severity</span>
              <div className="flex items-center gap-1.5">
                <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      severityPct > 70
                        ? 'bg-red-500'
                        : severityPct > 40
                        ? 'bg-orange-500'
                        : severityPct > 10
                        ? 'bg-yellow-500'
                        : 'bg-emerald-500'
                    }`}
                    style={{ width: `${severityPct}%` }}
                  />
                </div>
                <span className="font-mono text-white w-8 text-right">
                  {severityPct}%
                </span>
              </div>
            </div>

            {/* Health Bar */}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Sensor Health</span>
              <div className="flex items-center gap-1.5">
                <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      healthPct > 70
                        ? 'bg-emerald-500'
                        : healthPct > 40
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                    }`}
                    style={{ width: `${healthPct}%` }}
                  />
                </div>
                <span className="font-mono text-white w-8 text-right">
                  {healthPct}%
                </span>
              </div>
            </div>

            {/* Root Cause */}
            {isAnomaly && (
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Root Cause</span>
                <span className="font-medium text-amber-300 text-[11px]">
                  {anomaly.root_cause.replace(/_/g, ' ')}
                </span>
              </div>
            )}

            {/* Detection Layer */}
            {dominantLayer && (
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Primary Layer</span>
                <span className="font-medium text-cyan-300 capitalize text-[11px]">
                  {dominantLayer[0]} ({(Number(dominantLayer[1]) * 100).toFixed(0)}%)
                </span>
              </div>
            )}

            {/* Explanation (truncated) */}
            {anomaly.explanation && (
              <div className="mt-1 text-[10px] text-slate-400 leading-snug line-clamp-3 bg-white/5 rounded-md p-1.5">
                {anomaly.explanation}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Standard Weather Forecast View (existing behavior) ──
  const hourlyItem = data?.hourly && data.hourly[timeOffsetHours] ? data.hourly[timeOffsetHours] : null;
  const current = data?.current;
  const location = data?.location;

  const locationName = location?.name || selectedStation?.stationName || 'Selected Location';
  const tempVal = hourlyItem ? hourlyItem.temp : current?.temp ?? 28;
  const windSpeedVal = hourlyItem ? hourlyItem.windSpeed : current?.windSpeed ?? 14;
  const windDir = hourlyItem ? hourlyItem.windDirection : current?.windDirection ?? 'WNW';
  const humidityVal = hourlyItem ? hourlyItem.humidity : current?.humidity ?? 71;
  const pressureVal = hourlyItem ? hourlyItem.pressure : current?.pressure ?? 1009;
  const weatherDesc = hourlyItem ? hourlyItem.weatherDesc : current?.weatherDesc ?? 'Mainly clear';

  const formatTemp = (celsius: number) => {
    if (unitSystem === 'imperial') return `${Math.round((celsius * 9) / 5 + 32)}°F`;
    return `${Math.round(celsius)}°C`;
  };

  const formatWind = (kmh: number) => {
    if (unitSystem === 'imperial') return `${Math.round(kmh * 0.621371)} mph`;
    return `${Math.round(kmh)} km/h`;
  };

  const getWeatherIcon = (desc: string) => {
    const d = desc.toLowerCase();
    if (d.includes('rain') || d.includes('drizzle')) return <CloudRain className="w-4 h-4 text-blue-400" />;
    if (d.includes('cloud')) return <Cloud className="w-4 h-4 text-slate-300" />;
    return <Sun className="w-4 h-4 text-amber-400" />;
  };

  return (
    <div className="absolute top-14 left-3 z-30 w-64 animate-in fade-in slide-in-from-top-1 duration-150">
      <div className="windy-glass rounded-xl p-3 shadow-2xl border border-white/10 flex flex-col gap-2">
        {/* Header with Location & Dismiss */}
        <div className="flex items-center justify-between pb-1 border-b border-white/10">
          <div className="flex items-center gap-1.5 overflow-hidden">
            <span className="w-2 h-2 rounded-full bg-cyan-400 shrink-0 animate-pulse" />
            <span className="font-bold text-sm text-white truncate">
              {locationName}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
            title="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Loading Spinner State */}
        {loading && !hourlyItem && (
          <div className="py-4 flex items-center justify-center gap-2 text-xs text-slate-400">
            <div className="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
            <span>Loading...</span>
          </div>
        )}

        {/* Weather Metrics Card */}
        {(!loading || hourlyItem) && (
          <>
            {/* Temperature & Condition */}
            <div className="flex items-center justify-between">
              <span className="text-2xl font-black text-white tracking-tight">
                {formatTemp(tempVal)}
              </span>
              <div className="flex items-center gap-1 text-xs text-slate-300 bg-white/5 px-2 py-0.5 rounded-md">
                {getWeatherIcon(weatherDesc)}
                <span className="capitalize text-[11px] truncate max-w-[100px]">{weatherDesc}</span>
              </div>
            </div>

            {/* Metrics List */}
            <div className="flex flex-col gap-1 text-xs text-slate-300 pt-1 border-t border-white/5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 text-slate-400">
                  <Wind className="w-3 h-3 text-cyan-400" /> Wind
                </span>
                <span className="font-medium text-white">{formatWind(windSpeedVal)} {windDir}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 text-slate-400">
                  <Droplets className="w-3 h-3 text-blue-400" /> Humidity
                </span>
                <span className="font-medium text-white">{Math.round(humidityVal)}%</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1 text-slate-400">
                  <Gauge className="w-3 h-3 text-rose-400" /> Pressure
                </span>
                <span className="font-medium text-white">{Math.round(pressureVal)} hPa</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

