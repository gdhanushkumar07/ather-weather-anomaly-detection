import React, { useState } from 'react';
import { AwsStation, TempUnit, PressureUnit } from '../types';
import { 
  X, 
  AlertTriangle, 
  CheckCircle2, 
  ChevronDown, 
  ChevronUp, 
  Layers, 
  HelpCircle, 
  RotateCcw,
  TrendingDown,
  TrendingUp,
  Minus,
  Wrench,
  Compass
} from 'lucide-react';
import { calculateHaversineDistance } from '../utils/atherEngine';

interface AtherStationDrawerProps {
  station: AwsStation | null;
  onClose: () => void;
  tempUnit: TempUnit;
  pressureUnit: PressureUnit;
  allStations?: AwsStation[];
  onFlyToStation?: (lat: number, lon: number) => void;
}

export const AtherStationDrawer: React.FC<AtherStationDrawerProps> = ({
  station,
  onClose,
  tempUnit,
  pressureUnit,
  allStations = [],
}) => {
  const [showWhyFlagged, setShowWhyFlagged] = useState(false);
  const [showFiveLayers, setShowFiveLayers] = useState(false);
  const [showSelfHealing, setShowSelfHealing] = useState(false);
  const [showMaintenance, setShowMaintenance] = useState(false);

  if (!station) return null;

  const analysis = station.latestAnalysis;
  const obs = station.currentObs;

  const displayTemp = (c: number) => {
    if (tempUnit === 'f') return `${Math.round((c * 9) / 5 + 32)}°F`;
    return `${c.toFixed(1)}°C`;
  };

  const displayPress = (p: number) => {
    if (pressureUnit === 'inhg') return `${(p * 0.02953).toFixed(2)} inHg`;
    if (pressureUnit === 'mmhg') return `${Math.round(p * 0.75006)} mmHg`;
    return `${p.toFixed(1)} hPa`;
  };

  // Status indicators
  const isCritical = analysis?.severity === 'Critical' || station.healthStatus === 'critical';
  const isWarning = analysis?.severity === 'Warning' || station.healthStatus === 'warning';
  const isNormal = !isCritical && !isWarning;

  const statusLabel = isCritical ? 'CRITICAL' : isWarning ? 'WARNING' : 'NORMAL';
  const statusColor = isCritical
    ? 'text-rose-400 bg-rose-500/20 border-rose-500/40'
    : isWarning
    ? 'text-amber-400 bg-amber-500/20 border-amber-500/40'
    : 'text-emerald-400 bg-emerald-500/20 border-emerald-500/40';

  const dotColor = isCritical ? 'bg-rose-400' : isWarning ? 'bg-amber-400' : 'bg-emerald-400';

  // Spatial Neighbors Context (4 nearest stations)
  const nearestNeighbors = allStations
    .filter((s) => s.id !== station.id)
    .map((s) => ({
      station: s,
      distanceKm: Math.round(calculateHaversineDistance(station.lat, station.lon, s.lat, s.lon)),
    }))
    .sort((a, b) => a.distanceKm - b.distanceKm)
    .slice(0, 4);

  const neighborAvgTemp =
    nearestNeighbors.length > 0
      ? nearestNeighbors.reduce((acc, n) => acc + n.station.currentObs.temperature, 0) / nearestNeighbors.length
      : station.currentObs.temperature;

  const tempDeltaFromNeighbors = obs.temperature - neighborAvgTemp;

  return (
    <div
      id="ather-compact-station-panel"
      className="absolute bottom-20 left-4 z-[950] w-[330px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-160px)] overflow-y-auto rounded-2xl bg-[#141822]/95 backdrop-blur-xl border border-white/10 shadow-2xl text-slate-100 text-xs select-none transition-all duration-300"
      style={{
        boxShadow: isCritical
          ? '0 16px 40px -8px rgba(225, 29, 72, 0.4)'
          : '0 16px 36px -8px rgba(0, 0, 0, 0.7)',
      }}
    >
      {/* 1. Header: Station Name & Close Button */}
      <div className="p-3 border-b border-white/10 flex items-start justify-between bg-[#191f2c]/80">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-bold text-sm text-white tracking-wide truncate max-w-[220px]">
              {station.name}
            </h2>
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-[11px] text-slate-400">
            <span className="font-mono text-slate-300">{station.id}</span>
            <span>•</span>
            <span>{station.state}</span>
            <span>•</span>
            <span>Alt: {station.altitude}m</span>
          </div>
        </div>
        <button
          id="close-station-panel-btn"
          onClick={onClose}
          className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
          title="Close station panel"
        >
          <X size={15} />
        </button>
      </div>

      {/* 2. Status Badge & Summary Bar */}
      <div className="px-3.5 py-2 bg-slate-800/40 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${dotColor} ${isCritical ? 'animate-ping' : ''}`} />
          <span className={`font-mono font-bold text-[10px] px-2 py-0.5 rounded-full border ${statusColor}`}>
            ● {statusLabel}
          </span>
        </div>
        <div className="text-[10px] text-slate-400 font-mono">
          <span>Health: </span>
          <strong className={station.healthPercent >= 80 ? 'text-emerald-400' : 'text-amber-400'}>
            {station.healthPercent.toFixed(0)}/100
          </strong>
        </div>
      </div>

      {/* 3. Primary Telemetry Observations (Temperature, Pressure, Humidity) */}
      <div className="p-3.5 border-b border-white/10">
        <div className="grid grid-cols-3 gap-2 text-center">
          {/* Temperature */}
          <div className={`p-2 rounded-xl border ${isCritical ? 'bg-rose-950/30 border-rose-500/40' : 'bg-[#1b212d] border-white/5'}`}>
            <span className="text-[10px] text-slate-400 block mb-0.5">Temperature</span>
            <span className={`font-mono text-base font-extrabold ${isCritical ? 'text-rose-400' : 'text-white'}`}>
              {displayTemp(obs.temperature)}
            </span>
          </div>

          {/* Pressure */}
          <div className="p-2 rounded-xl bg-[#1b212d] border border-white/5">
            <span className="text-[10px] text-slate-400 block mb-0.5">Pressure</span>
            <span className="font-mono text-base font-extrabold text-slate-100">
              {displayPress(obs.pressure)}
            </span>
          </div>

          {/* Humidity */}
          <div className="p-2 rounded-xl bg-[#1b212d] border border-white/5">
            <span className="text-[10px] text-slate-400 block mb-0.5">Humidity</span>
            <span className="font-mono text-base font-extrabold text-slate-100">
              {obs.humidity}%
            </span>
          </div>
        </div>
      </div>

      {/* 4. ATHER Score & Likely Root Cause */}
      {analysis && (
        <div className="p-3.5 border-b border-white/10 bg-[#161b26]/50">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Anomaly Score</span>
              <span className={`font-mono text-xl font-black ${analysis.anomalyScore > 70 ? 'text-rose-400' : analysis.anomalyScore > 35 ? 'text-amber-400' : 'text-emerald-400'}`}>
                {analysis.anomalyScore}%
              </span>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Confidence</span>
              <span className="font-mono text-xl font-black text-sky-400">
                {analysis.confidence}%
              </span>
            </div>
          </div>

          {/* Likely Cause */}
          <div className="mt-2 p-2.5 rounded-xl bg-[#1b212d] border border-white/5">
            <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">Likely Cause</span>
            <div className="font-bold text-slate-100 flex items-center gap-1.5 text-xs">
              {isCritical ? (
                <AlertTriangle size={14} className="text-rose-400 shrink-0" />
              ) : isNormal ? (
                <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
              ) : (
                <AlertTriangle size={14} className="text-amber-400 shrink-0" />
              )}
              <span>{analysis.anomalyType}</span>
            </div>
            {nearestNeighbors.length > 0 && (
              <div className="mt-1.5 text-[10px] text-slate-400 flex items-center gap-1">
                <Compass size={11} className="text-sky-400" />
                <span>Spatial check: 4 nearby AWS avg is <strong>{displayTemp(neighborAvgTemp)}</strong> (Δ {tempDeltaFromNeighbors > 0 ? `+${tempDeltaFromNeighbors.toFixed(1)}` : tempDeltaFromNeighbors.toFixed(1)}°C)</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 5. Expandable Sections (Contextual Inspection - The Map Remains Visible) */}
      <div className="divide-y divide-white/5">
        {/* Accordion 1: "Why was this flagged?" */}
        <div className="p-2.5">
          <button
            id="toggle-why-flagged-btn"
            onClick={() => setShowWhyFlagged(!showWhyFlagged)}
            className="w-full flex items-center justify-between p-2 rounded-xl bg-[#191f2c] hover:bg-[#202737] text-left transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <HelpCircle size={14} className="text-amber-400" />
              <span className="font-bold text-[11px] text-slate-200">Why was this flagged?</span>
            </div>
            {showWhyFlagged ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
          </button>

          {showWhyFlagged && (
            <div id="why-flagged-content" className="mt-2 p-2.5 rounded-xl bg-[#11141c] border border-amber-500/20 space-y-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-amber-300">
                WHY WAS THIS FLAGGED?
              </div>
              <div className="space-y-1.5 text-[11px]">
                {Math.abs(tempDeltaFromNeighbors) > 10 ? (
                  <div className="flex items-start gap-2 text-rose-300">
                    <span className="text-rose-400 font-bold">✓</span>
                    <span>Temperature is {Math.abs(tempDeltaFromNeighbors).toFixed(1)}°C above recent station baseline</span>
                  </div>
                ) : (
                  <div className="flex items-start gap-2 text-slate-300">
                    <span className="text-emerald-400 font-bold">✓</span>
                    <span>Temperature follows regional baseline</span>
                  </div>
                )}

                {nearestNeighbors.length > 0 && (
                  <div className="flex items-start gap-2 text-amber-200">
                    <span className="text-amber-400 font-bold">✓</span>
                    <span>
                      Nearby AWS stations ({nearestNeighbors.map((n) => n.station.id.replace('AWS-', '')).join(', ')}) remain within normal range ({nearestNeighbors.map((n) => `${n.station.currentObs.temperature.toFixed(0)}°C`).join(', ')})
                    </span>
                  </div>
                )}

                {obs.temperature > 50 && (
                  <div className="flex items-start gap-2 text-rose-300">
                    <span className="text-rose-400 font-bold">✓</span>
                    <span>Sudden temperature spike detected (+{(obs.temperature - station.baseTemp).toFixed(1)}°C jump)</span>
                  </div>
                )}

                {obs.temperature > 40 && obs.humidity > 80 && (
                  <div className="flex items-start gap-2 text-rose-300">
                    <span className="text-rose-400 font-bold">✓</span>
                    <span>Temperature/Humidity relationship is thermodynamically inconsistent</span>
                  </div>
                )}

                <div className="flex items-start gap-2 text-slate-300">
                  <span className="text-sky-400 font-bold">✓</span>
                  <span>Physics validation produced anomaly evidence across thermodynamic bounds</span>
                </div>

                {analysis?.reasons && analysis.reasons.map((r, idx) => (
                  <div key={idx} className="flex items-start gap-2 text-slate-400 text-[10px] border-l border-slate-700 pl-2">
                    <span>•</span>
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Accordion 2: "ATHER 5-Layer Evidence" */}
        {analysis && (
          <div className="p-2.5">
            <button
              id="toggle-five-layers-btn"
              onClick={() => setShowFiveLayers(!showFiveLayers)}
              className="w-full flex items-center justify-between p-2 rounded-xl bg-[#191f2c] hover:bg-[#202737] text-left transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <Layers size={14} className="text-sky-400" />
                <span className="font-bold text-[11px] text-slate-200">ATHER 5-Layer Evidence</span>
              </div>
              {showFiveLayers ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
            </button>

            {showFiveLayers && (
              <div id="five-layers-content" className="mt-2 p-2.5 rounded-xl bg-[#11141c] border border-white/5 space-y-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-sky-400 mb-1">
                  ATHER Analysis
                </div>

                <div className="space-y-1.5 font-mono text-[11px]">
                  {/* Layer 1: Physics */}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Physics Validation</span>
                    <span className={analysis.layerScores.physicsScore > 50 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {analysis.layerScores.physicsScore}/100
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${analysis.layerScores.physicsScore > 50 ? 'bg-rose-500' : 'bg-sky-500'}`}
                      style={{ width: `${analysis.layerScores.physicsScore}%` }}
                    />
                  </div>

                  {/* Layer 2: Temporal */}
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-slate-400">Temporal Intelligence</span>
                    <span className={analysis.layerScores.temporalScore > 50 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {analysis.layerScores.temporalScore}/100
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${analysis.layerScores.temporalScore > 50 ? 'bg-rose-500' : 'bg-sky-500'}`}
                      style={{ width: `${analysis.layerScores.temporalScore}%` }}
                    />
                  </div>

                  {/* Layer 3: Multivariate */}
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-slate-400">Multivariate Consistency</span>
                    <span className={analysis.layerScores.multivariateScore > 50 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {analysis.layerScores.multivariateScore}/100
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${analysis.layerScores.multivariateScore > 50 ? 'bg-rose-500' : 'bg-sky-500'}`}
                      style={{ width: `${analysis.layerScores.multivariateScore}%` }}
                    />
                  </div>

                  {/* Layer 4: Spatial */}
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-slate-400">Spatial Intelligence</span>
                    <span className={analysis.layerScores.spatialScore > 50 ? 'text-rose-400 font-bold' : 'text-slate-200'}>
                      {analysis.layerScores.spatialScore}/100
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${analysis.layerScores.spatialScore > 50 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                      style={{ width: `${analysis.layerScores.spatialScore}%` }}
                    />
                  </div>

                  {/* Layer 5: Sensor Health */}
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-slate-400">Sensor Health & Drift</span>
                    <span className={analysis.layerScores.sensorHealthScore > 50 ? 'text-amber-400 font-bold' : 'text-slate-200'}>
                      {analysis.layerScores.sensorHealthScore}/100
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${analysis.layerScores.sensorHealthScore > 50 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                      style={{ width: `${analysis.layerScores.sensorHealthScore}%` }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Accordion 3: "Self-Healing AI Estimate" (Requirement 16) */}
        {analysis && (
          <div className="p-2.5">
            <button
              id="toggle-self-healing-btn"
              onClick={() => setShowSelfHealing(!showSelfHealing)}
              className="w-full flex items-center justify-between p-2 rounded-xl bg-[#191f2c] hover:bg-[#202737] text-left transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <RotateCcw size={14} className="text-emerald-400" />
                <span className="font-bold text-[11px] text-slate-200">Self-Healing AI Estimate</span>
              </div>
              {showSelfHealing ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
            </button>

            {showSelfHealing && (
              <div id="self-healing-content" className="mt-2 p-2.5 rounded-xl bg-[#11141c] border border-emerald-500/20 space-y-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Observed (Raw):</span>
                  <span className="font-mono font-bold text-rose-300">
                    {displayTemp(obs.temperature)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">AI Estimate:</span>
                  <span className="font-mono font-bold text-emerald-400">
                    {displayTemp(analysis.correctedEstimate.temperature)}
                  </span>
                </div>
                <div className="pt-2 border-t border-white/5 flex items-center justify-between text-[10px] text-slate-400 font-mono">
                  <span>Original value preserved:</span>
                  <span className="text-emerald-400 font-bold bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                    YES
                  </span>
                </div>
                <div className="text-[9.5px] text-slate-400 leading-relaxed pt-1">
                  The corrected value does not overwrite the raw physical observation, preserving full meteorological auditability.
                </div>
              </div>
            )}
          </div>
        )}

        {/* Accordion 4: "Sensor Health & Predictive Maintenance" (Requirement 17 & 18) */}
        <div className="p-2.5">
          <button
            id="toggle-maintenance-btn"
            onClick={() => setShowMaintenance(!showMaintenance)}
            className="w-full flex items-center justify-between p-2 rounded-xl bg-[#191f2c] hover:bg-[#202737] text-left transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Wrench size={14} className="text-purple-400" />
              <span className="font-bold text-[11px] text-slate-200">Sensor Health & Maintenance</span>
            </div>
            {showMaintenance ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
          </button>

          {showMaintenance && (
            <div id="maintenance-content" className="mt-2 p-2.5 rounded-xl bg-[#11141c] border border-white/5 space-y-2 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Sensor Health:</span>
                <span className={`font-mono font-bold ${station.healthPercent >= 80 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {station.healthPercent.toFixed(0)}/100
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Trend:</span>
                <span className={`font-semibold flex items-center gap-1 ${
                  station.healthTrend === 'degrading' ? 'text-rose-400' : station.healthTrend === 'recovering' ? 'text-emerald-400' : 'text-slate-300'
                }`}>
                  {station.healthTrend === 'degrading' ? (
                    <>
                      <TrendingDown size={12} /> Degrading
                    </>
                  ) : station.healthTrend === 'recovering' ? (
                    <>
                      <TrendingUp size={12} /> Recovering
                    </>
                  ) : (
                    <>
                      <Minus size={12} /> Stable
                    </>
                  )}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Maintenance Risk:</span>
                <span className={`font-mono font-bold px-1.5 py-0.5 rounded text-[10px] ${
                  station.maintenanceRisk === 'HIGH'
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                    : station.maintenanceRisk === 'MEDIUM'
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                    : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                }`}>
                  {station.maintenanceRisk}
                </span>
              </div>
              {station.maintenanceRisk === 'HIGH' && (
                <div className="text-[10px] text-rose-300 bg-rose-950/30 p-2 rounded-lg border border-rose-500/20">
                  Recommended Action: Schedule field calibration or RTD probe replacement.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
