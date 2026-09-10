import React, { useState, useMemo } from 'react';
import {
  TrendingUp,
  Thermometer,
  Gauge,
  Droplets,
  Clock,
  Table as TableIcon,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Info
} from 'lucide-react';
import { ObservationPoint, StationAnomalyAssessment, Station } from '../types/weather';

interface StationHistoricalGraphsProps {
  station: Station;
  series: ObservationPoint[];
  hours: number;
  onHoursChange: (hours: number) => void;
  isLoading?: boolean;
  anomalyAssessment?: StationAnomalyAssessment | null;
}

type ParameterType = 'temperature' | 'pressure' | 'humidity';

export const StationHistoricalGraphs: React.FC<StationHistoricalGraphsProps> = ({
  station,
  series,
  hours,
  onHoursChange,
  isLoading = false,
  anomalyAssessment
}) => {
  const [activeParam, setActiveParam] = useState<ParameterType>('temperature');
  const [showTable, setShowTable] = useState<boolean>(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // Check if historical data exists
  const hasHistory = series && series.length > 0;

  // Parameter configuration
  const paramConfig = {
    temperature: {
      label: 'TEMPERATURE',
      unit: '°C',
      icon: Thermometer,
      strokeColor: '#00e5ff',
      fillStart: 'rgba(0, 229, 255, 0.35)',
      fillEnd: 'rgba(0, 229, 255, 0.0)',
      getValue: (p: ObservationPoint) => p.temperature,
      format: (v: number | null | undefined) => (v !== null && v !== undefined ? `${v.toFixed(1)} °C` : '--'),
      isAnomalyParam: anomalyAssessment?.diagnosis?.primary?.toLowerCase().includes('temp') ||
                      anomalyAssessment?.diagnosis?.affected_channels?.includes('temperature') ||
                      station.anomaly?.parameter?.toLowerCase().includes('temp'),
      expectedRange: [15, 35] as [number, number]
    },
    pressure: {
      label: 'ATMOSPHERIC PRESSURE',
      unit: 'hPa',
      icon: Gauge,
      strokeColor: '#38bdf8',
      fillStart: 'rgba(56, 189, 248, 0.35)',
      fillEnd: 'rgba(56, 189, 248, 0.0)',
      getValue: (p: ObservationPoint) => p.pressure,
      format: (v: number | null | undefined) => (v !== null && v !== undefined ? `${v.toFixed(1)} hPa` : '--'),
      isAnomalyParam: anomalyAssessment?.diagnosis?.primary?.toLowerCase().includes('press') ||
                      anomalyAssessment?.diagnosis?.affected_channels?.includes('pressure') ||
                      station.anomaly?.parameter?.toLowerCase().includes('press'),
      expectedRange: [980, 1040] as [number, number]
    },
    humidity: {
      label: 'RELATIVE HUMIDITY',
      unit: '%',
      icon: Droplets,
      strokeColor: '#2dd4bf',
      fillStart: 'rgba(45, 212, 191, 0.35)',
      fillEnd: 'rgba(45, 212, 191, 0.0)',
      getValue: (p: ObservationPoint) => p.humidity,
      format: (v: number | null | undefined) => (v !== null && v !== undefined ? `${Math.round(v)}%` : '--'),
      isAnomalyParam: anomalyAssessment?.diagnosis?.primary?.toLowerCase().includes('humid') ||
                      anomalyAssessment?.diagnosis?.affected_channels?.includes('humidity') ||
                      station.anomaly?.parameter?.toLowerCase().includes('humid'),
      expectedRange: [20, 95] as [number, number]
    }
  };

  const currentCfg = paramConfig[activeParam];

  // Extract valid data points for active parameter
  const validData = useMemo(() => {
    if (!hasHistory) return [];
    return series
      .map((p, idx) => ({ point: p, val: currentCfg.getValue(p), index: idx }))
      .filter((d): d is { point: ObservationPoint; val: number; index: number } => d.val !== null && d.val !== undefined && !isNaN(d.val));
  }, [series, activeParam, hasHistory]);

  // Derive statistical summary
  const stats = useMemo(() => {
    if (validData.length === 0) return null;
    const values = validData.map((d) => d.val);
    const sorted = [...values].sort((a, b) => a - b);
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const median = sorted[Math.floor(sorted.length / 2)];
    const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
    const latest = values[values.length - 1];

    // Determine parameter state
    let state = 'NORMAL';
    if (currentCfg.isAnomalyParam) {
      state = station.status === 'ANOMALY' ? 'ANOMALY' : 'WARNING';
    }

    return {
      current: latest,
      median,
      mean,
      min,
      max,
      range: `${min.toFixed(1)} – ${max.toFixed(1)} ${currentCfg.unit}`,
      state,
      count: values.length,
      detectedEvents: currentCfg.isAnomalyParam ? 1 : 0
    };
  }, [validData, currentCfg, station.status]);

  // Chart dimensions & scaling
  const chartWidth = 330;
  const chartHeight = 130;
  const padLeft = 38;
  const padRight = 14;
  const padTop = 14;
  const padBottom = 22;

  const plotW = chartWidth - padLeft - padRight;
  const plotH = chartHeight - padTop - padBottom;

  const { minVal, maxVal, pointsString, pathD, coordinates } = useMemo(() => {
    if (validData.length < 2) {
      return { minVal: 0, maxVal: 100, pointsString: '', pathD: '', coordinates: [] };
    }

    const rawMin = Math.min(...validData.map((d) => d.val));
    const rawMax = Math.max(...validData.map((d) => d.val));
    const padding = Math.max((rawMax - rawMin) * 0.15, 1.0);
    const minV = Math.floor(rawMin - padding);
    const maxV = Math.ceil(rawMax + padding);
    const range = maxV - minV || 1;

    const coords = validData.map((d, i) => {
      const x = padLeft + (i / (validData.length - 1)) * plotW;
      const y = padTop + plotH - ((d.val - minV) / range) * plotH;
      return { x, y, val: d.val, point: d.point, index: d.index };
    });

    const pts = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');

    // SVG Area path
    const firstX = coords[0].x.toFixed(1);
    const lastX = coords[coords.length - 1].x.toFixed(1);
    const bottomY = (padTop + plotH).toFixed(1);
    const areaPath = `M ${firstX},${bottomY} L ${pts.replace(/ /g, ' L ')} L ${lastX},${bottomY} Z`;

    return { minVal: minV, maxVal: maxV, pointsString: pts, pathD: areaPath, coordinates: coords };
  }, [validData, plotW, plotH, padLeft, padTop]);

  // Baseline reference band (if available from statistical bounds or normal climate range)
  const baselineBand = useMemo(() => {
    if (!stats || validData.length < 2) return null;
    const range = maxVal - minVal || 1;
    // Compute ±1.5σ or expected range band
    const expectedMin = Math.max(minVal, stats.mean - 2.5);
    const expectedMax = Math.min(maxVal, stats.mean + 2.5);
    const yTop = padTop + plotH - ((expectedMax - minVal) / range) * plotH;
    const yBottom = padTop + plotH - ((expectedMin - minVal) / range) * plotH;
    return {
      y: Math.max(padTop, yTop),
      height: Math.max(2, yBottom - yTop)
    };
  }, [stats, validData, minVal, maxVal, plotH, padTop]);

  // Handle mouse hovering over SVG for precision tooltip
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (coordinates.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const mouseX = ((e.clientX - rect.left) / rect.width) * chartWidth;
    let closestIndex = 0;
    let closestDist = Infinity;
    coordinates.forEach((c, idx) => {
      const dist = Math.abs(c.x - mouseX);
      if (dist < closestDist) {
        closestDist = dist;
        closestIndex = idx;
      }
    });
    setHoveredIndex(closestIndex);
  };

  const hoveredCoord = hoveredIndex !== null && coordinates[hoveredIndex] ? coordinates[hoveredIndex] : null;

  return (
    <div className="section-card historical-graphs-card">
      {/* 1. Header with Range Toggles & Table Toggle */}
      <div className="card-header-flex">
        <div className="card-title-group">
          <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
          <span className="card-section-title">HISTORICAL READINGS & CHARTS</span>
        </div>

        <div className="graph-controls-cluster">
          {/* Time Range Selector (Phase 9) */}
          <div className="range-toggle-pill" role="group" aria-label="Historical observation time range">
            <button
              className={`range-btn ${hours === 24 ? 'active' : ''}`}
              onClick={() => onHoursChange(24)}
              disabled={isLoading}
              title="Show last 24 hours of observations"
            >
              24H
            </button>
            <button
              className={`range-btn ${hours === 168 ? 'active' : ''}`}
              onClick={() => onHoursChange(168)}
              disabled={isLoading}
              title="Show last 7 days of observations"
            >
              7D
            </button>
          </div>

          {/* Table View Toggle (Phase 10) */}
          <button
            className={`table-toggle-btn ${showTable ? 'active' : ''}`}
            onClick={() => setShowTable(!showTable)}
            title={showTable ? 'Hide telemetry table' : 'Show raw telemetry data table'}
          >
            <TableIcon className="w-3 h-3" />
            <span>Table</span>
          </button>
        </div>
      </div>

      {/* 2. Parameter Selection Tabs (Phase 11) */}
      <div className="param-tab-selector" role="tablist">
        <button
          role="tab"
          aria-selected={activeParam === 'temperature'}
          className={`param-tab-btn ${activeParam === 'temperature' ? 'active' : ''}`}
          onClick={() => { setActiveParam('temperature'); setHoveredIndex(null); }}
        >
          <Thermometer className="w-3 h-3" />
          <span>Temp</span>
          {paramConfig.temperature.isAnomalyParam && <span className="param-anomaly-dot" />}
        </button>

        <button
          role="tab"
          aria-selected={activeParam === 'pressure'}
          className={`param-tab-btn ${activeParam === 'pressure' ? 'active' : ''}`}
          onClick={() => { setActiveParam('pressure'); setHoveredIndex(null); }}
        >
          <Gauge className="w-3 h-3" />
          <span>Pressure</span>
          {paramConfig.pressure.isAnomalyParam && <span className="param-anomaly-dot" />}
        </button>

        <button
          role="tab"
          aria-selected={activeParam === 'humidity'}
          className={`param-tab-btn ${activeParam === 'humidity' ? 'active' : ''}`}
          onClick={() => { setActiveParam('humidity'); setHoveredIndex(null); }}
        >
          <Droplets className="w-3 h-3" />
          <span>Humidity</span>
          {paramConfig.humidity.isAnomalyParam && <span className="param-anomaly-dot" />}
        </button>
      </div>

      {/* 3. Empty or Loading State Handling */}
      {!hasHistory ? (
        <div className="historical-unavailable-box">
          <Info className="w-5 h-5 text-slate-500 mb-1.5" />
          <span className="unavailable-title">HISTORICAL DATA UNAVAILABLE</span>
          <p className="unavailable-desc">
            No continuous telemetry history is currently recorded for AWS station{' '}
            <span className="font-mono text-cyan-300">{station.id}</span>. In-situ observation pipeline is active.
          </p>
        </div>
      ) : validData.length < 2 ? (
        <div className="historical-unavailable-box">
          <Info className="w-5 h-5 text-slate-500 mb-1.5" />
          <span className="unavailable-title">INSUFFICIENT HISTORICAL DATA</span>
          <p className="unavailable-desc">
            Only {validData.length} valid reading available for {currentCfg.label.toLowerCase()}.
            Minimum 2 historical readings required for analytical trend projection.
          </p>
        </div>
      ) : (
        <>
          {/* 4. Interactive SVG Graph (Phase 11, 12, 14) */}
          <div className="svg-chart-container">
            <svg
              className="analytical-graph-svg"
              viewBox={`0 0 ${chartWidth} ${chartHeight}`}
              onMouseMove={handleMouseMove}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <defs>
                <linearGradient id={`gradient-${activeParam}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={currentCfg.strokeColor} stopOpacity="0.45" />
                  <stop offset="100%" stopColor={currentCfg.strokeColor} stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Background grid lines */}
              <line
                x1={padLeft}
                y1={padTop}
                x2={chartWidth - padRight}
                y2={padTop}
                stroke="#334155"
                strokeDasharray="2 3"
                strokeWidth="0.75"
              />
              <line
                x1={padLeft}
                y1={padTop + plotH / 2}
                x2={chartWidth - padRight}
                y2={padTop + plotH / 2}
                stroke="#1e293b"
                strokeDasharray="2 3"
                strokeWidth="0.75"
              />
              <line
                x1={padLeft}
                y1={padTop + plotH}
                x2={chartWidth - padRight}
                y2={padTop + plotH}
                stroke="#334155"
                strokeWidth="1"
              />

              {/* Baseline reference band (Phase 12) */}
              {baselineBand && (
                <rect
                  x={padLeft}
                  y={baselineBand.y}
                  width={plotW}
                  height={baselineBand.height}
                  fill="rgba(56, 189, 248, 0.08)"
                  stroke="rgba(56, 189, 248, 0.2)"
                  strokeDasharray="2 2"
                  strokeWidth="0.5"
                />
              )}

              {/* Y-Axis Value Labels */}
              <text x={padLeft - 6} y={padTop + 4} textAnchor="end" className="chart-axis-label">
                {maxVal}
              </text>
              <text x={padLeft - 6} y={padTop + plotH / 2 + 3} textAnchor="end" className="chart-axis-label">
                {Math.round((maxVal + minVal) / 2)}
              </text>
              <text x={padLeft - 6} y={padTop + plotH} textAnchor="end" className="chart-axis-label">
                {minVal}
              </text>

              {/* Shaded Area Fill */}
              {pathD && <path d={pathD} fill={`url(#gradient-${activeParam})`} />}

              {/* Time-series Polyline */}
              {pointsString && (
                <polyline
                  fill="none"
                  stroke={currentCfg.strokeColor}
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={pointsString}
                />
              )}

              {/* Anomaly Outlier Marker (Phase 12, 14) */}
              {currentCfg.isAnomalyParam && coordinates.length > 0 && (
                <g className="anomaly-marker-group">
                  <circle
                    cx={coordinates[coordinates.length - 1].x}
                    cy={coordinates[coordinates.length - 1].y}
                    r="6.5"
                    fill={station.status === 'ANOMALY' ? '#ef4444' : '#f59e0b'}
                    stroke="#ffffff"
                    strokeWidth="2"
                    className="anomaly-pulse-ring"
                  />
                  <circle
                    cx={coordinates[coordinates.length - 1].x}
                    cy={coordinates[coordinates.length - 1].y}
                    r="3.5"
                    fill="#ffffff"
                  />
                </g>
              )}

              {/* Hover Cursor Guideline & Highlight Point */}
              {hoveredCoord && (
                <g className="chart-hover-group">
                  <line
                    x1={hoveredCoord.x}
                    y1={padTop}
                    x2={hoveredCoord.x}
                    y2={padTop + plotH}
                    stroke="#94a3b8"
                    strokeDasharray="2 2"
                    strokeWidth="1"
                  />
                  <circle
                    cx={hoveredCoord.x}
                    cy={hoveredCoord.y}
                    r="4.5"
                    fill={currentCfg.strokeColor}
                    stroke="#ffffff"
                    strokeWidth="2"
                  />
                </g>
              )}

              {/* X-Axis Time Labels */}
              <text x={padLeft} y={chartHeight - 6} textAnchor="start" className="chart-axis-label">
                {hours === 168 ? '7d ago' : '24h ago'}
              </text>
              <text x={padLeft + plotW / 2} y={chartHeight - 6} textAnchor="middle" className="chart-axis-label">
                {hours === 168 ? '3d ago' : '12h ago'}
              </text>
              <text x={chartWidth - padRight} y={chartHeight - 6} textAnchor="end" className="chart-axis-label">
                Now (In-Situ)
              </text>
            </svg>

            {/* Interactive Floating Hover Tooltip (Phase 29) */}
            {hoveredCoord && (
              <div
                className="chart-hover-tooltip"
                style={{
                  left: `${Math.max(10, Math.min(chartWidth - 120, hoveredCoord.x - 55))}px`,
                  top: `${Math.max(4, hoveredCoord.y - 42)}px`
                }}
              >
                <div className="tooltip-time">
                  <Clock className="w-2.5 h-2.5 text-slate-400 inline mr-1" />
                  {hoveredCoord.point.timeLabel || 'Observation'}
                </div>
                <div className="tooltip-val font-mono">
                  {currentCfg.format(hoveredCoord.val)}
                </div>
              </div>
            )}
          </div>

          {/* 5. Graph Analysis Summary (Phase 13) */}
          {stats && (
            <div className="graph-analysis-summary">
              <div className="summary-stat-box">
                <span className="stat-box-lbl">CURRENT</span>
                <span className="stat-box-val font-mono">{currentCfg.format(stats.current)}</span>
              </div>
              <div className="summary-stat-box">
                <span className="stat-box-lbl">MEDIAN</span>
                <span className="stat-box-val font-mono">{currentCfg.format(stats.median)}</span>
              </div>
              <div className="summary-stat-box">
                <span className="stat-box-lbl">RANGE</span>
                <span className="stat-box-val font-mono text-xs">{stats.range}</span>
              </div>
              <div className="summary-stat-box">
                <span className="stat-box-lbl">STATUS</span>
                <span className={`stat-box-status ${stats.state.toLowerCase()}`}>
                  ● {stats.state}
                </span>
              </div>
            </div>
          )}

          {/* 6. Raw Historical Data Table (Phase 10) */}
          {showTable && (
            <div className="historical-table-container">
              <div className="table-header-row">
                <span className="th-col time">TIME</span>
                <span className="th-col temp">TEMP</span>
                <span className="th-col press">PRESSURE</span>
                <span className="th-col humid">HUMIDITY</span>
                <span className="th-col status">STATUS</span>
              </div>
              <div className="table-rows-scroll">
                {series.slice().reverse().map((p, idx) => (
                  <div key={idx} className="table-data-row">
                    <span className="td-col time font-mono">{p.timeLabel || `${idx}h ago`}</span>
                    <span className="td-col temp font-mono">{p.temperature !== null && p.temperature !== undefined ? `${p.temperature.toFixed(1)}°C` : '--'}</span>
                    <span className="td-col press font-mono">{p.pressure !== null && p.pressure !== undefined ? `${p.pressure.toFixed(1)}` : '--'}</span>
                    <span className="td-col humid font-mono">{p.humidity !== null && p.humidity !== undefined ? `${Math.round(p.humidity)}%` : '--'}</span>
                    <span className="td-col status">
                      <span className={`table-status-pill ${idx === 0 && station.status === 'ANOMALY' ? 'anomaly' : 'normal'}`}>
                        {idx === 0 ? station.status : 'NORMAL'}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
