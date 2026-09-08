import React from 'react';
import { Layers, Thermometer, Wind, Gauge, Droplets, MapPin } from 'lucide-react';
import { WeatherLayerType } from '../types/weather';

interface LayerControlsProps {
  activeLayers: Record<WeatherLayerType, boolean>;
  onToggleLayer: (layer: WeatherLayerType) => void;
}

export const LayerControls: React.FC<LayerControlsProps> = ({
  activeLayers,
  onToggleLayer
}) => {
  return (
    <aside className="layer-controls-panel">
      <div className="panel-title">
        <span>Weather Layers</span>
        <Layers className="w-3.5 h-3.5" />
      </div>

      <div
        className={`layer-item ${activeLayers.stations ? 'active' : ''}`}
        onClick={() => onToggleLayer('stations')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <MapPin className="w-4 h-4" style={{ color: '#0284c7' }} />
          <span>Stations</span>
        </div>
        <input
          type="checkbox"
          checked={activeLayers.stations}
          onChange={() => {}}
          tabIndex={-1}
        />
      </div>

      <div
        className={`layer-item ${activeLayers.temperature ? 'active' : ''}`}
        onClick={() => onToggleLayer('temperature')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Thermometer className="w-4 h-4" style={{ color: '#f97316' }} />
          <span>Temperature</span>
        </div>
        <input
          type="checkbox"
          checked={activeLayers.temperature}
          onChange={() => {}}
          tabIndex={-1}
        />
      </div>

      <div
        className={`layer-item ${activeLayers.wind ? 'active' : ''}`}
        onClick={() => onToggleLayer('wind')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Wind className="w-4 h-4" style={{ color: '#06b6d4' }} />
          <span>Wind Flow</span>
        </div>
        <input
          type="checkbox"
          checked={activeLayers.wind}
          onChange={() => {}}
          tabIndex={-1}
        />
      </div>

      <div
        className={`layer-item ${activeLayers.pressure ? 'active' : ''}`}
        onClick={() => onToggleLayer('pressure')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Gauge className="w-4 h-4" style={{ color: '#6366f1' }} />
          <span>Pressure</span>
        </div>
        <input
          type="checkbox"
          checked={activeLayers.pressure}
          onChange={() => {}}
          tabIndex={-1}
        />
      </div>

      <div
        className={`layer-item ${activeLayers.humidity ? 'active' : ''}`}
        onClick={() => onToggleLayer('humidity')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Droplets className="w-4 h-4" style={{ color: '#3b82f6' }} />
          <span>Humidity</span>
        </div>
        <input
          type="checkbox"
          checked={activeLayers.humidity}
          onChange={() => {}}
          tabIndex={-1}
        />
      </div>
    </aside>
  );
};
