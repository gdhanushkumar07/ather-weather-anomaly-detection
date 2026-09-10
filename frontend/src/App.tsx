import React, { useState, useEffect } from 'react';
import { AtherMap } from './map/AtherMap';
import { TopNav } from './components/TopNav';
import { LayerControls } from './components/LayerControls';
import { StationPanel } from './panels/StationPanel';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { fetchStationsGeoJSON, fetchStationDetails, fetchAnomaliesSummary } from './services/api';
import { findNearestStations, AWSNeighbor } from './aws/awsGeo';

export const App: React.FC = () => {
  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [summary, setSummary] = useState<AnomaliesSummary | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('dark');
  const [isGlobeMode, setIsGlobeMode] = useState<boolean>(false);
  const [neighbors, setNeighbors] = useState<AWSNeighbor[]>([]);

  const [activeLayers, setActiveLayers] = useState<Record<WeatherLayerType, boolean>>({
    stations: true,
    temperature: false,
    wind: false,
    pressure: false,
    humidity: false
  });

  // Fetch initial stations and summary
  useEffect(() => {
    loadStations();
    loadSummary();
  }, [statusFilter]);

  // Real nearest-3-neighbor computation (Haversine over actual station
  // coordinates already in stationsGeoJSON) -- single source of truth,
  // shared by the map's connection lines and the station panel below.
  useEffect(() => {
    if (!selectedStation || !stationsGeoJSON) {
      setNeighbors([]);
      return;
    }
    setNeighbors(
      findNearestStations(
        selectedStation.id,
        selectedStation.latitude,
        selectedStation.longitude,
        stationsGeoJSON.features,
        3
      )
    );
  }, [selectedStation?.id, selectedStation?.latitude, selectedStation?.longitude, stationsGeoJSON]);

  const loadStations = async () => {
    try {
      const geojson = await fetchStationsGeoJSON({
        status: statusFilter || undefined
      });
      setStationsGeoJSON(geojson);
    } catch (err) {
      console.error('Error loading stations', err);
    }
  };

  const loadSummary = async () => {
    try {
      const sum = await fetchAnomaliesSummary();
      setSummary(sum);
    } catch (err) {
      console.error('Error loading summary', err);
    }
  };

  const handleSelectStation = async (id: string) => {
    try {
      const stn = await fetchStationDetails(id);
      setSelectedStation(stn);
    } catch (err) {
      console.error('Error selecting station', err);
    }
  };

  const handleToggleLayer = (layer: WeatherLayerType) => {
    setActiveLayers((prev) => ({
      ...prev,
      [layer]: !prev[layer]
    }));
  };

  return (
    <div className="ather-app">
      {/* Top Navigation */}
      <TopNav
        summary={summary}
        onSelectStation={handleSelectStation}
        statusFilter={statusFilter}
        onSetStatusFilter={setStatusFilter}
        isGlobeMode={isGlobeMode}
        onToggleGlobeMode={() => setIsGlobeMode((prev) => !prev)}
      />

      {/* Weather Layer Controls Right Panel */}
      <LayerControls
        activeLayers={activeLayers}
        onToggleLayer={handleToggleLayer}
        isStationPanelOpen={Boolean(selectedStation)}
        basemap={basemap}
        onToggleBasemap={setBasemap}
        isGlobeMode={isGlobeMode}
        onToggleGlobeMode={() => setIsGlobeMode((prev) => !prev)}
      />

      {/* Main Full-World 2D/3D Interactive Map */}
      <AtherMap
        stationsGeoJSON={stationsGeoJSON}
        selectedStationId={selectedStation?.id ?? null}
        onSelectStation={handleSelectStation}
        activeLayers={activeLayers}
        basemap={basemap}
        onToggleBasemap={setBasemap}
        isGlobeMode={isGlobeMode}
        onToggleGlobeMode={() => setIsGlobeMode((prev) => !prev)}
        neighbors={neighbors}
      />

      {/* Sliding Collapsible Station & Anomaly Details Panel */}
      <StationPanel
        station={selectedStation}
        onClose={() => setSelectedStation(null)}
        neighbors={neighbors}
      />
    </div>
  );
};
export default App;

