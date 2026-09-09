import React, { useState, useEffect } from 'react';
import { AtherMap } from './map/AtherMap';
import { TopNav } from './components/TopNav';
import { LayerControls } from './components/LayerControls';
import { StationPanel } from './panels/StationPanel';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { fetchStationsGeoJSON, fetchStationDetails, fetchAnomaliesSummary } from './services/api';

export const App: React.FC = () => {
  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [summary, setSummary] = useState<AnomaliesSummary | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('dark');

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
      />

      {/* Weather Layer Controls Right Panel */}
      <LayerControls
        activeLayers={activeLayers}
        onToggleLayer={handleToggleLayer}
        isStationPanelOpen={Boolean(selectedStation)}
        basemap={basemap}
        onToggleBasemap={setBasemap}
      />

      {/* Main Full-World 2D Interactive Map */}
      <AtherMap
        stationsGeoJSON={stationsGeoJSON}
        selectedStationId={selectedStation?.id ?? null}
        onSelectStation={handleSelectStation}
        activeLayers={activeLayers}
        basemap={basemap}
        onToggleBasemap={setBasemap}
      />

      {/* Sliding Collapsible Station & Anomaly Details Panel */}
      <StationPanel
        station={selectedStation}
        onClose={() => setSelectedStation(null)}
      />
    </div>
  );
};
