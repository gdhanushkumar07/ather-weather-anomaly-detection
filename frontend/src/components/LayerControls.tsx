import React from 'react';
import { Thermometer, Gauge, Droplets, Radio, X, ShieldAlert, Filter, Layers, Check } from 'lucide-react';
import { WeatherLayerType } from '../types/weather';

interface LayerControlsProps {
  isOpen: boolean;
  onClose: () => void;
  activeLayers: Record<WeatherLayerType, boolean>;
  onToggleLayer: (layer: WeatherLayerType) => void;
  basemap: 'dark' | 'satellite';
  onToggleBasemap: (mode: 'dark' | 'satellite') => void;
  showAnomalyOverlay: boolean;
  onToggleAnomalyOverlay: () => void;
  statusFilter: string | null;
  onSetStatusFilter: (status: string | null) => void;
}

export const LayerControls: React.FC<LayerControlsProps> = ({
  isOpen,
  onClose,
  activeLayers,
  onToggleLayer,
  basemap,
  onToggleBasemap,
  showAnomalyOverlay,
  onToggleAnomalyOverlay,
  statusFilter,
  onSetStatusFilter
}) => {
  if (!isOpen) return null;

  return (
    <aside className="weather-controls-right map-options-popover" role="dialog" aria-label="Map Layers">
      <div className="map-options-popover-header">
        <div className="flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-blue-600" />
          <span className="map-options-popover-title">MAP LAYERS</span>
        </div>
        <button className="map-options-close-btn" onClick={onClose} title="Close Map Layers" aria-label="Close">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Group 1: WEATHER */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>WEATHER</span>
        </div>

        <div
          className={`control-capsule ${activeLayers.temperature ? 'active' : ''}`}
          onClick={() => onToggleLayer('temperature')}
          title="Surface Temperature observation layer"
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.temperature ? 'active' : ''}`} />
            <span className="capsule-param-name">Temperature</span>
          </div>
          <div className="capsule-badge-group">
            <div className="circle-icon-badge temp-gradient-badge">
              <Thermometer className="w-3 h-3 text-orange-500" />
            </div>
          </div>
        </div>

        <div
          className={`control-capsule ${activeLayers.pressure ? 'active' : ''}`}
          onClick={() => onToggleLayer('pressure')}
          title="Atmospheric Pressure observation layer"
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.pressure ? 'active' : ''}`} />
            <span className="capsule-param-name">Pressure</span>
          </div>
          <div className="capsule-badge-group">
            <div className="circle-icon-badge pressure-gradient-badge">
              <Gauge className="w-3 h-3 text-blue-500" />
            </div>
          </div>
        </div>

        <div
          className={`control-capsule ${activeLayers.humidity ? 'active' : ''}`}
          onClick={() => onToggleLayer('humidity')}
          title="Relative Humidity observation layer"
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.humidity ? 'active' : ''}`} />
            <span className="capsule-param-name">Relative Humidity</span>
          </div>
          <div className="capsule-badge-group">
            <div className="circle-icon-badge humidity-gradient-badge">
              <Droplets className="w-3 h-3 text-teal-500" />
            </div>
          </div>
        </div>
      </div>

      {/* Group 2: STATIONS */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>STATIONS</span>
        </div>

        <div
          className={`display-row-toggle ${activeLayers.stations ? 'active' : ''}`}
          onClick={() => onToggleLayer('stations')}
          title="Toggle AWS Stations"
        >
          <div className="aws-toggle-left">
            <Radio className="w-3.5 h-3.5 text-blue-600" />
            <span className="aws-status-text">AWS Stations</span>
          </div>
          <span className={`display-row-state ${activeLayers.stations ? 'on' : ''}`}>
            {activeLayers.stations ? <Check className="w-3 h-3" /> : 'OFF'}
          </span>
        </div>

        <div
          className={`display-row-toggle ${showAnomalyOverlay ? 'active' : ''}`}
          onClick={onToggleAnomalyOverlay}
          title="Toggle Anomaly Indicators"
        >
          <div className="aws-toggle-left">
            <ShieldAlert className="w-3.5 h-3.5 text-red-500" />
            <span className="aws-status-text">Anomaly Indicators</span>
          </div>
          <span className={`display-row-state ${showAnomalyOverlay ? 'on' : ''}`}>
            {showAnomalyOverlay ? <Check className="w-3 h-3" /> : 'OFF'}
          </span>
        </div>

        <div className="display-row-divider" />

        <div className="display-row-label">
          <Filter className="w-3 h-3" /> Filter Status
        </div>
        <div className="status-filter-chip-row">
          {(['NORMAL', 'WARNING', 'ANOMALY'] as const).map((s) => (
            <button
              key={s}
              className={`status-filter-chip ${s.toLowerCase()} ${statusFilter === s ? 'active' : ''}`}
              onClick={() => onSetStatusFilter(statusFilter === s ? null : s)}
              title={`Show only ${s} stations`}
            >
              {s}
            </button>
          ))}
          {statusFilter && (
            <button className="status-filter-chip clear" onClick={() => onSetStatusFilter(null)} title="Clear filter">
              ALL
            </button>
          )}
        </div>
      </div>

      {/* Group 3: BASEMAP */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>BASEMAP</span>
        </div>
        <div className="basemap-toggle-row">
          <button
            className={`basemap-pill-btn ${basemap === 'satellite' ? 'active' : ''}`}
            onClick={() => onToggleBasemap('satellite')}
            title="Switch to Satellite Imagery"
          >
            <span className={`basemap-radio-indicator ${basemap === 'satellite' ? 'active' : ''}`} />
            <span>Satellite</span>
          </button>
          <button
            className={`basemap-pill-btn ${basemap === 'dark' ? 'active' : ''}`}
            onClick={() => onToggleBasemap('dark')}
            title="Switch to Standard Basemap"
          >
            <span className={`basemap-radio-indicator ${basemap === 'dark' ? 'active' : ''}`} />
            <span>Standard</span>
          </button>
        </div>
      </div>
    </aside>
  );
};
