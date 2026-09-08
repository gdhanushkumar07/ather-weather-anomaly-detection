import React from 'react';
import { Thermometer, Wind, Gauge, Droplets, Radio } from 'lucide-react';
import { WeatherLayerType } from '../types/weather';

interface LayerControlsProps {
  activeLayers: Record<WeatherLayerType, boolean>;
  onToggleLayer: (layer: WeatherLayerType) => void;
  isStationPanelOpen?: boolean;
}

export const LayerControls: React.FC<LayerControlsProps> = ({
  activeLayers,
  onToggleLayer,
  isStationPanelOpen = false
}) => {
  return (
    <aside className={`weather-controls-right ${isStationPanelOpen ? 'shifted' : ''}`}>
      {/* Dedicated AWS Station Marker Control Button */}
      <div
        className={`aws-station-toggle ${activeLayers.stations ? 'active' : ''}`}
        onClick={() => onToggleLayer('stations')}
        title="Toggle Global AWS Station Observation Markers"
      >
        <span className={`aws-status-dot ${activeLayers.stations ? 'active' : ''}`} />
        <span className="aws-status-text">
          {activeLayers.stations ? 'AWS MARKERS ON' : 'AWS MARKERS OFF'}
        </span>
        <Radio className="w-3.5 h-3.5 ml-auto" />
      </div>

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

      {/* Contextual Weather Inputs */}
      <div className="control-group-card">
        <div className="control-group-header">
          <span>CONTEXTUAL WEATHER</span>
        </div>

        <div
          className={`control-capsule ${activeLayers.wind ? 'active' : ''}`}
          onClick={() => onToggleLayer('wind')}
        >
          <div className="control-capsule-left">
            <span className={`radio-dot ${activeLayers.wind ? 'active' : ''}`} />
            <span>Wind Streamlines</span>
          </div>
          <Wind className="control-icon text-sky-400" />
        </div>
      </div>
    </aside>
  );
};
