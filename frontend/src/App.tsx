import React, { useState, useEffect, useRef, useMemo } from 'react';
import { TopNav } from './components/TopNav';
import { StationPanel } from './panels/StationPanel';
import { TestLabWorkspace } from './workspaces/TestLabWorkspace';
import { NetworkOverview } from './components/NetworkOverview';
import { MapWorkspace } from './workspaces/MapWorkspace';
import { AtherMapHandle, MapViewState } from './map/AtherMap';
import { AnomaliesWorkspace } from './workspaces/AnomaliesWorkspace';
import { SensorHealthWorkspace } from './workspaces/SensorHealthWorkspace';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { Workspace } from './types/workspace';
import { fetchStationsGeoJSON, fetchStationDetails, fetchAnomaliesSummary, fetchActiveIncidentCounts } from './services/api';
import { HomePage } from './pages/HomePage';
import { SystemWorkspace } from './workspaces/SystemWorkspace';
import { mapStatus, useLive } from './services/live';

/**
 * Maps browser path to Workspace
 */
function getWorkspaceFromPath(): Workspace {
  const path = window.location.pathname.toLowerCase();
  if (path === '/map' || path === '/dashboard') return 'map';
  if (path === '/overview') return 'overview';
  if (path === '/anomalies' || path === '/incidents') return 'anomalies';
  if (path === '/health') return 'health';
  if (path === '/testlab' || path === '/test-lab') return 'testlab';
  if (path === '/station') return 'station';
  if (path === '/system') return 'system';
  // Default root '/' is the marketing & product homepage
  return 'home';
}

function getPathForWorkspace(ws: Workspace): string {
  switch (ws) {
    case 'home': return '/';
    case 'map': return '/map';
    case 'overview': return '/overview';
    case 'anomalies': return '/anomalies';
    case 'health': return '/health';
    case 'testlab': return '/test-lab';
    case 'station': return '/station';
    case 'system': return '/system';
    default: return '/';
  }
}

/**
 * ATHER application shell (UI architecture restructure).
 *
 * Exactly ONE workspace is the main content area at a time — Home, Overview, Map,
 * Station Intelligence, Anomalies, Sensor Health, or Test Lab. All shared
 * state (stations, summary, selection, map layer state) lives here, once,
 * and is passed down — no workspace recomputes or refetches what another
 * workspace already has (Phase 31: single source of truth).
 */
