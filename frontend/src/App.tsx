import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { TopNav } from './components/TopNav';
import { TestLabWorkspace } from './workspaces/TestLabWorkspace';
import { MapWorkspace, MapFilters, DEFAULT_MAP_FILTERS } from './workspaces/MapWorkspace';
import { OverviewWorkspace } from './workspaces/OverviewWorkspace';
import { StationWorkspace } from './workspaces/StationWorkspace';
import { InvestigationsWorkspace } from './workspaces/InvestigationsWorkspace';
import { SystemWorkspace } from './workspaces/SystemWorkspace';
import { AtherMapHandle, MapViewState } from './map/AtherMap';
import { Station, AnomaliesSummary, WeatherLayerType } from './types/weather';
import { Workspace } from './types/workspace';
import { fetchStationsGeoJSON, fetchStationDetails } from './services/api';
import { HomePage } from './pages/HomePage';
import { OverallStatus, useLive } from './services/live';
import { findNearestStations, AWSNeighbor } from './aws/awsGeo';

/** Browser path ⇄ workspace. Old paths keep working. */
function getWorkspaceFromPath(): Workspace {
  const path = window.location.pathname.toLowerCase();
  if (path === '/map' || path === '/dashboard') return 'map';
  if (path === '/overview' || path === '/health') return 'overview';
  if (path === '/investigations' || path === '/anomalies' || path === '/incidents') return 'anomalies';
  if (path === '/testlab' || path === '/test-lab') return 'testlab';
  if (path === '/station') return 'station';
  if (path === '/system') return 'system';
  return 'home';
}

function getPathForWorkspace(ws: Workspace): string {
  switch (ws) {
    case 'map': return '/map';
    case 'overview': return '/overview';
    case 'anomalies': return '/investigations';
    case 'testlab': return '/test-lab';
    case 'station': return '/station';
    case 'system': return '/system';
    default: return '/';
  }
}

/** Live sensor-trust status → map marker variant. Degraded (stale / missing
 *  data) is neutral grey, not amber: it is a data problem, not suspect evidence. */
function markerStatus(s: OverallStatus): string {
  return s === 'anomaly' ? 'ANOMALY' : s === 'suspect' ? 'WARNING' : s === 'degraded' ? 'OFFLINE' : 'NORMAL';
}

/**
 * ATHER application shell.
 *   Home (public) → Overview · Live Map · Investigations · Test Lab
 * Station detail is entered from the map/overview/investigations; System
 * from the live indicator. Shared state lives here once and is passed down.
 */
