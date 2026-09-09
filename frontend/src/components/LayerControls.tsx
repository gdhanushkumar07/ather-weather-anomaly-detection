import React from 'react';
import { Thermometer, Gauge, Droplets, Radio, X, ShieldAlert, Filter } from 'lucide-react';
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

/**
 * MAP OPTIONS popover (UI architecture restructure, Phase 5). This used to
 * be a permanent floating panel sitting on top of the map at all times —
 * that is exactly the "map as a dumping ground" problem the restructure
 * targets. It is now a compact, on-demand popover: closed by default,
 * opened only via the small "Map Options" trigger in the Map workspace,
 * and closable. All existing toggle logic/markup below is unchanged.
 */
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
    <aside className="weather-controls-right map-options-popover">
      <div className="map-options-popover-header">
        <span className="map-options-popover-title">MAP OPTIONS</span>
        <button className="map-options-close-btn" onClick={onClose} title="Close Map Options">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Group 1: Map Layers — the three parameter visualizations (mutually exclusive). */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>MAP LAYERS</span>
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
            {activeLayers.temperature && <span className="active-tag-mini">ACTIVE</span>}
            <div className="circle-icon-badge temp-gradient-badge">
              <Thermometer className="w-3 h-3 text-white" />
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
            {activeLayers.pressure && <span className="active-tag-mini">ACTIVE</span>}
            <div className="circle-icon-badge pressure-gradient-badge">
              <Gauge className="w-3 h-3 text-white" />
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
            {activeLayers.humidity && <span className="active-tag-mini">ACTIVE</span>}
            <div className="circle-icon-badge humidity-gradient-badge">
              <Droplets className="w-3 h-3 text-white" />
            </div>
          </div>
        </div>
      </div>

      {/* Group 2: Display — everything controlling what's drawn on top of the
          basemap (markers, anomaly halo, status filter), consolidated into
          one compact group instead of three separate cards. */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>DISPLAY</span>
        </div>

        <div
          className={`display-row-toggle ${activeLayers.stations ? 'active' : ''}`}
          onClick={() => onToggleLayer('stations')}
          title="Toggle Global AWS Station Observation Markers"
        >
          <div className="aws-toggle-left">
            <Radio className="w-3.5 h-3.5" />
            <span className="aws-status-text">AWS Markers</span>
          </div>
          <span className={`display-row-state ${activeLayers.stations ? 'on' : ''}`}>{activeLayers.stations ? 'ON' : 'OFF'}</span>
        </div>

        <div
          className={`display-row-toggle ${showAnomalyOverlay ? 'active' : ''}`}
          onClick={onToggleAnomalyOverlay}
          title="Toggle the pulsing anomaly-alert halo on anomalous stations"
        >
          <div className="aws-toggle-left">
            <ShieldAlert className="w-3.5 h-3.5" />
            <span className="aws-status-text">Anomaly Halo</span>
          </div>
          <span className={`display-row-state ${showAnomalyOverlay ? 'on' : ''}`}>{showAnomalyOverlay ? 'ON' : 'OFF'}</span>
        </div>

        <div className="display-row-divider" />

        <div className="display-row-label">
          <Filter className="w-3 h-3" /> Station status
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

      {/* Group 3: Basemap */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>BASEMAP</span>
        </div>
        <div className="basemap-toggle-row">
          <button
            className={`basemap-pill-btn ${basemap === 'dark' ? 'active' : ''}`}
            onClick={() => onToggleBasemap('dark')}
            title="Switch to ATHER Dark Map"
          >
            <span className={`basemap-radio-indicator ${basemap === 'dark' ? 'active' : ''}`} />
            <span>DARK MAP</span>
          </button>
          <button
            className={`basemap-pill-btn ${basemap === 'satellite' ? 'active' : ''}`}
            onClick={() => onToggleBasemap('satellite')}
            title="Switch to Satellite Imagery"
          >
            <span className={`basemap-radio-indicator ${basemap === 'satellite' ? 'active' : ''}`} />
            <span>SATELLITE</span>
          </button>
        </div>
      </div>
    </aside>
  );
};
