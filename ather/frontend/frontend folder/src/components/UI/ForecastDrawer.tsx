import { useState } from 'react';
import type React from 'react';
import {
  X,
  Wind,
  Droplets,
  Gauge,
  Sun,
  CloudRain,
  AlertTriangle,
  Camera,
  Activity,
} from 'lucide-react';
import type { PointForecastData, AIAnomalyItem, WebcamItem } from '../../types/weather';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { ANOMALY_SEVERITY_CONFIG } from '../../utils/colorScales';

interface ForecastDrawerProps {
  data: PointForecastData | null;
  loading: boolean;
  onClose: () => void;
  selectedStation: AIAnomalyItem | null;
  onSelectStation: (station: AIAnomalyItem | null) => void;
  nearbyWebcams: WebcamItem[];
  onOpenWebcam: (webcam: WebcamItem) => void;
  unitSystem: 'metric' | 'imperial';
}

export const ForecastDrawer: React.FC<ForecastDrawerProps> = ({
  data,
  loading,
  onClose,
  selectedStation,
  onSelectStation,
  nearbyWebcams,
  onOpenWebcam,
  unitSystem,
}) => {
  const [activeTab, setActiveTab] = useState<'meteogram' | 'hourly' | 'daily' | 'webcams' | 'anomaly'>('meteogram');

  if (!data && !loading && !selectedStation) return null;

  const current = data?.current;
  const location = data?.location;

  // Temperature unit conversion
  const formatTemp = (val: number) => {
    if (unitSystem === 'imperial') return `${Math.round((val * 9) / 5 + 32)}°F`;
    return `${Math.round(val)}°C`;
  };

  const formatSpeed = (val: number) => {
    if (unitSystem === 'imperial') return `${Math.round(val * 0.621371)} mph`;
    return `${Math.round(val)} km/h`;
  };

  // Prepare Meteogram chart dataset (next 24 hours)
  const chartData = (data?.hourly || []).slice(0, 24).map((h) => ({
    time: h.hourLabel,
    temp: unitSystem === 'imperial' ? Math.round((h.temp * 9) / 5 + 32) : h.temp,
    precip: h.precipitation,
    wind: unitSystem === 'imperial' ? Math.round(h.windSpeed * 0.621371) : h.windSpeed,
    gust: unitSystem === 'imperial' ? Math.round(h.windGust * 0.621371) : h.windGust,
  }));

  return (
    <div className="absolute top-16 right-3 bottom-24 z-40 w-full max-w-md md:max-w-lg flex flex-col pointer-events-auto">
      <div className="windy-glass rounded-3xl p-4 shadow-2xl flex flex-col h-full border border-white/10 overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between pb-3 border-b border-white/10">
          <div>
            {loading ? (
              <div className="h-6 w-36 bg-white/10 rounded animate-pulse" />
            ) : selectedStation ? (
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold px-2 py-0.5 rounded bg-amber-500/30 text-amber-300 border border-amber-500/40">
                    SIH AI ANOMALY
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono">
                    {selectedStation.id}
                  </span>
                </div>
                <h2 className="text-lg font-bold text-white mt-1">
                  {selectedStation.stationName}
                </h2>
                <div className="text-xs text-slate-400">
                  {selectedStation.state}, India ({selectedStation.lat.toFixed(2)}°, {selectedStation.lon.toFixed(2)}°)
                </div>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-bold text-white">
                    {location?.name || 'Selected Point'}
                  </h2>
                  {location?.country && (
                    <span className="text-xs font-medium px-2 py-0.5 rounded bg-white/10 text-slate-300">
                      {location.country}
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-400">
                  {location?.lat.toFixed(2)}°N, {location?.lon.toFixed(2)}°E {location?.elevation ? `• ${location.elevation}m ASL` : ''}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={() => {
              if (selectedStation) onSelectStation(null);
              else onClose();
            }}
            className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 text-slate-300 hover:text-white flex items-center justify-center transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto pt-3 space-y-4 pr-1">
          {loading ? (
            <div className="space-y-3 py-8">
              <div className="flex items-center justify-center gap-3 text-cyan-400 text-sm">
                <div className="w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                <span>Fetching real-time atmospheric telemetry...</span>
              </div>
              <div className="h-24 bg-white/5 rounded-2xl animate-pulse" />
              <div className="h-44 bg-white/5 rounded-2xl animate-pulse" />
            </div>
          ) : selectedStation ? (
            /* AI Anomaly Telemetry Card */
            <div className="space-y-4">
              <div
                className="p-4 rounded-2xl border"
                style={{
                  backgroundColor: ANOMALY_SEVERITY_CONFIG[selectedStation.severity].bg,
                  borderColor: ANOMALY_SEVERITY_CONFIG[selectedStation.severity].border,
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertTriangle
                      className="w-5 h-5"
                      style={{ color: ANOMALY_SEVERITY_CONFIG[selectedStation.severity].color }}
                    />
                    <span className="font-bold text-sm text-white">
                      {selectedStation.severity} — {selectedStation.severityLabel}
                    </span>
                  </div>
                  <span
                    className="px-2 py-0.5 rounded text-xs font-extrabold uppercase"
                    style={{
                      backgroundColor: ANOMALY_SEVERITY_CONFIG[selectedStation.severity].color,
                      color: '#0f172a',
                    }}
                  >
                    {selectedStation.status}
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-white/10 text-center">
                  <div className="bg-black/30 p-2 rounded-xl">
                    <div className="text-[10px] text-slate-400">Confidence</div>
                    <div className="text-sm font-bold text-cyan-300">
                      {selectedStation.confidenceScore}%
                    </div>
                  </div>
                  <div className="bg-black/30 p-2 rounded-xl">
                    <div className="text-[10px] text-slate-400">Soil Moisture</div>
                    <div className="text-sm font-bold text-amber-300">
                      {selectedStation.soilMoistureIndex}%
                    </div>
                  </div>
                  <div className="bg-black/30 p-2 rounded-xl">
                    <div className="text-[10px] text-slate-400">Heat Delta</div>
                    <div className="text-sm font-bold text-rose-400">
                      {selectedStation.heatAnomalyDelta > 0 ? `+${selectedStation.heatAnomalyDelta}` : selectedStation.heatAnomalyDelta}°C
                    </div>
                  </div>
                </div>

                <div className="mt-3 p-3 bg-black/40 rounded-xl border border-white/5">
                  <div className="text-[10px] uppercase font-bold text-cyan-400 mb-1 flex items-center gap-1">
                    <Activity className="w-3 h-3" />
                    AI Prescriptive Recommendation
                  </div>
                  <p className="text-xs text-slate-200 leading-relaxed">
                    {selectedStation.aiRecommendation}
                  </p>
                </div>
              </div>
            </div>
          ) : current ? (
            <>
              {/* Primary Current Weather Row */}
              <div className="flex items-center justify-between p-3 rounded-2xl bg-white/5 border border-white/5">
                <div className="flex items-center gap-3">
                  <div className="text-4xl font-extrabold text-white tracking-tight">
                    {formatTemp(current.temp)}
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-slate-200">
                      {current.weatherDesc}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      Feels like {formatTemp(current.feelsLike)}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-right">
                  <div>
                    <div className="flex items-center gap-1 text-cyan-400 font-bold text-xs justify-end">
                      <Wind className="w-3.5 h-3.5" />
                      <span>{formatSpeed(current.windSpeed)}</span>
                    </div>
                    <div className="text-[10px] text-slate-400">
                      {current.windDirection} • Gusts {formatSpeed(current.windGust)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Atmospheric Metrics Grid */}
              <div className="grid grid-cols-4 gap-2">
                <div className="p-2.5 rounded-xl bg-white/5 border border-white/5 text-center">
                  <Droplets className="w-3.5 h-3.5 text-blue-400 mx-auto mb-1" />
                  <div className="text-[10px] text-slate-400">Humidity</div>
                  <div className="text-xs font-bold text-white">{current.humidity}%</div>
                </div>
                <div className="p-2.5 rounded-xl bg-white/5 border border-white/5 text-center">
                  <Gauge className="w-3.5 h-3.5 text-rose-400 mx-auto mb-1" />
                  <div className="text-[10px] text-slate-400">Pressure</div>
                  <div className="text-xs font-bold text-white">{current.pressure} hPa</div>
                </div>
                <div className="p-2.5 rounded-xl bg-white/5 border border-white/5 text-center">
                  <Sun className="w-3.5 h-3.5 text-amber-400 mx-auto mb-1" />
                  <div className="text-[10px] text-slate-400">UV Index</div>
                  <div className="text-xs font-bold text-white">{current.uvIndex} / 11</div>
                </div>
                <div className="p-2.5 rounded-xl bg-white/5 border border-white/5 text-center">
                  <CloudRain className="w-3.5 h-3.5 text-cyan-400 mx-auto mb-1" />
                  <div className="text-[10px] text-slate-400">Rain Prob</div>
                  <div className="text-xs font-bold text-white">{current.rainProb}%</div>
                </div>
              </div>

              {/* View Tabs */}
              <div className="flex border-b border-white/10 gap-2 text-xs font-medium">
                <button
                  onClick={() => setActiveTab('meteogram')}
                  className={`pb-2 transition-colors ${
                    activeTab === 'meteogram'
                      ? 'text-cyan-400 border-b-2 border-cyan-400 font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Meteogram
                </button>
                <button
                  onClick={() => setActiveTab('hourly')}
                  className={`pb-2 transition-colors ${
                    activeTab === 'hourly'
                      ? 'text-cyan-400 border-b-2 border-cyan-400 font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Hourly (72h)
                </button>
                <button
                  onClick={() => setActiveTab('daily')}
                  className={`pb-2 transition-colors ${
                    activeTab === 'daily'
                      ? 'text-cyan-400 border-b-2 border-cyan-400 font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  7-Day Forecast
                </button>
                {nearbyWebcams.length > 0 && (
                  <button
                    onClick={() => setActiveTab('webcams')}
                    className={`pb-2 transition-colors ${
                      activeTab === 'webcams'
                        ? 'text-cyan-400 border-b-2 border-cyan-400 font-bold'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Webcams ({nearbyWebcams.length})
                  </button>
                )}
              </div>

              {/* Tab 1: Meteogram Chart */}
              {activeTab === 'meteogram' && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />
                      Temperature ({unitSystem === 'metric' ? '°C' : '°F'})
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-cyan-400 inline-block" />
                      Wind Gusts
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded bg-blue-500 inline-block" />
                      Rain (mm)
                    </span>
                  </div>

                  <div className="w-full h-44 bg-black/30 rounded-2xl p-2 border border-white/5">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                        <CartesianGrid stroke="#ffffff10" strokeDasharray="3 3" vertical={false} />
                        <XAxis
                          dataKey="time"
                          stroke="#94a3b8"
                          fontSize={9}
                          tickLine={false}
                          interval={2}
                        />
                        <YAxis stroke="#94a3b8" fontSize={9} tickLine={false} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: '#14181d',
                            borderColor: 'rgba(255,255,255,0.1)',
                            borderRadius: '12px',
                            fontSize: '11px',
                          }}
                        />
                        <Bar dataKey="precip" fill="#3b82f6" opacity={0.7} barSize={6} />
                        <Line
                          type="monotone"
                          dataKey="temp"
                          stroke="#f59e0b"
                          strokeWidth={2.5}
                          dot={false}
                        />
                        <Line
                          type="monotone"
                          dataKey="gust"
                          stroke="#06b6d4"
                          strokeWidth={1.5}
                          strokeDasharray="3 3"
                          dot={false}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* Tab 2: Hourly Table */}
              {activeTab === 'hourly' && (
                <div className="space-y-1.5 max-h-56 overflow-y-auto">
                  {(data?.hourly || []).slice(0, 36).map((h, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs text-slate-200 transition-colors"
                    >
                      <span className="w-14 font-mono text-slate-400">{h.hourLabel}</span>
                      <span className="w-24 font-bold text-white">{formatTemp(h.temp)}</span>
                      <span className="w-24 text-slate-300 truncate">{h.weatherDesc}</span>
                      <span className="w-16 text-cyan-400 font-semibold text-right">
                        {formatSpeed(h.windSpeed)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Tab 3: 7-Day Forecast */}
              {activeTab === 'daily' && (
                <div className="space-y-1.5">
                  {(data?.daily || []).map((d, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs transition-colors"
                    >
                      <span className="w-16 font-bold text-white">{d.dayLabel}</span>
                      <span className="text-slate-300 truncate flex-1 px-2">
                        {d.weatherDesc}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-rose-400 font-bold">{formatTemp(d.tempMax)}</span>
                        <span className="text-slate-500">/</span>
                        <span className="text-blue-400 font-medium">{formatTemp(d.tempMin)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Tab 4: Live Webcams */}
              {activeTab === 'webcams' && (
                <div className="grid grid-cols-2 gap-2">
                  {nearbyWebcams.map((cam) => (
                    <div
                      key={cam.id}
                      onClick={() => onOpenWebcam(cam)}
                      className="group cursor-pointer rounded-xl overflow-hidden bg-black/40 border border-white/10 hover:border-cyan-400/50 transition-all relative"
                    >
                      <img
                        src={cam.thumbnail}
                        alt={cam.title}
                        className="w-full h-24 object-cover group-hover:scale-105 transition-transform"
                      />
                      <div className="p-2">
                        <div className="text-xs font-semibold text-white truncate">
                          {cam.title}
                        </div>
                        <div className="text-[10px] text-cyan-400 flex items-center gap-1 mt-0.5">
                          <Camera className="w-2.5 h-2.5" />
                          <span>{cam.city}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};