export const App: React.FC = () => {
  const [workspace, setWorkspace] = useState<Workspace>(getWorkspaceFromPath);
  const [stationsGeoJSON, setStationsGeoJSON] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [filters, setFilters] = useState<MapFilters>(DEFAULT_MAP_FILTERS);
  const [basemap, setBasemap] = useState<'dark' | 'satellite'>('satellite');
  const [isGlobeMode, setIsGlobeMode] = useState<boolean>(false);
  const [neighbors, setNeighbors] = useState<AWSNeighbor[]>([]);
  const [showAnomalyOverlay, setShowAnomalyOverlay] = useState(true);
  const [activeLayers, setActiveLayers] = useState<Record<WeatherLayerType, boolean>>({
    stations: true, temperature: false, wind: false, pressure: false, humidity: false,
  });
  const [openIncidentId, setOpenIncidentId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get('id')
  );

  useEffect(() => {
    const onPop = () => setWorkspace(getWorkspaceFromPath());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  useEffect(() => {
    document.body.classList.toggle('home-active', workspace === 'home');
  }, [workspace]);

  const changeWorkspace = useCallback((target: Workspace) => {
    const path = getPathForWorkspace(target);
    if (window.location.pathname !== path) window.history.pushState({ workspace: target }, '', path);
    setWorkspace(target);
    window.scrollTo({ top: 0 });
  }, []);

  // The map is never unmounted, so its camera survives workspace switches;
  // the view is captured before opening a station and restored on return.
  const mapRef = useRef<AtherMapHandle>(null);
  const savedMapViewRef = useRef<MapViewState | null>(null);

  useEffect(() => {
    fetchStationsGeoJSON().then(setStationsGeoJSON).catch((e) => console.error('stations', e));
  }, []);

  const { stations: liveStations, stationsVersion, counts, warmingIds } = useLive();
  // The public homepage shows the same live counts as the Overview.
  const summary: AnomaliesSummary | null = counts ? {
    totalStations: counts.live_stations ?? 0, normalCount: counts.nominal ?? 0,
    warningCount: (counts.suspect ?? 0) + (counts.degraded ?? 0), anomalyCount: counts.anomaly ?? 0,
    activeAnomalies: [], activeWarnings: [],
  } : null;

  const regions = useMemo(() => {
    const set = new Set<string>();
    stationsGeoJSON?.features.forEach((f) => {
      if (liveStations.has(String(f.properties?.id)) && f.properties?.region) set.add(String(f.properties.region));
    });
    return [...set].sort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsGeoJSON, stationsVersion]);

  const mapGeoJSON = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!stationsGeoJSON) return null;
    const features = [];
    for (const f of stationsGeoJSON.features) {
      const id = String(f.properties?.id ?? '');
      const live = liveStations.get(id);
      const warming = !live && warmingIds.has(id);
      // The live view shows the whole simulated network: stations still in
      // start-up warm-up are drawn neutral ("not live yet"), never hidden.
      if (filters.network === 'live' && !live && !warming) continue;
      if (filters.region !== 'all' && f.properties?.region !== filters.region) continue;
      if (filters.severity !== 'all' && live?.overall_status !== filters.severity) continue;
      if (filters.finding !== 'all' && live?.interpretation !== filters.finding) continue;
      if (!live) {
        // Catalogue-only station: shown neutral — it is not evaluated live.
        features.push({ ...f, properties: { ...f.properties, status: 'OFFLINE', hasAnomaly: 0, liveStatus: null, warming: warming ? 1 : 0 } });
        continue;
      }
      const v = live.values || {};
      features.push({
        ...f,
        properties: {
          ...f.properties,
          status: markerStatus(live.overall_status),
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
      });
    }
    return { ...stationsGeoJSON, features };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsGeoJSON, stationsVersion, filters, warmingIds]);

  useEffect(() => {
    if (!selectedStation || !stationsGeoJSON) { setNeighbors([]); return; }
    setNeighbors(findNearestStations(selectedStation.id, selectedStation.latitude, selectedStation.longitude, stationsGeoJSON.features, 3));
  }, [selectedStation?.id, selectedStation?.latitude, selectedStation?.longitude, stationsGeoJSON]);

  const selectOnMap = async (id: string) => {
    if (workspace !== 'map') changeWorkspace('map');
    try { setSelectedStation(await fetchStationDetails(id)); } catch (e) { console.error('select station', e); }
  };

  const openStation = async (id: string) => {
    const captured = mapRef.current?.getViewState();
    if (captured) savedMapViewRef.current = captured;
    try {
      setSelectedStation(await fetchStationDetails(id));
      changeWorkspace('station');
    } catch (e) { console.error('open station', e); }
  };

  const backToMap = () => {
    if (savedMapViewRef.current) {
      mapRef.current?.restoreViewState(savedMapViewRef.current);
      savedMapViewRef.current = null;
    }
    changeWorkspace('map');
  };

  const openIncident = (id: string) => { setOpenIncidentId(id); changeWorkspace('anomalies'); };

  const navigate = (target: Workspace) => changeWorkspace(target);

  // Temperature / pressure / humidity overlays are mutually exclusive.
  const PARAMETER_KEYS: WeatherLayerType[] = ['temperature', 'pressure', 'humidity'];
  const toggleLayer = (layer: WeatherLayerType) => {
    setActiveLayers((prev) => {
      if (PARAMETER_KEYS.includes(layer)) {
        const next = { ...prev };
        const on = !prev[layer];
        PARAMETER_KEYS.forEach((k) => { next[k] = false; });
        next[layer] = on;
        return next;
      }
      return { ...prev, [layer]: !prev[layer] };
    });
  };

  if (workspace === 'home') {
    return (
      <div className="ather-app workspace-home-active">
        <HomePage summary={summary} onLaunchPlatform={(target) => changeWorkspace(target === 'map' ? 'map' : 'overview')} />
      </div>
    );
  }

  const stationOptions = (stationsGeoJSON?.features || [])
    .map((f) => ({ id: String(f.properties?.id ?? ''), name: String(f.properties?.name ?? f.properties?.id ?? '') }))
    .filter((s) => s.id);

  return (
    <div className="ather-app">
      <TopNav activeWorkspace={workspace} onNavigate={navigate} onSelectStation={openStation} />
      <main className="ather-workspace-content">
        {/* The map stays mounted (hidden, not unmounted) to keep its camera. */}
        <div style={{ display: workspace === 'map' ? 'block' : 'none' }}>
          <MapWorkspace
            ref={mapRef}
            isActive={workspace === 'map'}
            stationsGeoJSON={mapGeoJSON}
            filters={filters}
            onFiltersChange={setFilters}
            regions={regions}
            liveCount={liveStations.size}
            warmingCount={[...warmingIds].filter((id) => !liveStations.has(id)).length}
            catalogueCount={stationsGeoJSON?.features.length ?? 0}
            selectedStation={selectedStation}
            onSelectStation={selectOnMap}
            onClosePreview={() => setSelectedStation(null)}
            onViewStationDetails={openStation}
            onOpenIncident={openIncident}
            activeLayers={activeLayers}
            onToggleLayer={toggleLayer}
            basemap={basemap}
            onToggleBasemap={setBasemap}
            showAnomalyOverlay={showAnomalyOverlay}
            onToggleAnomalyOverlay={() => setShowAnomalyOverlay((v) => !v)}
            isGlobeMode={isGlobeMode}
            onToggleGlobeMode={() => setIsGlobeMode((v) => !v)}
            neighbors={neighbors}
          />
        </div>

        {workspace === 'overview' && (
          <OverviewWorkspace stationsGeoJSON={stationsGeoJSON} onNavigate={navigate} onOpenStation={openStation} onOpenIncident={openIncident} />
        )}

        {workspace === 'station' && (selectedStation ? (
          <StationWorkspace station={selectedStation} onBack={backToMap} onOpenIncident={openIncident} onOpenStation={openStation} />
        ) : (
          <div className="lv-page"><div className="lv-empty">No station selected. <button className="lv-link" onClick={backToMap}>Open the live map</button></div></div>
        ))}

        {workspace === 'anomalies' && (
          <InvestigationsWorkspace openIncidentId={openIncidentId} onOpenIncident={setOpenIncidentId} onOpenStation={openStation} onShowOnMap={selectOnMap} />
        )}

        {workspace === 'system' && <SystemWorkspace />}

        {workspace === 'testlab' && (
          <TestLabWorkspace onClose={() => changeWorkspace('overview')} onOpenIncident={openIncident} onViewStation={openStation} stations={stationOptions} />
        )}
      </main>
    </div>
  );
};
export default App;
