import React from 'react';
import { Layers, Thermometer, Wind, Gauge, Droplets, MapPin, Check } from 'lucide-react';
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
        <Layers className="w-3.5 h-3.5 text-slate-400" />
      </div>

      <div
        className={`layer-item ${activeLayers.stations ? 'active' : ''}`}
        onClick={() => onToggleLayer('stations')}
      >
        <div className="layer-item-left">
          <MapPin className="w-4 h-4 text-sky-600" />
          <span>Stations</span>
        </div>
        <div className="layer-checkbox">
          {activeLayers.stations && <Check className="layer-checkbox-icon" />}
        </div>
      </div>

      <div
        className={`layer-item ${activeLayers.temperature ? 'active' : ''}`}
        onClick={() => onToggleLayer('temperature')}
      >
        <div className="layer-item-left">
          <Thermometer className="w-4 h-4 text-orange-500" />
          <span>Temperature</span>
        </div>
        <div className="layer-checkbox">
          {activeLayers.temperature && <Check className="layer-checkbox-icon" />}
        </div>
      </div>

      <div
        className={`layer-item ${activeLayers.wind ? 'active' : ''}`}
        onClick={() => onToggleLayer('wind')}
      >
        <div className="layer-item-left">
          <Wind className="w-4 h-4 text-cyan-600" />
          <span>Wind Flow</span>
        </div>
        <div className="layer-checkbox">
          {activeLayers.wind && <Check className="layer-checkbox-icon" />}
        </div>
      </div>

      <div
        className={`layer-item ${activeLayers.pressure ? 'active' : ''}`}
        onClick={() => onToggleLayer('pressure')}
      >
        <div className="layer-item-left">
          <Gauge className="w-4 h-4 text-indigo-500" />
          <span>Pressure</span>
        </div>
        <div className="layer-checkbox">
          {activeLayers.pressure && <Check className="layer-checkbox-icon" />}
        </div>
      </div>

      <div
        className={`layer-item ${activeLayers.humidity ? 'active' : ''}`}
        onClick={() => onToggleLayer('humidity')}
      >
        <div className="layer-item-left">
          <Droplets className="w-4 h-4 text-blue-500" />
          <span>Humidity</span>
        </div>
        <div className="layer-checkbox">
          {activeLayers.humidity && <Check className="layer-checkbox-icon" />}
        </div>
      </div>
    </aside>
  );
};
