import React, { useState, useEffect } from 'react';
import { AtherMap } from './map/AtherMap';
import { TopNav } from './components/TopNav';
import { LayerControls } from './components/LayerControls';
import { StationPanel } from './panels/StationPanel';
import { TestLabModal } from './components/TestLabModal';
import { NetworkOverview } from './components/NetworkOverview';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { fetchStationsGeoJSON, fetchStationDetails, fetchAnomaliesSummary } from './services/api';

export const App: React.FC = () => {
  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [summary, setSummary] = useState<AnomaliesSummary | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('dark');
  const [isTestLabOpen, setIsTestLabOpen] = useState(false);
  const [isOverviewOpen, setIsOverviewOpen] = useState(false);

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

  // Temperature / Pressure / Relative Humidity are mutually exclusive — the
  // "ATHER CORE INPUTS" panel selects ONE active spatial parameter at a time
  // (clicking the active one turns it off). Wind and the AWS marker toggle
  // remain independent boolean toggles, unchanged from existing behavior.
  const PARAMETER_KEYS: WeatherLayerType[] = ['temperature', 'pressure', 'humidity'];

  const handleToggleLayer = (layer: WeatherLayerType) => {
    setActiveLayers((prev) => {
      if (PARAMETER_KEYS.includes(layer)) {
        const turningOn = !prev[layer];
        const next = { ...prev };
        PARAMETER_KEYS.forEach((k) => { next[k] = false; });
        next[layer] = turningOn;
        return next;
      }
      return { ...prev, [layer]: !prev[layer] };
    });
  };

  return (
    <div className="ather-app">
      {/* Top Navigation */}
      <TopNav
        summary={summary}
        onSelectStation={handleSelectStation}
        statusFilter={statusFilter}
        onSetStatusFilter={setStatusFilter}
        onOpenTestLab={() => setIsTestLabOpen(true)}
        onToggleOverview={() => setIsOverviewOpen((prev) => !prev)}
        isOverviewOpen={isOverviewOpen}
      />

      {/* Collapsible Network Overview & Regional Weather Intelligence */}
      <NetworkOverview
        summary={summary}
        stationsGeoJSON={stationsGeoJSON}
        isOpen={isOverviewOpen}
        onToggle={() => setIsOverviewOpen((prev) => !prev)}
        onSelectStation={(id) => {
          handleSelectStation(id);
        }}
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

      {/* ATHER Diagnostic Test Lab — secondary workspace overlay (Phase 6) */}
      <TestLabModal
        isOpen={isTestLabOpen}
        onClose={() => setIsTestLabOpen(false)}
        stations={
          stationsGeoJSON?.features
            .map((f) => ({ id: String(f.properties?.id ?? ''), name: String(f.properties?.name ?? f.properties?.id ?? '') }))
            .filter((s) => s.id) ?? []
        }
      />
    </div>
  );
};
