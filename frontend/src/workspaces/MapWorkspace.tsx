import React, { useState, forwardRef, useMemo } from 'react';
import { SlidersHorizontal, Activity, Radio } from 'lucide-react';
import { AtherMap, AtherMapHandle } from '../map/AtherMap';
import { LayerControls } from '../components/LayerControls';
import { StationPreviewPanel } from '../components/StationPreviewPanel';
import { Station, WeatherLayerType, AnomaliesSummary } from '../types/weather';
import { Workspace } from '../types/workspace';
import { mapStatus, useLive } from '../services/live';
import {
  FreshnessCard, IncidentsSummaryCard, LiveEventFeed, NetworkStatusCard, SystemHealthCard, ThroughputCard,
} from '../components/live/LivePanels';
import { Card, SourceBadge } from '../components/live/LiveBits';

interface MapWorkspaceProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  selectedStation: Station | null;
  onSelectStation: (stationId: string) => void;
  onClosePreview: () => void;
  onViewStationDetails: (stationId: string) => void;
  onOpenIncident: (incidentId: string) => void;
  activeLayers: Record<WeatherLayerType, boolean>;
  onToggleLayer: (layer: WeatherLayerType) => void;
  basemap: 'dark' | 'satellite';
  onToggleBasemap: (mode: 'dark' | 'satellite') => void;
  showAnomalyOverlay: boolean;
  onToggleAnomalyOverlay: () => void;
  statusFilter: string | null;
  onSetStatusFilter: (status: string | null) => void;
  isActive: boolean;
  summary: AnomaliesSummary | null;
  onNavigate: (workspace: Workspace) => void;
}

/**
 * ATHER COMMAND CENTER — the operational dashboard.
 *
 * Station colours, counts, the event feed and the health cards are all
 * driven by the backend's continuous pipeline over SSE (services/live.tsx);
 * nothing here recomputes a detection or polls stations.
 */
export const MapWorkspace = forwardRef<AtherMapHandle, MapWorkspaceProps>(({
  stationsGeoJSON,
  selectedStation,
  onSelectStation,
  onClosePreview,
  onViewStationDetails,
  onOpenIncident,
  activeLayers,
  onToggleLayer,
  basemap,
  onToggleBasemap,
  showAnomalyOverlay,
  onToggleAnomalyOverlay,
  statusFilter,
  onSetStatusFilter,
  isActive,
  onNavigate
}, ref) => {
  const [isMapOptionsOpen, setIsMapOptionsOpen] = useState(false);
  const activeParamCount = ['temperature', 'pressure', 'humidity'].filter((k) => (activeLayers as any)[k]).length;
  const { stations, stationsVersion } = useLive();

  // Regional mean of the LIVE stations' latest observations — no fallback
  // numbers: when nothing is reporting, the card says so.
  const weatherSnapshot = useMemo(() => {
    let t = 0, tn = 0, p = 0, pn = 0, h = 0, hn = 0, sim = 0;
    stations.forEach((s) => {
      const v = s.values || {};
      if (typeof v.temperature === 'number') { t += v.temperature; tn++; }
      if (typeof v.pressure === 'number') { p += v.pressure; pn++; }
      if (typeof v.humidity === 'number' && v.humidity <= 100) { h += v.humidity; hn++; }
      if (s.simulated) sim++;
    });
    return {
      temp: tn ? (t / tn).toFixed(1) : null,
      pressure: pn ? Math.round(p / pn) : null,
      humidity: hn ? Math.round(h / hn) : null,
      n: tn,
      simulated: sim > 0,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsVersion]);

  return (
    <div className="dashboard-page-container">
      <section className="dashboard-upper-grid" aria-label="Main Monitoring Workspace">
        <div className="dashboard-map-card">
          <AtherMap
            ref={ref}
            stationsGeoJSON={stationsGeoJSON}
            selectedStationId={selectedStation?.id ?? null}
            onSelectStation={onSelectStation}
            activeLayers={activeLayers}
            basemap={basemap}
            onToggleBasemap={onToggleBasemap}
            showAnomalyOverlay={showAnomalyOverlay}
            isActive={isActive}
          />

          <button
            className={`map-options-trigger-btn ${isMapOptionsOpen ? 'active' : ''}`}
            onClick={() => setIsMapOptionsOpen((v) => !v)}
            title="Map Layers"
            aria-expanded={isMapOptionsOpen}
          >
            <SlidersHorizontal size={14} />
            <span>MAP LAYERS</span>
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

        <aside className="dashboard-sidebar-column" aria-label="Station and Network Intelligence">
          {selectedStation ? (
            <StationPreviewPanel
              station={selectedStation}
              onClose={onClosePreview}
              onViewDetails={onViewStationDetails}
            />
          ) : (
            <div className="lv-side-stack">
              <NetworkStatusCard
                statusFilter={null}
                onFilter={(s) => onSetStatusFilter(s ? mapStatus(s as any) : null)}
              />

              <Card
                title="Current weather"
                icon={<Activity size={14} />}
                right={weatherSnapshot.simulated ? <SourceBadge simulated /> : <span className="lv-muted">network mean</span>}
              >
                {weatherSnapshot.n === 0 ? (
                  <p className="lv-muted">No live station is reporting yet.</p>
                ) : (
                  <div className="weather-snapshot-grid">
                    <div className="weather-snapshot-item">
                      <div className="snapshot-label">Temperature</div>
                      <div className="snapshot-val">{weatherSnapshot.temp ?? '—'}°<span className="snapshot-unit">C</span></div>
                    </div>
                    <div className="weather-snapshot-item">
                      <div className="snapshot-label">Humidity</div>
                      <div className="snapshot-val">{weatherSnapshot.humidity ?? '—'}<span className="snapshot-unit">%</span></div>
                    </div>
                    <div className="weather-snapshot-item">
                      <div className="snapshot-label">Pressure</div>
                      <div className="snapshot-val">{weatherSnapshot.pressure ?? '—'}<span className="snapshot-unit">hPa</span></div>
                    </div>
                  </div>
                )}
              </Card>

              <Card
                className="lv-feed-card"
                title="Live event feed"
                icon={<Radio size={14} />}
                right={<button className="lv-link" onClick={() => onNavigate('anomalies')}>All incidents</button>}
              >
                <LiveEventFeed onSelectStation={onSelectStation} onOpenIncident={onOpenIncident} />
              </Card>
            </div>
          )}
        </aside>
      </section>

      <section className="dashboard-lower-grid" aria-label="Operational Metrics and Health">
        <IncidentsSummaryCard onOpen={() => onNavigate('anomalies')} />
        <FreshnessCard />
        <SystemHealthCard onOpen={() => onNavigate('system')} />
        <ThroughputCard />
      </section>
    </div>
  );
});
