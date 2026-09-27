import React, { forwardRef, useMemo, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { AtherMap, AtherMapHandle } from '../map/AtherMap';
import { LayerControls } from '../components/LayerControls';
import { StationPreviewPanel } from '../components/StationPreviewPanel';
import { Station, WeatherLayerType } from '../types/weather';
import { formatAge, INTERPRETATION_LABEL } from '../services/live';
import { Empty, StatusPill } from '../components/live/LiveBits';
import { AWSNeighbor } from '../aws/awsGeo';

export interface MapFilters {
  network: 'live' | 'all';
  severity: 'all' | 'anomaly' | 'suspect' | 'degraded' | 'nominal';
  finding: 'all' | 'likely_sensor_fault' | 'likely_weather_event' | 'communication_issue' | 'uncertain';
  region: string;
}

export const DEFAULT_MAP_FILTERS: MapFilters = { network: 'live', severity: 'all', finding: 'all', region: 'all' };

interface MapWorkspaceProps {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  filters: MapFilters;
  onFiltersChange: (f: MapFilters) => void;
  regions: string[];
  liveCount: number;
  warmingCount?: number;
  catalogueCount: number;
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
  isGlobeMode?: boolean;
  onToggleGlobeMode?: () => void;
  neighbors?: AWSNeighbor[];
  isActive: boolean;
}

const SEVERITY: [MapFilters['severity'], string][] = [
  ['all', 'All'], ['anomaly', 'Critical'], ['suspect', 'Warning'], ['degraded', 'Degraded'], ['nominal', 'Healthy'],
];
const FINDING: [MapFilters['finding'], string][] = [
  ['all', 'Any finding'], ['likely_sensor_fault', 'Sensor fault'], ['likely_weather_event', 'Weather event'],
  ['communication_issue', 'Communication'], ['uncertain', 'Uncertain'],
];
const RANK: Record<string, number> = { anomaly: 0, suspect: 1, degraded: 2, nominal: 3 };

/**
 * LIVE MAP — "Where is something happening?"
 * The map shows the pipeline's live state per station; filters narrow it;
 * selecting a station opens its quick view, then the full station page.
 */
export const MapWorkspace = forwardRef<AtherMapHandle, MapWorkspaceProps>(({
  stationsGeoJSON, filters, onFiltersChange, regions, liveCount, warmingCount = 0, catalogueCount,
  selectedStation, onSelectStation, onClosePreview, onViewStationDetails,
  activeLayers, onToggleLayer, basemap, onToggleBasemap, showAnomalyOverlay, onToggleAnomalyOverlay,
  isGlobeMode = false, onToggleGlobeMode, neighbors = [], isActive,
}, ref) => {
  const [layersOpen, setLayersOpen] = useState(false);
  const set = (patch: Partial<MapFilters>) => onFiltersChange({ ...filters, ...patch });

  const attention = useMemo(() => {
    const rows = (stationsGeoJSON?.features || [])
      .map((f) => f.properties || {})
      .filter((p) => p.liveStatus && p.liveStatus !== 'nominal');
    rows.sort((a, b) => (RANK[a.liveStatus] ?? 9) - (RANK[b.liveStatus] ?? 9));
    return rows;
  }, [stationsGeoJSON]);

  const shown = stationsGeoJSON?.features.length ?? 0;
  const filtered = filters.severity !== 'all' || filters.finding !== 'all' || filters.region !== 'all';

  return (
    <div className="lv-page" style={{ maxWidth: 'none', paddingTop: 16, gap: 12 }}>
      <div className="lv-spread" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div className="a-filters">
          <span className="a-filter-label">Network</span>
          <div className="a-filter-group">
            <button className={filters.network === 'live' ? 'active' : ''} onClick={() => set({ network: 'live' })}
              title={warmingCount ? `${warmingCount} simulated stations are still warming up (history being processed) and join the live feed shortly` : undefined}>
              Live AWS · {liveCount}{warmingCount ? ` + ${warmingCount} warming up` : ''}</button>
            <button className={filters.network === 'all' ? 'active' : ''} onClick={() => set({ network: 'all' })}
              title="Adds catalogue stations that are not monitored live (static snapshot)">All catalogue · {catalogueCount.toLocaleString()}</button>
          </div>
          <span className="a-filter-label" style={{ marginLeft: 8 }}>Severity</span>
          <div className="a-filter-group">
            {SEVERITY.map(([k, l]) => (
              <button key={k} className={filters.severity === k ? 'active' : ''} onClick={() => set({ severity: k })}>
                {k !== 'all' && <span className={`lv-dot`} style={{ background: `var(--s-${k === 'anomaly' ? 'critical' : k === 'suspect' ? 'warning' : k === 'degraded' ? 'neutral' : 'nominal'})` }} />}
                {l}
              </button>
            ))}
          </div>
          <select className="a-select" value={filters.finding} onChange={(e) => set({ finding: e.target.value as MapFilters['finding'] })} aria-label="Finding">
            {FINDING.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select className="a-select" value={filters.region} onChange={(e) => set({ region: e.target.value })} aria-label="Region">
            <option value="all">All regions</option>
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          {filtered && <button className="lv-link" style={{ fontSize: '0.74rem' }} onClick={() => onFiltersChange({ ...filters, severity: 'all', finding: 'all', region: 'all' })}>Clear filters</button>}
        </div>
        <span className="lv-muted a-num">{shown.toLocaleString()} stations shown</span>
      </div>

      <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 360px', gap: 12, height: 'calc(100vh - 150px)', minHeight: 520 }}>
        <div className="dashboard-map-card" style={{ height: '100%', minHeight: 0 }}>
          <AtherMap
            ref={ref}
            stationsGeoJSON={stationsGeoJSON}
            selectedStationId={selectedStation?.id ?? null}
            onSelectStation={onSelectStation}
            activeLayers={activeLayers}
            basemap={basemap}
            onToggleBasemap={onToggleBasemap}
            isGlobeMode={isGlobeMode}
            onToggleGlobeMode={onToggleGlobeMode}
            neighbors={neighbors}
            showAnomalyOverlay={showAnomalyOverlay}
            isActive={isActive}
          />
          <button className={`map-options-trigger-btn ${layersOpen ? 'active' : ''}`} onClick={() => setLayersOpen((v) => !v)} aria-expanded={layersOpen}>
            <SlidersHorizontal size={14} /><span>DISPLAY</span>
          </button>
          <LayerControls
            isOpen={layersOpen}
            onClose={() => setLayersOpen(false)}
            activeLayers={activeLayers}
            onToggleLayer={onToggleLayer}
            basemap={basemap}
            onToggleBasemap={onToggleBasemap}
            showAnomalyOverlay={showAnomalyOverlay}
            onToggleAnomalyOverlay={onToggleAnomalyOverlay}
            isGlobeMode={isGlobeMode}
            onToggleGlobeMode={onToggleGlobeMode}
          />
        </div>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
          {selectedStation ? (
            <StationPreviewPanel station={selectedStation} onClose={onClosePreview} onViewDetails={onViewStationDetails} />
          ) : (
            <section className="lv-card" style={{ flex: 1, minHeight: 0 }}>
              <header className="lv-card-head">
                <span className="lv-card-title">Needing attention in view</span>
                <span className="lv-muted a-num">{attention.length}</span>
              </header>
              <div className="lv-card-body" style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
                {!attention.length ? (
                  <Empty>{filters.network === 'live' ? 'Every live station matching these filters is nominal.' : 'No live station matching these filters needs attention.'}</Empty>
                ) : (
                  <div className="lv-feed">
                    {attention.map((p) => (
                      <button key={p.id} className={`lv-feed-item ${p.liveStatus === 'anomaly' ? 'anomaly' : p.liveStatus === 'suspect' ? 'suspect' : 'system'}`} onClick={() => onSelectStation(String(p.id))}>
                        <span className="lv-feed-bar" />
                        <span>
                          <span className="lv-feed-top"><StatusPill status={p.liveStatus} small /><span className="lv-feed-time">{formatAge(p.timestamp)}</span></span>
                          <div className="lv-feed-title">{p.name}</div>
                          <div className="lv-feed-text">{p.id} · {p.region || '—'} · {INTERPRETATION_LABEL[p.interpretation] || '—'}</div>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}
          <section className="lv-card">
            <div className="lv-card-body">
              <div className="lv-legend" style={{ gap: 14 }}>
                <span><i style={{ background: 'var(--s-nominal)', borderRadius: '50%' }} />Healthy</span>
                <span><i style={{ background: 'var(--s-warning)', borderRadius: '50%' }} />Warning</span>
                <span><i style={{ background: 'var(--s-critical)', borderRadius: '50%' }} />Critical</span>
                <span><i style={{ background: 'var(--s-neutral)', borderRadius: '50%' }} />Degraded / not live</span>
              </div>
              <p className="a-note" style={{ marginTop: 6 }}>Clusters take the colour of their most severe station. Only critical stations animate.</p>
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
});