export const App: React.FC = () => {
  const [workspace, setWorkspace] = useState<Workspace>(getWorkspaceFromPath);

  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [summary, setSummary] = useState<AnomaliesSummary | null>(null);
  // Real, persisted incident counts (Phase 24: "ANOMALIES 190" must be
  // audited — this is unique ACTIVE INCIDENTS, distinct from summary's raw
  // per-station status counts, and labeled accordingly wherever it is shown).
  const [activeIncidentCounts, setActiveIncidentCounts] = useState<Record<string, number> | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  // Epoch ms of the last successful summary refresh — surfaced in the nav so
  // the LIVE badge is backed by an actual, visible data age.
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('satellite');
  const [showAnomalyOverlay, setShowAnomalyOverlay] = useState(true);

  const [activeLayers, setActiveLayers] = useState<Record<WeatherLayerType, boolean>>({
    stations: true,
    temperature: false,
    wind: false,
    pressure: false,
    humidity: false
  });

  // Synchronize browser history with workspace
  useEffect(() => {
    const onPopState = () => {
      setWorkspace(getWorkspaceFromPath());
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  // Set body class for scrolling behavior
  useEffect(() => {
    if (workspace === 'home') {
      document.body.classList.add('home-active');
    } else {
      document.body.classList.remove('home-active');
    }
  }, [workspace]);

  const changeWorkspace = (target: Workspace) => {
    const path = getPathForWorkspace(target);
    if (window.location.pathname !== path) {
      window.history.pushState({ workspace: target }, '', path);
    }
    setWorkspace(target);
    if (target === 'home') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  // Map view-state persistence: the map itself is never unmounted, so center/zoom/bearing/pitch
  // survive workspace switches on their own. mapRef gives imperative access to capture
  // the view right before navigating to full station details, and restore it on "Back to Map".
  const mapRef = useRef<AtherMapHandle>(null);
  const savedMapViewRef = useRef<MapViewState | null>(null);

  // Incident deep link (/incidents?id=INC-...) — opened from the live feed.
  const [openIncidentId, setOpenIncidentId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get('id')
  );

  // The station CATALOGUE is loaded once; live status is merged in below from
  // the SSE-driven store. Filtering is client-side — no refetch per filter.
  useEffect(() => {
    loadStations();
    loadSummary();
    loadActiveIncidentCounts();
  }, []);

  const { stations: liveStations, stationsVersion, incidentCounts: liveIncidentCounts } = useLive();
  useEffect(() => {
    if (liveIncidentCounts) setActiveIncidentCounts(liveIncidentCounts);
  }, [liveIncidentCounts]);

  const mapGeoJSON = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!stationsGeoJSON) return null;
    const features = stationsGeoJSON.features
      .map((f) => {
        const id = String(f.properties?.id ?? '');
        const live = liveStations.get(id);
        if (!live) return f;
        const v = live.values || {};
        return {
          ...f,
          properties: {
            ...f.properties,
            status: mapStatus(live.overall_status),
            liveStatus: live.overall_status,
            interpretation: live.interpretation,
            hasAnomaly: live.overall_status === 'anomaly' ? 1 : 0,
            severity: live.severity || 'NONE',
            temperature: typeof v.temperature === 'number' && v.temperature > -45 && v.temperature < 60 ? v.temperature : null,
            humidity: typeof v.humidity === 'number' && v.humidity >= 0 && v.humidity <= 100 ? v.humidity : null,
            pressure: typeof v.pressure === 'number' && v.pressure > 850 && v.pressure < 1090 ? v.pressure : null,
            windSpeed: v.wind_speed ?? f.properties?.windSpeed,
            source: live.source,
            timestamp: live.last_observed_at,
          },
        };
      })
      .filter((f) => !statusFilter || f.properties?.status === statusFilter);
    return { ...stationsGeoJSON, features };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsGeoJSON, stationsVersion, statusFilter]);

  const loadActiveIncidentCounts = async () => {
    try {
      const counts = await fetchActiveIncidentCounts();
      setActiveIncidentCounts(counts);
    } catch (err) {
      console.error('Error loading active incident counts', err);
    }
  };

  const loadStations = async () => {
    try {
      const geojson = await fetchStationsGeoJSON();
      setStationsGeoJSON(geojson);
    } catch (err) {
      console.error('Error loading stations', err);
    }
  };

  const loadSummary = async () => {
    try {
      const sum = await fetchAnomaliesSummary();
      setSummary(sum);
      setLastUpdatedAt(Date.now());
    } catch (err) {
      console.error('Error loading summary', err);
    }
  };

  // Selecting a station (map click, search, alert click):
  // Keeps the map visible, centers/highlights on map, and opens the compact Station Preview Panel!
  const handleSelectStation = async (id: string) => {
    if (workspace !== 'map') {
      changeWorkspace('map');
    }
    try {
      const stn = await fetchStationDetails(id);
      setSelectedStation(stn);
    } catch (err) {
      console.error('Error selecting station', err);
    }
  };

  // Level 3 Progressive Disclosure: Only called when the user explicitly clicks
  // [ VIEW DETAILS ] in the Station Preview Panel.
  const handleOpenStationDetails = async (id: string) => {
    const captured = mapRef.current?.getViewState();
    if (captured) savedMapViewRef.current = captured;

    try {
      const stn = await fetchStationDetails(id);
      setSelectedStation(stn);
      changeWorkspace('station');
    } catch (err) {
      console.error('Error opening station details', err);
    }
  };

  const handleBackToMap = () => {
    if (savedMapViewRef.current) {
      mapRef.current?.restoreViewState(savedMapViewRef.current);
      savedMapViewRef.current = null;
    }
    changeWorkspace('map');
  };

  const handleNavigate = (target: Workspace) => {
    if (target !== 'anomalies') setOpenIncidentId(null);
    changeWorkspace(target);
  };

  const handleOpenIncident = (incidentId: string) => {
    setOpenIncidentId(incidentId);
    changeWorkspace('anomalies');
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
    <div className={`ather-app ${workspace === 'home' ? 'workspace-home-active' : ''}`}>
      {workspace === 'home' ? (
        <HomePage
          summary={summary}
          onLaunchPlatform={(target) => changeWorkspace(target || 'map')}
        />
      ) : (
        <>
          <TopNav
            summary={summary}
            activeIncidentCounts={activeIncidentCounts}
            onSelectStation={handleSelectStation}
            activeWorkspace={workspace}
            onNavigate={handleNavigate}
            lastUpdatedAt={lastUpdatedAt}
          />

          <main className="ather-workspace-content">
            {/* The map is ALWAYS mounted, never conditionally rendered — hidden
                via CSS instead of being unmounted (Phase 9 of the map-state-
                persistence fix). AtherMap.tsx creates its maplibregl.Map
                instance exactly once (empty effect dependency array); as long
                as this component tree never unmounts, that instance — and
                therefore its center/zoom/bearing/pitch — survives every
                workspace switch with zero state serialization needed. Only
                React-level state (basemap, activeLayers, filters), which
                already lives in App.tsx and was never the problem, is passed
                down as props. */}
            <div className="map-workspace-keepalive" style={{ display: workspace === 'map' ? 'block' : 'none' }}>
              <MapWorkspace
                ref={mapRef}
                isActive={workspace === 'map'}
                stationsGeoJSON={mapGeoJSON}
                selectedStation={selectedStation}
                onSelectStation={handleSelectStation}
                onClosePreview={() => setSelectedStation(null)}
                onViewStationDetails={handleOpenStationDetails}
                onOpenIncident={handleOpenIncident}
                activeLayers={activeLayers}
                onToggleLayer={handleToggleLayer}
                basemap={basemap}
                onToggleBasemap={setBasemap}
                showAnomalyOverlay={showAnomalyOverlay}
                onToggleAnomalyOverlay={() => setShowAnomalyOverlay((v) => !v)}
                statusFilter={statusFilter}
                onSetStatusFilter={setStatusFilter}
                summary={summary}
                onNavigate={handleNavigate}
              />
            </div>

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

        {workspace === 'station' && (
          selectedStation ? (
            <StationPanel
              variant="page"
              station={selectedStation}
              onClose={handleBackToMap}
              onOpenIncident={handleOpenIncident}
              onSelectStation={handleOpenStationDetails}
            />
          ) : (
            <div className="workspace-empty-redirect">
              <p>No station selected.</p>
              <button className="quick-action-btn" onClick={handleBackToMap}>BACK TO MAP</button>
            </div>
          )
        )}

        {workspace === 'anomalies' && (
          <AnomaliesWorkspace
            summary={summary}
            activeIncidentCounts={activeIncidentCounts}
            onViewStation={handleOpenStationDetails}
            openIncidentId={openIncidentId}
            onOpenIncident={setOpenIncidentId}
          />
        )}

        {workspace === 'health' && (
          <SensorHealthWorkspace summary={summary} onViewStation={handleSelectStation} />
        )}

        {workspace === 'system' && <SystemWorkspace />}

        {workspace === 'testlab' && (
          <TestLabWorkspace
            onClose={handleBackToMap}
            onOpenIncident={handleOpenIncident}
            onViewStation={handleOpenStationDetails}
            stations={
              stationsGeoJSON?.features
                .map((f) => ({ id: String(f.properties?.id ?? ''), name: String(f.properties?.name ?? f.properties?.id ?? '') }))
                .filter((s) => s.id) ?? []
            }
          />
        )}
      </main>
    </>
  )}
</div>
);
};
