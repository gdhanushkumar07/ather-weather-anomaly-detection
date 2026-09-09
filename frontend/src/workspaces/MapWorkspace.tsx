import React, { useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { AtherMap } from '../map/AtherMap';
import { LayerControls } from '../components/LayerControls';
import { Station, WeatherLayerType } from '../types/weather';

interface MapWorkspaceProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  selectedStationId: string | null;
  onSelectStation: (stationId: string) => void;
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
 * MAP — clean, dedicated workspace (UI architecture restructure, Phase 4).
 * The map fills nearly the entire content area. Everything that used to be
 * a permanent floating panel (weather layers, basemap, anomaly overlay,
 * status filter) now lives behind a single compact "Map Options" trigger,
 * closed by default.
 */
export const MapWorkspace: React.FC<MapWorkspaceProps> = ({
  stationsGeoJSON,
  selectedStationId,
  onSelectStation,
  activeLayers,
  onToggleLayer,
  basemap,
  onToggleBasemap,
  showAnomalyOverlay,
  onToggleAnomalyOverlay,
  statusFilter,
  onSetStatusFilter
}) => {
  const [isMapOptionsOpen, setIsMapOptionsOpen] = useState(false);
  const activeParamCount = ['temperature', 'pressure', 'humidity'].filter((k) => (activeLayers as any)[k]).length;

  return (
    <div className="map-workspace">
      <AtherMap
        stationsGeoJSON={stationsGeoJSON}
        selectedStationId={selectedStationId}
        onSelectStation={onSelectStation}
        activeLayers={activeLayers}
        basemap={basemap}
        onToggleBasemap={onToggleBasemap}
        showAnomalyOverlay={showAnomalyOverlay}
      />

      {/* Small, always-visible trigger — everything else is on-demand. */}
      <button
        className={`map-options-trigger-btn ${isMapOptionsOpen ? 'active' : ''}`}
        onClick={() => setIsMapOptionsOpen((v) => !v)}
        title="Map Options"
      >
        <SlidersHorizontal className="w-3.5 h-3.5" />
        <span>Map Options</span>
        {activeParamCount > 0 && <span className="nav-badge-count anomaly">{activeParamCount}</span>}
      </button>

      <LayerControls
        isOpen={isMapOptionsOpen}
        onClose={() => setIsMapOptionsOpen(false)}
        activeLayers={activeLayers}
        onToggleLayer={onToggleLayer}
        basemap={basemap}
        onToggleBasemap={onToggleBasemap}
        showAnomalyOverlay={showAnomalyOverlay}
        onToggleAnomalyOverlay={onToggleAnomalyOverlay}
        statusFilter={statusFilter}
        onSetStatusFilter={onSetStatusFilter}
      />
    </div>
  );
};
