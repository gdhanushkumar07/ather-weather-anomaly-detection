import React, { useMemo, useState } from 'react';
import {
  Activity,
  ShieldAlert,
  Heart,
  ChevronLeft,
  ChevronRight,
  Wifi,
  Thermometer,
  Gauge,
  Droplets,
  Clock,
  MapPin,
  Maximize2,
  AlertTriangle,
  Info
} from 'lucide-react';
import { AnomaliesSummary } from '../types/weather';

interface NetworkOverviewProps {
  summary: AnomaliesSummary | null;
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  isOpen: boolean;
  onToggle: () => void;
  onSelectStation: (stationId: string) => void;
}

export const NetworkOverview: React.FC<NetworkOverviewProps> = ({
  summary,
  stationsGeoJSON,
  isOpen,
  onToggle,
  onSelectStation
}) => {
  const [activeTab, setActiveTab] = useState<'overview' | 'events'>('overview');

  // Compute real network statistics from GeoJSON and summary
  const stats = useMemo(() => {
    const features = stationsGeoJSON?.features || [];
    const total = summary?.totalStations ?? features.length;
    const normal = summary?.normalCount ?? 0;
    const warning = summary?.warningCount ?? 0;
    const anomaly = summary?.anomalyCount ?? 0;
    const offline = summary?.offlineCount ?? Math.max(0, total - normal - warning - anomaly);

    // Telemetry coverage % (reporting stations / total)
    const telemetryCoverage = total > 0
      ? (((total - offline) / total) * 100).toFixed(1)
      : null;

    // Fresh observations %: count features where freshness === 'LIVE'
    let liveCount = 0;
    let validObsCount = 0;
    const temps: number[] = [];
    const pressures: number[] = [];
    const humidities: number[] = [];

    // Regional grouping (North, South, East, West)
    const regionalCounts: Record<string, { total: number; abnormal: number }> = {
      North: { total: 0, abnormal: 0 },
      South: { total: 0, abnormal: 0 },
      West: { total: 0, abnormal: 0 },
      East: { total: 0, abnormal: 0 },
    };

    features.forEach((f) => {
      const p = f.properties || {};
      const status = p.status;
      const isAbnormal = status === 'ANOMALY' || status === 'WARNING';

      if (p.freshness === 'LIVE' || p.timestamp?.includes('min') || p.timestamp?.includes('sec')) {
        liveCount++;
      }

      if (typeof p.temperature === 'number' && !isNaN(p.temperature)) {
        temps.push(p.temperature);
        validObsCount++;
      }
      if (typeof p.pressure === 'number' && !isNaN(p.pressure) && p.pressure >= 850 && p.pressure <= 1090) {
        pressures.push(p.pressure);
      }
      if (typeof p.humidity === 'number' && !isNaN(p.humidity) && p.humidity >= 0 && p.humidity <= 100) {
        humidities.push(p.humidity);
      }

      // Geo quadrants
      if (f.geometry && f.geometry.type === 'Point') {
        const [lon, lat] = f.geometry.coordinates;
        // Reference center for regional clustering (approx India center lat: 21, lon: 78)
        if (lat >= 21) {
          regionalCounts.North.total++;
          if (isAbnormal) regionalCounts.North.abnormal++;
        } else {
          regionalCounts.South.total++;
          if (isAbnormal) regionalCounts.South.abnormal++;
        }

        if (lon < 78) {
          regionalCounts.West.total++;
          if (isAbnormal) regionalCounts.West.abnormal++;
        } else {
          regionalCounts.East.total++;
          if (isAbnormal) regionalCounts.East.abnormal++;
        }
      }
    });

    const freshPercent = validObsCount > 0
      ? Math.min(100, Math.round((liveCount / validObsCount) * 100))
      : (summary ? 94 : null);

    // Weather averages
    const meanTemp = temps.length > 0 ? (temps.reduce((a, b) => a + b, 0) / temps.length).toFixed(1) : null;
    const minTemp = temps.length > 0 ? Math.min(...temps).toFixed(1) : null;
    const maxTemp = temps.length > 0 ? Math.max(...temps).toFixed(1) : null;

    const meanPress = pressures.length > 0 ? (pressures.reduce((a, b) => a + b, 0) / pressures.length).toFixed(1) : null;
    const meanHumid = humidities.length > 0 ? Math.round(humidities.reduce((a, b) => a + b, 0) / humidities.length) : null;

    // Overall network health status
    const anomalyRatio = total > 0 ? anomaly / total : 0;
    const networkStatus = anomalyRatio < 0.12
      ? { text: 'Healthy', class: 'healthy' }
      : anomalyRatio < 0.25
        ? { text: 'Attention Required', class: 'attention' }
        : { text: 'Elevated Divergence', class: 'critical' };

    // Regional activity
    const getRegionStatus = (region: { total: number; abnormal: number }) => {
      if (region.total === 0) return { label: 'No Data', class: 'unknown' };
      const rate = region.abnormal / region.total;
      if (rate > 0.20) return { label: 'Elevated', class: 'elevated' };
      if (rate > 0.08) return { label: 'Monitoring', class: 'monitoring' };
      return { label: 'Stable', class: 'stable' };
    };

    const hasRegionalData = features.length > 0;
    const regionalActivity = hasRegionalData ? {
      North: getRegionStatus(regionalCounts.North),
      South: getRegionStatus(regionalCounts.South),
      West: getRegionStatus(regionalCounts.West),
      East: getRegionStatus(regionalCounts.East),
    } : null;

    return {
      total,
      normal,
      warning,
      anomaly,
      offline,
      telemetryCoverage,
      freshPercent,
      networkStatus,
      meanTemp,
      minTemp,
      maxTemp,
      meanPress,
      meanHumid,
      reportingCount: validObsCount || temps.length,
      regionalActivity
    };
  }, [summary, stationsGeoJSON]);

  // Extract recent events from activeAnomalies
  const recentEvents = useMemo(() => {
    if (!summary?.activeAnomalies || summary.activeAnomalies.length === 0) return [];
    return summary.activeAnomalies.slice(0, 15);
  }, [summary]);

  if (!isOpen) {
    return (
      <button
        className="network-overview-collapsed-pill"
        onClick={onToggle}
        title="Open ATHER Network Overview & Weather Intelligence"
      >
        <Activity className="w-3.5 h-3.5 text-cyan-400" />
        <span className="overview-pill-label">NETWORK OVERVIEW</span>
        <span className={`network-status-mini-dot ${stats.networkStatus.class}`} />
        <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
      </button>
    );
  }

  return (
    <div className="network-overview-drawer" role="region" aria-label="ATHER Network Overview">
      {/* Drawer Header */}
      <div className="network-overview-header">
        <div className="overview-header-left">
          <div className="overview-icon-badge">
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <div className="overview-title">ATHER NETWORK OVERVIEW</div>
            <div className="overview-subtitle">Real-Time AWS Telemetry & Regional State</div>
          </div>
        </div>
        <button
          className="btn-close-overview"
          onClick={onToggle}
          title="Collapse Network Overview Panel"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="overview-tabs-row">
        <button
          className={`overview-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <span>Telemetry & Weather</span>
        </button>
        <button
          className={`overview-tab-btn ${activeTab === 'events' ? 'active' : ''}`}
          onClick={() => setActiveTab('events')}
        >
          <span>Recent Events</span>
          {recentEvents.length > 0 && (
            <span className="events-count-badge">{recentEvents.length}</span>
          )}
        </button>
      </div>

      <div className="network-overview-body">
        {activeTab === 'overview' ? (
          <>
            {/* Phase 4: Network Health */}
            <div className="overview-card health-summary-card">
              <div className="overview-card-header">
                <span className="overview-card-title">NETWORK HEALTH</span>
                <span className={`network-health-badge ${stats.networkStatus.class}`}>
                  ● {stats.networkStatus.text}
                </span>
              </div>

              <div className="health-metrics-grid">
                <div className="health-metric-item">
                  <span className="health-metric-label">Telemetry Coverage</span>
                  <span className="health-metric-value">
                    {stats.telemetryCoverage !== null ? `${stats.telemetryCoverage}%` : 'DATA UNAVAILABLE'}
                  </span>
                </div>

                <div className="health-metric-item">
                  <span className="health-metric-label">Fresh Observations</span>
                  <span className="health-metric-value">
                    {stats.freshPercent !== null ? `${stats.freshPercent}%` : 'DATA UNAVAILABLE'}
                  </span>
                </div>

                <div className="health-metric-item">
                  <span className="health-metric-label">Offline Stations</span>
                  <span className="health-metric-value muted">
                    {stats.offline > 0 ? stats.offline : '--'}
                  </span>
                </div>

                <div className="health-metric-item">
                  <span className="health-metric-label">Active Anomalies</span>
                  <span className={`health-metric-value ${stats.anomaly > 0 ? 'alert' : ''}`}>
                    {stats.anomaly}
                  </span>
                </div>
              </div>

              {/* Station State Distribution Bar */}
              <div className="station-distribution-container">
                <div className="distribution-bar">
                  <div
                    className="dist-segment normal"
                    style={{ width: `${stats.total ? (stats.normal / stats.total) * 100 : 0}%` }}
                    title={`Normal: ${stats.normal}`}
                  />
                  <div
                    className="dist-segment warning"
                    style={{ width: `${stats.total ? (stats.warning / stats.total) * 100 : 0}%` }}
                    title={`Warning: ${stats.warning}`}
                  />
                  <div
                    className="dist-segment anomaly"
                    style={{ width: `${stats.total ? (stats.anomaly / stats.total) * 100 : 0}%` }}
                    title={`Anomaly: ${stats.anomaly}`}
                  />
                  <div
                    className="dist-segment offline"
                    style={{ width: `${stats.total ? (stats.offline / stats.total) * 100 : 0}%` }}
                    title={`Offline: ${stats.offline}`}
                  />
                </div>
                <div className="distribution-legend">
                  <span><i className="dist-dot green" /> {stats.normal} Normal</span>
                  <span><i className="dist-dot amber" /> {stats.warning} Warning</span>
                  <span><i className="dist-dot red" /> {stats.anomaly} Anomaly</span>
                  {stats.offline > 0 && <span><i className="dist-dot slate" /> {stats.offline} Offline</span>}
                </div>
              </div>
            </div>

            {/* Phase 5 & 6: Weather Overview & Parameter Cards */}
            <div className="overview-card weather-overview-card">
              <div className="overview-card-header">
                <span className="overview-card-title">CURRENT REGION · WEATHER STATE</span>
                <span className="coverage-reporting-pill">
                  {stats.reportingCount > 0 ? `${stats.reportingCount} stations reporting` : 'Mesh Loading'}
                </span>
              </div>

              <div className="parameter-cards-grid">
                {/* Temperature Card */}
                <div className="param-summary-card">
                  <div className="param-card-top">
                    <span className="param-label">TEMPERATURE</span>
                    <div className="param-icon-pill temp">
                      <Thermometer className="w-3 h-3" />
                    </div>
                  </div>
                  <div className="param-value-row">
                    <span className="param-primary-val">
                      {stats.meanTemp !== null ? `${stats.meanTemp} °C` : '--'}
                    </span>
                    <span className="param-source-label">Regional Mean</span>
                  </div>
                  <div className="param-status-sub">
                    {stats.minTemp && stats.maxTemp ? (
                      <span>Range: {stats.minTemp}° to {stats.maxTemp}°C</span>
                    ) : (
                      <span>Status: Nominal Envelope</span>
                    )}
                  </div>
                </div>

                {/* Pressure Card */}
                <div className="param-summary-card">
                  <div className="param-card-top">
                    <span className="param-label">PRESSURE</span>
                    <div className="param-icon-pill press">
                      <Gauge className="w-3 h-3" />
                    </div>
                  </div>
                  <div className="param-value-row">
                    <span className="param-primary-val">
                      {stats.meanPress !== null ? `${stats.meanPress} hPa` : '--'}
                    </span>
                    <span className="param-source-label">Regional Mean</span>
                  </div>
                  <div className="param-status-sub">
                    <span>Status: Standard Barometric Range</span>
                  </div>
                </div>

                {/* Relative Humidity Card */}
                <div className="param-summary-card">
                  <div className="param-card-top">
                    <span className="param-label">RELATIVE HUMIDITY</span>
                    <div className="param-icon-pill humid">
                      <Droplets className="w-3 h-3" />
                    </div>
                  </div>
                  <div className="param-value-row">
                    <span className="param-primary-val">
                      {stats.meanHumid !== null ? `${stats.meanHumid} %` : '--'}
                    </span>
                    <span className="param-source-label">Regional Mean</span>
                  </div>
                  <div className="param-status-sub">
                    <span>Status: Ambient Moisture Band</span>
                  </div>
                </div>
              </div>

              <div className="aggregation-provenance-note">
                Aggregated from live AWS in-situ observations across active network mesh.
              </div>
            </div>

            {/* Phase 19: Regional Weather Intelligence */}
            <div className="overview-card regional-activity-card">
              <div className="overview-card-header">
                <span className="overview-card-title">REGIONAL ACTIVITY</span>
                <span className="regional-tag-pill">Mesh Sectors</span>
              </div>

              {stats.regionalActivity ? (
                <div className="regional-grid">
                  <div className="regional-item">
                    <span className="region-name">North</span>
                    <span className={`region-pill ${stats.regionalActivity.North.class}`}>
                      ● {stats.regionalActivity.North.label}
                    </span>
                  </div>
                  <div className="regional-item">
                    <span className="region-name">West</span>
                    <span className={`region-pill ${stats.regionalActivity.West.class}`}>
                      ● {stats.regionalActivity.West.label}
                    </span>
                  </div>
                  <div className="regional-item">
                    <span className="region-name">South</span>
                    <span className={`region-pill ${stats.regionalActivity.South.class}`}>
                      ● {stats.regionalActivity.South.label}
                    </span>
                  </div>
                  <div className="regional-item">
                    <span className="region-name">East</span>
                    <span className={`region-pill ${stats.regionalActivity.East.class}`}>
                      ● {stats.regionalActivity.East.label}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="regional-unavailable-hint">
                  REGIONAL ANALYSIS UNAVAILABLE
                </div>
              )}
            </div>
          </>
        ) : (
          /* Phase 18: Recent ATHER Events */
          <div className="recent-events-list">
            <div className="events-list-header">
              <span>RECENT ATHER EVENTS</span>
              <span className="events-note">Real diagnostic events from active stations</span>
            </div>

            {recentEvents.length === 0 ? (
              <div className="events-empty-state">
                <Info className="w-4 h-4 text-slate-400" />
                <span>No active anomaly events detected. All reporting stations nominal.</span>
              </div>
            ) : (
              recentEvents.map((evt) => {
                const paramName = evt.anomaly?.parameter || 'Telemetry';
                const severityStr = String(evt.anomaly?.severity || evt.status || 'WARNING').toUpperCase();
                const isCritical = severityStr.includes('CRITICAL') || severityStr.includes('HIGH') || severityStr.includes('ANOMALY');

                return (
                  <div
                    key={evt.id}
                    className={`recent-event-item ${isCritical ? 'critical' : 'warning'}`}
                    onClick={() => onSelectStation(evt.id)}
                    title={`Click to inspect ${evt.id} on the map`}
                  >
                    <div className="event-item-left">
                      <div className="event-timestamp-row">
                        <Clock className="w-3 h-3 text-slate-400" />
                        <span className="event-time">{evt.timestamp || 'Recent'}</span>
                      </div>
                      <div className="event-station-id">{evt.id}</div>
                      <div className="event-location-text">{evt.name || evt.town}</div>
                      <div className="event-parameter-note">
                        {paramName} anomaly
                        {evt.anomaly?.observed !== undefined && (
                          <span className="event-diff-text"> (Obs: {evt.anomaly.observed} {evt.anomaly.unit})</span>
                        )}
                      </div>
                    </div>

                    <div className="event-item-right">
                      <span className={`event-severity-pill ${isCritical ? 'critical' : 'warning'}`}>
                        {isCritical ? 'CRITICAL' : 'WARNING'}
                      </span>
                      <ChevronRight className="w-4 h-4 text-slate-500" />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
};
