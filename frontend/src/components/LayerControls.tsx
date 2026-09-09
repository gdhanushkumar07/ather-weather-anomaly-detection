import React from 'react';
import { Thermometer, Gauge, Droplets, Radio, Eye, X, ShieldAlert } from 'lucide-react';
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

      {/* Top Active Status Capsule (Matches Reference Image) */}
      <div className="active-mode-capsule">
        <Eye className="w-3.5 h-3.5 text-cyan-400" />
        <span className="active-mode-text">
          Active: <strong className="text-white">{basemap === 'satellite' ? 'Satellite (Clear)' : 'Dark Map (Base)'}</strong>
        </span>
      </div>

      {/* Core Meteorological Inputs */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>ATHER CORE INPUTS</span>
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

      {/* AWS Monitoring Section */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>AWS MONITORING</span>
        </div>
        <div
          className={`aws-station-toggle ${activeLayers.stations ? 'active' : ''}`}
          onClick={() => onToggleLayer('stations')}
          title="Toggle Global AWS Station Observation Markers"
        >
          <div className="aws-toggle-left">
            <span className={`aws-status-dot ${activeLayers.stations ? 'active' : ''}`} />
            <span className="aws-status-text">AWS MARKERS</span>
          </div>
          <div className="aws-toggle-right">
            <span className="aws-state-badge">{activeLayers.stations ? '(ON)' : '(OFF)'}</span>
            <Radio className="w-3.5 h-3.5" />
          </div>
        </div>
      </div>

      {/* Basemap Selection */}
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

      {/* Anomaly Overlay (Phase 5): independent of the AWS markers toggle —
          controls only the pulsing anomaly-alert halo. */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>ANOMALY OVERLAY</span>
        </div>
        <div
          className={`aws-station-toggle ${showAnomalyOverlay ? 'active' : ''}`}
          onClick={onToggleAnomalyOverlay}
          title="Toggle the pulsing anomaly-alert halo on anomalous stations"
        >
          <div className="aws-toggle-left">
            <span className={`aws-status-dot ${showAnomalyOverlay ? 'active' : ''}`} />
            <span className="aws-status-text">ANOMALY HALO</span>
          </div>
          <div className="aws-toggle-right">
            <span className="aws-state-badge">{showAnomalyOverlay ? '(ON)' : '(OFF)'}</span>
            <ShieldAlert className="w-3.5 h-3.5" />
          </div>
        </div>
      </div>

      {/* Station Status Filter — which stations are shown on the map at all. */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>STATION STATUS FILTER</span>
        </div>
        <div className="basemap-toggle-row" style={{ flexWrap: 'wrap', gap: '6px' }}>
          {(['NORMAL', 'WARNING', 'ANOMALY'] as const).map((s) => (
            <button
              key={s}
              className={`basemap-pill-btn ${statusFilter === s ? 'active' : ''}`}
              onClick={() => onSetStatusFilter(statusFilter === s ? null : s)}
              title={`Show only ${s} stations`}
            >
              <span className={`basemap-radio-indicator ${statusFilter === s ? 'active' : ''}`} />
              <span>{s}</span>
            </button>
          ))}
        </div>
        {statusFilter && (
          <button className="map-options-clear-filter-btn" onClick={() => onSetStatusFilter(null)}>
            Clear filter — show all stations
          </button>
        )}
      </div>
    </aside>
  );
};
