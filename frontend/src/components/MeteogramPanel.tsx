import React, { useState } from 'react';
import { 
  X, 
  Wind, 
  Droplets, 
  Gauge, 
  Sun, 
  CloudRain, 
  Compass, 
  ShieldAlert, 
  Sparkles, 
  Share2, 
  Bookmark, 
  ArrowUp,
  Activity
} from 'lucide-react';
import { 
  PointForecastData, 
  AIAnomalyData, 
  TempUnit, 
  WindSpeedUnit, 
  PressureUnit 
} from '../types';
import { 
  convertTemp, 
  convertSpeed, 
  convertPressure, 
  getWindCompass, 
  getWeatherDescription 
} from '../utils/weatherApi';

interface MeteogramPanelProps {
  data: PointForecastData | null;
  anomalyData: AIAnomalyData | null;
  isLoading: boolean;
  onClose: () => void;
  tempUnit: TempUnit;
  windUnit: WindSpeedUnit;
  pressureUnit: PressureUnit;
}

export const MeteogramPanel: React.FC<MeteogramPanelProps> = ({
  data,
  anomalyData,
  isLoading,
  onClose,
  tempUnit,
  windUnit,
  pressureUnit,
}) => {
  const [activeTab, setActiveTab] = useState<'forecast' | 'meteogram' | 'anomaly'>('meteogram');

  if (!data && !isLoading) return null;

  const current = data?.current;
  const location = data?.location;

  const tempVal = current ? convertTemp(current.temp, tempUnit) : { value: 0, unit: '°C' };
  const feelsLikeVal = current ? convertTemp(current.feelsLike, tempUnit) : { value: 0, unit: '°C' };
  const windVal = current ? convertSpeed(current.windSpeed, windUnit) : { value: 0, unit: 'km/h' };
  const gustsVal = current ? convertSpeed(current.windGusts, windUnit) : { value: 0, unit: 'km/h' };
  const pressureVal = current ? convertPressure(current.pressure, pressureUnit) : { value: 0, unit: 'hPa' };
  const compassDir = current ? getWindCompass(current.windDirection) : 'N';

  // SVG dimensions for meteogram
  const hourly = data?.hourly.slice(0, 24) || [];
  const temps = hourly.map(h => h.temp);
  const minT = temps.length ? Math.min(...temps) - 2 : 10;
  const maxT = temps.length ? Math.max(...temps) + 2 : 35;
  const rangeT = maxT - minT || 1;

  return (
    <aside 
      id="ather-detail-panel"
      className="absolute top-16 right-3 bottom-24 z-[1010] w-[95%] sm:w-[420px] lg:w-[480px] bg-[#1a1e26]/95 backdrop-blur-2xl border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden pointer-events-auto transition-all animate-in slide-in-from-right duration-300"
    >
      {/* Header */}
      <header className="p-4 border-b border-white/10 flex items-start justify-between bg-black/20">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold text-white tracking-tight">
              {location?.name || 'Selected Location'}
            </h2>
            {location?.country && (
              <span className="text-xs text-slate-400 bg-white/10 px-2 py-0.5 rounded font-medium">
                {location.country}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-0.5 font-mono">
            {location?.lat.toFixed(3)}°N, {location?.lon.toFixed(3)}°E • {location?.elevation ?? 120}m ASL
          </p>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            id="close-detail-panel-btn"
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-white/10 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Navigation tabs */}
      <nav className="flex items-center border-b border-white/10 bg-black/10 px-3">
        <button
          id="tab-meteogram-btn"
          onClick={() => setActiveTab('meteogram')}
          className={`py-2 px-3 text-xs font-semibold border-b-2 transition-all cursor-pointer ${
            activeTab === 'meteogram'
              ? 'border-sky-400 text-sky-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Meteogram
        </button>
        <button
          id="tab-forecast-btn"
          onClick={() => setActiveTab('forecast')}
          className={`py-2 px-3 text-xs font-semibold border-b-2 transition-all cursor-pointer ${
            activeTab === 'forecast'
              ? 'border-sky-400 text-sky-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          5-Day Forecast
        </button>
        <button
          id="tab-anomaly-btn"
          onClick={() => setActiveTab('anomaly')}
          className={`flex items-center gap-1.5 py-2 px-3 text-xs font-semibold border-b-2 transition-all cursor-pointer ${
            activeTab === 'anomaly'
              ? 'border-red-500 text-red-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>AI Anomaly (D0-D5)</span>
        </button>
      </nav>

      {/* Content scroll area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {isLoading && (
          <div className="py-12 flex flex-col items-center justify-center gap-3 text-slate-400">
            <div className="w-7 h-7 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs font-medium">Fetching meteorological point model data...</span>
          </div>
        )}

        {!isLoading && current && (
          <>
            {/* Primary Current Weather Card */}
            <div className="bg-white/5 border border-white/10 rounded-xl p-3.5 flex items-center justify-between">
              <div>
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-black tracking-tighter text-white">
                    {tempVal.value}{tempVal.unit}
                  </span>
                  <span className="text-xs text-slate-400">
                    Feels like {feelsLikeVal.value}{feelsLikeVal.unit}
                  </span>
                </div>
                <div className="text-sm font-semibold text-sky-300 mt-1">
                  {current.condition}
                </div>
              </div>

              {/* Wind compass badge */}
              <div className="bg-black/30 border border-white/10 rounded-lg p-2 flex flex-col items-center min-w-[90px]">
                <div className="flex items-center gap-1.5 text-xs text-slate-300 font-bold">
                  <div 
                    className="transition-transform duration-500"
                    style={{ transform: `rotate(${current.windDirection}deg)` }}
                  >
                    <ArrowUp className="w-4 h-4 text-sky-400" />
                  </div>
                  <span>{compassDir}</span>
                </div>
                <div className="text-sm font-black text-white mt-0.5">
                  {windVal.value} <span className="text-[10px] font-normal text-slate-400">{windVal.unit}</span>
                </div>
                <div className="text-[10px] text-slate-400">
                  gusts {gustsVal.value}
                </div>
              </div>
            </div>

            {/* Quick Metrics Grid */}
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-white/5 border border-white/5 rounded-lg p-2.5">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1">
                  <Droplets className="w-3.5 h-3.5 text-sky-400" />
                  <span>Humidity</span>
                </div>
                <div className="text-sm font-bold text-white">{current.humidity}%</div>
                <div className="text-[10px] text-slate-400">Dew pt {current.dewPoint}°C</div>
              </div>

              <div className="bg-white/5 border border-white/5 rounded-lg p-2.5">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1">
                  <Gauge className="w-3.5 h-3.5 text-blue-400" />
                  <span>Pressure</span>
                </div>
                <div className="text-sm font-bold text-white">{pressureVal.value}</div>
                <div className="text-[10px] text-slate-400">{pressureVal.unit}</div>
              </div>

              <div className="bg-white/5 border border-white/5 rounded-lg p-2.5">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1">
                  <Sun className="w-3.5 h-3.5 text-amber-400" />
                  <span>UV Index</span>
                </div>
                <div className="text-sm font-bold text-white">{current.uvIndex}</div>
                <div className="text-[10px] text-slate-400">Moderate</div>
              </div>
            </div>

            {/* Tab 1: Meteogram view */}
            {activeTab === 'meteogram' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs font-bold text-slate-300">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-sky-400" />
                    <span>24-Hour Meteogram</span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px]">
                    <span className="flex items-center gap-1 text-amber-400">
                      <span className="w-2 h-0.5 bg-amber-400 inline-block" /> Temp
                    </span>
                    <span className="flex items-center gap-1 text-sky-400">
                      <span className="w-2 h-0.5 bg-sky-400 inline-block" /> Dew pt
                    </span>
                    <span className="flex items-center gap-1 text-emerald-400">
                      <span className="w-2 h-2 bg-emerald-400/60 inline-block" /> Rain
                    </span>
                  </div>
                </div>

                {/* SVG Meteogram Graph */}
                <div className="bg-black/35 border border-white/10 rounded-xl p-3 overflow-x-auto">
                  <svg className="w-full h-36" viewBox="0 0 420 120">
                    <defs>
                      <linearGradient id="tempGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.4" />
                        <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.0" />
                      </linearGradient>
                    </defs>

                    {/* Grid lines */}
                    {[20, 50, 80].map((y, idx) => (
                      <line key={idx} x1="0" y1={y} x2="420" y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
                    ))}

                    {/* Rain bars */}
                    {hourly.map((h, i) => {
                      const x = (i / (hourly.length - 1)) * 400 + 10;
                      const rainHeight = Math.min(40, (h.precipitation || 0) * 12);
                      return (
                        <rect
                          key={`rain-${i}`}
                          x={x - 4}
                          y={110 - rainHeight}
                          width="8"
                          height={rainHeight}
                          fill="#34d399"
                          opacity="0.65"
                          rx="2"
                        />
                      );
                    })}

                    {/* Temperature Line Path */}
                    {hourly.length > 1 && (
                      <path
                        d={hourly.reduce((acc, h, i) => {
                          const x = (i / (hourly.length - 1)) * 400 + 10;
                          const y = 95 - ((h.temp - minT) / rangeT) * 75;
                          return `${acc} ${i === 0 ? 'M' : 'L'} ${x} ${y}`;
                        }, '')}
                        fill="none"
                        stroke="#fbbf24"
                        strokeWidth="2.5"
                      />
                    )}

                    {/* Dew point line */}
                    {hourly.length > 1 && (
                      <path
                        d={hourly.reduce((acc, h, i) => {
                          const x = (i / (hourly.length - 1)) * 400 + 10;
                          const y = 95 - ((h.dewPoint - minT) / rangeT) * 75;
                          return `${acc} ${i === 0 ? 'M' : 'L'} ${x} ${y}`;
                        }, '')}
                        fill="none"
                        stroke="#38bdf8"
                        strokeWidth="1.5"
                        strokeDasharray="4 2"
                      />
                    )}

                    {/* Data points */}
                    {hourly.filter((_, i) => i % 3 === 0).map((h, i) => {
                      const origIndex = i * 3;
                      const x = (origIndex / (hourly.length - 1)) * 400 + 10;
                      const y = 95 - ((h.temp - minT) / rangeT) * 75;
                      return (
                        <g key={`pt-${i}`}>
                          <circle cx={x} cy={y} r="3" fill="#fbbf24" stroke="#1a1e26" strokeWidth="1" />
                          <text x={x} y={y - 8} fill="#ffffff" fontSize="10" fontWeight="bold" textAnchor="middle">
                            {Math.round(h.temp)}°
                          </text>
                        </g>
                      );
                    })}
                  </svg>

                  {/* Hourly Wind Direction Arrows Strip */}
                  <div className="grid grid-cols-8 gap-1 pt-2 border-t border-white/10 text-center">
                    {hourly.filter((_, i) => i % 3 === 0).map((h, i) => {
                      const hourStr = new Date(h.time).getHours();
                      return (
                        <div key={i} className="flex flex-col items-center">
                          <span className="text-[10px] text-slate-400 font-mono">{hourStr}:00</span>
                          <div
                            className="my-1 text-sky-400"
                            style={{ transform: `rotate(${h.windDirection}deg)` }}
                          >
                            <ArrowUp className="w-3.5 h-3.5" />
                          </div>
                          <span className="text-[10px] font-bold text-white">
                            {Math.round(h.windSpeed)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Tab 2: 5-Day Forecast Cards */}
            {activeTab === 'forecast' && (
              <div className="space-y-2">
                <div className="text-xs font-bold text-slate-300">5-Day Weather Outlook</div>
                {data.daily.slice(0, 5).map((d, i) => (
                  <div
                    key={i}
                    className="bg-white/5 hover:bg-white/10 transition-colors border border-white/5 rounded-xl p-2.5 flex items-center justify-between"
                  >
                    <div className="min-w-[90px]">
                      <div className="text-xs font-bold text-white">{d.dayName}</div>
                      <div className="text-[11px] text-slate-400">{d.condition}</div>
                    </div>

                    <div className="flex items-center gap-2">
                      <CloudRain className="w-3.5 h-3.5 text-sky-400" />
                      <span className="text-xs text-slate-300">{d.precipitationSum.toFixed(1)} mm</span>
                    </div>

                    <div className="flex items-center gap-2 font-mono text-xs">
                      <span className="text-slate-400">{Math.round(d.tempMin)}°</span>
                      <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-sky-400 to-amber-400 rounded-full w-3/4" />
                      </div>
                      <span className="font-bold text-white">{Math.round(d.tempMax)}°</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Tab 3: SIH AI Anomaly Detection (D0-D5) */}
            {activeTab === 'anomaly' && anomalyData && (
              <div className="space-y-3">
                <div className="bg-gradient-to-br from-red-950/40 to-slate-900/60 border border-red-500/30 rounded-xl p-3.5">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-black px-2 py-0.5 rounded text-white ${
                          anomalyData.level === 'D5' ? 'bg-red-600' :
                          anomalyData.level === 'D4' ? 'bg-orange-600' :
                          anomalyData.level === 'D3' ? 'bg-amber-600' :
                          'bg-emerald-600'
                        }`}>
                          {anomalyData.level}
                        </span>
                        <h3 className="text-sm font-bold text-white">{anomalyData.title}</h3>
                      </div>
                      <p className="text-xs text-slate-300 mt-2 leading-relaxed">
                        {anomalyData.description}
                      </p>
                    </div>
                  </div>

                  {/* Anomaly Risk Score Bar */}
                  <div className="mt-3 pt-3 border-t border-white/10">
                    <div className="flex justify-between text-xs font-semibold mb-1">
                      <span className="text-slate-300">Composite Anomaly Risk</span>
                      <span className={anomalyData.riskScore > 70 ? 'text-red-400 font-bold' : 'text-amber-400'}>
                        {anomalyData.riskScore}% Severity
                      </span>
                    </div>
                    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-700 ${
                          anomalyData.riskScore > 75 ? 'bg-red-500' :
                          anomalyData.riskScore > 50 ? 'bg-orange-500' : 'bg-emerald-400'
                        }`}
                        style={{ width: `${anomalyData.riskScore}%` }}
                      />
                    </div>
                  </div>
                </div>

                {/* Factor Breakdown */}
                <div className="space-y-1.5">
                  <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Diagnostic Anomalies
                  </div>
                  {anomalyData.factors.map((f, idx) => (
                    <div
                      key={idx}
                      className="bg-white/5 border border-white/5 rounded-lg p-2 flex items-center justify-between text-xs"
                    >
                      <span className="text-slate-300">{f.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-white">{f.value}</span>
                        <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                          f.severity === 'critical' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                          f.severity === 'high' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                          f.severity === 'moderate' ? 'bg-amber-500/20 text-amber-400' :
                          'bg-emerald-500/20 text-emerald-400'
                        }`}>
                          {f.severity}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
};
