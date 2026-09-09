import React, { useState, useEffect } from 'react';
import { TopNav } from './components/TopNav';
import { StationPanel } from './panels/StationPanel';
import { TestLabModal } from './components/TestLabModal';
import { NetworkOverview } from './components/NetworkOverview';
import { MapWorkspace } from './workspaces/MapWorkspace';
import { AnomaliesWorkspace } from './workspaces/AnomaliesWorkspace';
import { SensorHealthWorkspace } from './workspaces/SensorHealthWorkspace';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { Workspace } from './types/workspace';
import { fetchStationsGeoJSON, fetchStationDetails, fetchAnomaliesSummary } from './services/api';

/**
 * ATHER application shell (UI architecture restructure).
 *
 * Exactly ONE workspace is the main content area at a time — Overview, Map,
 * Station Intelligence, Anomalies, Sensor Health, or Test Lab. All shared
 * state (stations, summary, selection, map layer state) lives here, once,
 * and is passed down — no workspace recomputes or refetches what another
 * workspace already has (Phase 31: single source of truth).
 */
export const App: React.FC = () => {
  const [workspace, setWorkspace] = useState<Workspace>('map');

  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [summary, setSummary] = useState<AnomaliesSummary | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('dark');
  const [showAnomalyOverlay, setShowAnomalyOverlay] = useState(true);

  const [activeLayers, setActiveLayers] = useState<Record<WeatherLayerType, boolean>>({
    stations: true,
    temperature: false,
    wind: false,
    pressure: false,
    humidity: false
  });

  // Fetch initial stations and summary — shared across every workspace.
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

  // Selecting a station (map click, search, anomaly card, health card) always
  // opens the Station Intelligence workspace — never another floating card
  // stacked on top of whatever workspace was active (Phase 7).
  const handleSelectStation = async (id: string) => {
    try {
      const stn = await fetchStationDetails(id);
      setSelectedStation(stn);
      setWorkspace('station');
    } catch (err) {
      console.error('Error selecting station', err);
    }
  };

  const handleBackToMap = () => {
    setWorkspace('map');
  };

  const handleNavigate = (target: Workspace) => {
    setWorkspace(target);
  };

  // Temperature / Pressure / Relative Humidity are mutually exclusive — the
  // Map Options "core inputs" selects ONE active spatial parameter at a time
  // (clicking the active one turns it off). Wind and the AWS marker toggle
  // remain independent boolean toggles.
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
      <TopNav
        summary={summary}
        onSelectStation={handleSelectStation}
        activeWorkspace={workspace}
        onNavigate={handleNavigate}
      />

      <main className="ather-workspace-content">
        {workspace === 'overview' && (
          <NetworkOverview
            variant="page"
            summary={summary}
            stationsGeoJSON={stationsGeoJSON}
            isOpen={true}
            onToggle={() => {}}
            onSelectStation={handleSelectStation}
            onNavigate={handleNavigate}
          />
        )}

        {workspace === 'map' && (
          <MapWorkspace
            stationsGeoJSON={stationsGeoJSON}
            selectedStationId={selectedStation?.id ?? null}
            onSelectStation={handleSelectStation}
            activeLayers={activeLayers}
            onToggleLayer={handleToggleLayer}
            basemap={basemap}
            onToggleBasemap={setBasemap}
            showAnomalyOverlay={showAnomalyOverlay}
            onToggleAnomalyOverlay={() => setShowAnomalyOverlay((v) => !v)}
            statusFilter={statusFilter}
            onSetStatusFilter={setStatusFilter}
          />
        )}

        {workspace === 'station' && (
          selectedStation ? (
            <StationPanel
              variant="page"
              station={selectedStation}
              onClose={handleBackToMap}
            />
          ) : (
            <div className="workspace-empty-redirect">
              <p>No station selected.</p>
              <button className="quick-action-btn" onClick={handleBackToMap}>BACK TO MAP</button>
            </div>
          )
        )}

        {workspace === 'anomalies' && (
          <AnomaliesWorkspace summary={summary} onViewStation={handleSelectStation} />
        )}

        {workspace === 'health' && (
          <SensorHealthWorkspace summary={summary} onViewStation={handleSelectStation} />
        )}

        {workspace === 'testlab' && (
          <TestLabModal
            variant="page"
            isOpen={true}
            onClose={handleBackToMap}
            stations={
              stationsGeoJSON?.features
                .map((f) => ({ id: String(f.properties?.id ?? ''), name: String(f.properties?.name ?? f.properties?.id ?? '') }))
                .filter((s) => s.id) ?? []
            }
          />
        )}
      </main>
    </div>
  );
};
