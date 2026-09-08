import React from 'react';
import { Thermometer, Gauge, Droplets, Radio, Moon, Satellite } from 'lucide-react';
import { WeatherLayerType } from '../types/weather';

interface LayerControlsProps {
  activeLayers: Record<WeatherLayerType, boolean>;
  onToggleLayer: (layer: WeatherLayerType) => void;
  isStationPanelOpen?: boolean;
  basemap: 'dark' | 'satellite';
  onToggleBasemap: (mode: 'dark' | 'satellite') => void;
}

export const LayerControls: React.FC<LayerControlsProps> = ({
  activeLayers,
  onToggleLayer,
  isStationPanelOpen = false,
  basemap,
  onToggleBasemap
}) => {
  return (
    <aside className={`weather-controls-right ${isStationPanelOpen ? 'shifted' : ''}`}>
      {/* Core Meteorological Inputs */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>ATHER CORE INPUTS</span>
        </div>

        <div
          className={`control-capsule ${activeLayers.temperature ? 'active' : ''}`}
          onClick={() => onToggleLayer('temperature')}
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.temperature ? 'active' : ''}`} />
            <span>Temperature</span>
          </div>
          <Thermometer className="control-icon text-amber-400" />
        </div>

        <div
          className={`control-capsule ${activeLayers.pressure ? 'active' : ''}`}
          onClick={() => onToggleLayer('pressure')}
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.pressure ? 'active' : ''}`} />
            <span>Pressure</span>
          </div>
          <Gauge className="control-icon text-indigo-400" />
        </div>

        <div
          className={`control-capsule ${activeLayers.humidity ? 'active' : ''}`}
          onClick={() => onToggleLayer('humidity')}
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.humidity ? 'active' : ''}`} />
            <span>Relative Humidity</span>
          </div>
          <Droplets className="control-icon text-cyan-400" />
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
            <span className="aws-state-badge">{activeLayers.stations ? 'ON' : 'OFF'}</span>
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
    </aside>
  );
};
