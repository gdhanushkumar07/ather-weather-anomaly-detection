import maplibregl from 'maplibre-gl';
import { toMapLibreColorExpression, TEMPERATURE_STOPS, PRESSURE_STOPS, HUMIDITY_STOPS } from './vane/colormaps';

export const STATIONS_SOURCE_ID = 'ather-stations-source';
export const PARAMETER_HALO_LAYER_ID = 'ather-parameter-halo';
export const PARAMETER_VALUE_LABEL_LAYER_ID = 'ather-parameter-value-label';

export type ParameterField = 'temperature' | 'pressure' | 'humidity';

const PARAMETER_COLOR_STOPS: Record<ParameterField, ReturnType<typeof toMapLibreColorExpression>> = {
  temperature: toMapLibreColorExpression('temperature', TEMPERATURE_STOPS),
  pressure: toMapLibreColorExpression('pressure', PRESSURE_STOPS),
  humidity: toMapLibreColorExpression('humidity', HUMIDITY_STOPS),
};
export const CLUSTERS_LAYER_ID = 'ather-clusters';
export const CLUSTER_COUNT_LAYER_ID = 'ather-cluster-count';
export const ANOMALY_PULSE_LAYER_ID = 'ather-anomaly-pulse';
export const CLUSTER_ALERT_PULSE_LAYER_ID = 'ather-cluster-alert-pulse';
export const CLUSTER_ANOMALY_BADGE_LAYER_ID = 'ather-cluster-anomaly-badge';
export const SELECTED_HALO_LAYER_ID = 'ather-selected-station-halo';
export const UNCLUSTERED_RING_LAYER_ID = 'ather-unclustered-ring';
export const UNCLUSTERED_BASE_LAYER_ID = 'ather-unclustered-base';
export const UNCLUSTERED_CORE_LAYER_ID = 'ather-unclustered-core';

export function setupStationLayers(
  map: maplibregl.Map,
  data: GeoJSON.FeatureCollection,
  onSelectStation: (stationId: string) => void
) {
  // Add clustered GeoJSON source
  if (!map.getSource(STATIONS_SOURCE_ID)) {
    map.addSource(STATIONS_SOURCE_ID, {
      type: 'geojson',
      data: data,
      cluster: true,
      clusterMaxZoom: 11,
      clusterRadius: 45,
      // Aggregate per-station status up into the cluster itself. Without
      // this, a cluster knows only how many points it holds — which is why
      // the world view used to render 190 anomalies as uniform cyan.
      clusterProperties: {
        anomalies: ['+', ['case', ['==', ['get', 'status'], 'ANOMALY'], 1, 0]],
        warnings: ['+', ['case', ['==', ['get', 'status'], 'WARNING'], 1, 0]],
        offline: ['+', ['case', ['==', ['get', 'status'], 'OFFLINE'], 1, 0]]
      }
    });
  } else {
    const src = map.getSource(STATIONS_SOURCE_ID) as maplibregl.GeoJSONSource;
    src.setData(data);
  }

  // 1. Cluster Circles (Dark translucent center, cyan accent ring, crisp white border)
  if (!map.getLayer(CLUSTERS_LAYER_ID)) {
    map.addLayer({
      id: CLUSTERS_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': [
          'step',
          ['get', 'point_count'],
          'rgba(14, 28, 48, 0.90)', // small cluster (< 20)
          20,
          'rgba(12, 38, 64, 0.92)', // medium cluster (20 - 100)
          100,
          'rgba(8, 48, 80, 0.94)'   // large cluster (> 100)
        ],
        // Continuous sqrt-style scaling instead of three fixed buckets, so a
        // 4-station cluster and a 943-station cluster no longer read as the
        // same size. Stops approximate sqrt(count) over the real range.
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['sqrt', ['get', 'point_count']],
          1, 12,
          4, 17,
          10, 23,
          20, 29,
          32, 36
        ],
        // Worst-status-wins ring: red if the cluster contains any anomalous
        // station, amber for warnings, otherwise the neutral cyan.
        'circle-stroke-color': [
          'case',
          ['>', ['get', 'anomalies'], 0], '#ef4444',
          ['>', ['get', 'warnings'], 0], '#f59e0b',
          '#00e5ff'
        ],
        'circle-stroke-width': [
          'case',
          ['>', ['get', 'anomalies'], 0], 3,
          2
        ],
        'circle-opacity': 0.98
      }
    });
  }

  // 1b. Cluster Alert Pulse — a soft red halo behind any cluster that holds
  // at least one anomalous station. Animated by startAnomalyPulse() below so
  // that at world zoom the eye is pulled to where the incidents actually are.
  if (!map.getLayer(CLUSTER_ALERT_PULSE_LAYER_ID)) {
    map.addLayer({
      id: CLUSTER_ALERT_PULSE_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['all', ['has', 'point_count'], ['>', ['get', 'anomalies'], 0]],
      paint: {
        'circle-color': 'rgba(239, 68, 68, 0.14)',
        'circle-radius': 26,
        'circle-stroke-width': 1,
        'circle-stroke-color': 'rgba(239, 68, 68, 0.45)'
      }
    }, CLUSTERS_LAYER_ID);
  }

  // 1c. Anomaly Count Badge — the exact number of anomalous stations inside
  // a cluster, offset to the upper-right of the bubble. Answers "how bad is
  // this cluster" without requiring a click-through to find out.
  if (!map.getLayer(CLUSTER_ANOMALY_BADGE_LAYER_ID)) {
    map.addLayer({
      id: CLUSTER_ANOMALY_BADGE_LAYER_ID,
      type: 'symbol',
      source: STATIONS_SOURCE_ID,
      filter: ['all', ['has', 'point_count'], ['>', ['get', 'anomalies'], 0]],
      layout: {
        'text-field': ['concat', '▲ ', ['to-string', ['get', 'anomalies']]],
        'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
        'text-size': 10,
        'text-offset': [1.5, -1.5],
        'text-allow-overlap': true,
        'text-ignore-placement': true
      },
      paint: {
        'text-color': '#fca5a5',
        'text-halo-color': 'rgba(8, 12, 20, 0.95)',
        'text-halo-width': 1.6
      }
    });
  }

  // 2. Cluster Count Labels
  if (!map.getLayer(CLUSTER_COUNT_LAYER_ID)) {
    map.addLayer({
      id: CLUSTER_COUNT_LAYER_ID,
      type: 'symbol',
      source: STATIONS_SOURCE_ID,
      filter: ['has', 'point_count'],
      layout: {
        'text-field': '{point_count_abbreviated}',
        'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
        'text-size': 11,
        'text-allow-overlap': true,
        'text-ignore-placement': true
      },
      paint: {
        'text-color': '#ffffff'
      }
    });
  }

  // 3. Anomaly Pulsing Alert Halo (Unclustered)
  if (!map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
    map.addLayer({
      id: ANOMALY_PULSE_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: [
        'all',
        ['!', ['has', 'point_count']],
        ['==', ['get', 'hasAnomaly'], 1]
      ],
      paint: {
        'circle-color': 'rgba(239, 68, 68, 0.16)',
        'circle-radius': 14,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#ef4444'
      }
    });
  }

  // 4. Selected Station Highlighting Halo (Cyan Selection Ring)
  if (!map.getLayer(SELECTED_HALO_LAYER_ID)) {
    map.addLayer({
      id: SELECTED_HALO_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['==', ['get', 'id'], ''], // updated dynamically
      paint: {
        'circle-color': 'rgba(0, 229, 255, 0.22)',
        'circle-radius': 16,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#00e5ff'
      }
    });
  }

  // 5a. Real-data parameter halo (Temperature / Pressure / Relative Humidity).
  // Colors each unclustered station by its ACTUAL reported value for the
  // currently selected parameter (real lat/lon/value from the same station
  // GeoJSON already loaded — no new network request, no synthetic grid).
  // Rendered with a bold, luminous radius and border so parameter changes are
  // unmistakably visible across the entire subcontinent.
  if (!map.getLayer(PARAMETER_HALO_LAYER_ID)) {
    map.addLayer({
      id: PARAMETER_HALO_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['literal', false], // disabled until setParameterLayer() activates it
      paint: {
        'circle-color': '#94a3b8',
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          3, 10,
          7, 14,
          12, 18
        ],
        'circle-opacity': 0.88,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-opacity': 0.95
      },
      layout: { visibility: 'none' }
    });
  }

  // 5b. Station parameter value text label (zoom >= 5.5)
  if (!map.getLayer(PARAMETER_VALUE_LABEL_LAYER_ID)) {
    map.addLayer({
      id: PARAMETER_VALUE_LABEL_LAYER_ID,
      type: 'symbol',
      source: STATIONS_SOURCE_ID,
      filter: ['literal', false],
      minzoom: 5.5,
      layout: {
        'text-field': ['to-string', ['get', 'temperature']],
        'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
        'text-size': 11,
        'text-offset': [0, 1.4],
        'text-anchor': 'top',
        'text-allow-overlap': false
      },
      paint: {
        'text-color': '#ffffff',
        'text-halo-color': '#000000',
        'text-halo-width': 1.5
      }
    });
  }

  // 5. Professional Weather Station Marker - Outer Status Ring
  if (!map.getLayer(UNCLUSTERED_RING_LAYER_ID)) {
    map.addLayer({
      id: UNCLUSTERED_RING_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': [
          'match',
          ['get', 'status'],
          'ANOMALY',
          '#ef4444', // Red
          'WARNING',
          '#f59e0b', // Amber
          'NORMAL',
          '#10b981', // Green
          /* default / offline */ '#94a3b8'
        ],
        'circle-radius': [
          'case',
          ['==', ['get', 'hasAnomaly'], 1],
          7.5,
          6.5
        ],
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#ffffff',
        'circle-opacity': 0.98
      }
    });
  }

  // 6. Professional Weather Station Marker - Inner White Base
  if (!map.getLayer(UNCLUSTERED_BASE_LAYER_ID)) {
    map.addLayer({
      id: UNCLUSTERED_BASE_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': '#ffffff',
        'circle-radius': 3.8,
        'circle-opacity': 1.0
      }
    });
  }

  // 7. Professional Weather Station Marker - Center Sensor Core
  if (!map.getLayer(UNCLUSTERED_CORE_LAYER_ID)) {
    map.addLayer({
      id: UNCLUSTERED_CORE_LAYER_ID,
      type: 'circle',
      source: STATIONS_SOURCE_ID,
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': [
          'match',
          ['get', 'status'],
          'ANOMALY',
          '#ef4444',
          'WARNING',
          '#f59e0b',
          'NORMAL',
          '#10b981',
          '#64748b'
        ],
        'circle-radius': 2.0,
        'circle-opacity': 1.0
      }
    });
  }

  // Attach click and hover listeners only once per map instance
  if (!(map as any)._atherStationListenersAttached) {
    (map as any)._atherStationListenersAttached = true;

    // Click handler for clusters: smooth zoom into cluster
    map.on('click', CLUSTERS_LAYER_ID, (e) => {
      const features = map.queryRenderedFeatures(e.point, { layers: [CLUSTERS_LAYER_ID] });
      if (!features.length) return;
      const clusterId = features[0].properties?.cluster_id;
      const source = map.getSource(STATIONS_SOURCE_ID) as maplibregl.GeoJSONSource;

      source.getClusterExpansionZoom(clusterId).then((zoom) => {
        const coords = (features[0].geometry as GeoJSON.Point).coordinates;
        map.easeTo({
          center: [coords[0], coords[1]],
          zoom: zoom + 0.6,
          duration: 450
        });
      });
    });

    // Click handler for individual station: select station
    map.on('click', UNCLUSTERED_RING_LAYER_ID, (e) => {
      const features = map.queryRenderedFeatures(e.point, { layers: [UNCLUSTERED_RING_LAYER_ID] });
      if (!features.length) return;
      const stnId = features[0].properties?.id;
      if (stnId) {
        onSelectStation(stnId);
      }
    });

    // Cluster hover: status breakdown popup, so an operator can triage a
    // region without zooming into it first.
    const clusterPopup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 18,
      className: 'ather-cluster-popup'
    });

    map.on('mouseenter', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = 'pointer'; });

    map.on('mousemove', CLUSTERS_LAYER_ID, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties || {};
      const total = Number(p.point_count) || 0;
      const anomalies = Number(p.anomalies) || 0;
      const warnings = Number(p.warnings) || 0;
      const offline = Number(p.offline) || 0;
      const normal = Math.max(0, total - anomalies - warnings - offline);

      const row = (cls: string, label: string, value: number) =>
        value > 0
          ? `<div class="cp-row"><span class="cp-dot ${cls}"></span><span class="cp-label">${label}</span><span class="cp-val">${value}</span></div>`
          : '';

      clusterPopup
        .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
        .setHTML(
          `<div class="cp-head">${total.toLocaleString()} stations</div>` +
          row('anomaly', 'Anomaly', anomalies) +
          row('warning', 'Warning', warnings) +
          row('normal', 'Normal', normal) +
          row('offline', 'Offline', offline) +
          `<div class="cp-hint">Click to expand</div>`
        )
        .addTo(map);
    });

    map.on('mouseleave', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = ''; clusterPopup.remove(); });
    map.on('mouseenter', UNCLUSTERED_RING_LAYER_ID, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', UNCLUSTERED_RING_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
  }
}

/**
 * Shows/hides and re-colors the real-data parameter halo layer and value labels. `field` is
 * null to hide it (no parameter selected). Only unclustered stations that
 * actually reported a non-null value for the field are shown — missing
 * values stay missing, never substituted (Phase 3 of the weather-layer fix).
 */
export function setParameterLayer(map: maplibregl.Map, field: ParameterField | null) {
  if (!map.getLayer(PARAMETER_HALO_LAYER_ID)) return;

  if (!field) {
    map.setLayoutProperty(PARAMETER_HALO_LAYER_ID, 'visibility', 'none');
    if (map.getLayer(PARAMETER_VALUE_LABEL_LAYER_ID)) {
      map.setLayoutProperty(PARAMETER_VALUE_LABEL_LAYER_ID, 'visibility', 'none');
    }
    return;
  }

  // Filter out missing/null values: strictly only stations with valid observations for `field`
  const validFilter = [
    'all',
    ['!', ['has', 'point_count']],
    ['has', field],
    ['!=', ['get', field], null],
  ];

  map.setFilter(PARAMETER_HALO_LAYER_ID, validFilter as any);
  map.setPaintProperty(PARAMETER_HALO_LAYER_ID, 'circle-color', PARAMETER_COLOR_STOPS[field]);
  map.setLayoutProperty(PARAMETER_HALO_LAYER_ID, 'visibility', 'visible');

  if (map.getLayer(PARAMETER_VALUE_LABEL_LAYER_ID)) {
    map.setFilter(PARAMETER_VALUE_LABEL_LAYER_ID, validFilter as any);
    const unit = field === 'temperature' ? '°C' : field === 'pressure' ? ' hPa' : '%';
    map.setLayoutProperty(PARAMETER_VALUE_LABEL_LAYER_ID, 'text-field', [
      'concat',
      ['to-string', ['get', field]],
      unit
    ]);
    map.setLayoutProperty(PARAMETER_VALUE_LABEL_LAYER_ID, 'visibility', 'visible');
  }
}

export function updateSelectedStationHalo(map: maplibregl.Map, selectedStationId: string | null) {
  if (map.getLayer(SELECTED_HALO_LAYER_ID)) {
    if (selectedStationId) {
      map.setFilter(SELECTED_HALO_LAYER_ID, ['==', ['get', 'id'], selectedStationId]);
    } else {
      map.setFilter(SELECTED_HALO_LAYER_ID, ['==', ['get', 'id'], '']);
    }
  }
}

export function setStationLayersVisibility(map: maplibregl.Map, visible: boolean) {
  const vis = visible ? 'visible' : 'none';
  [
    CLUSTERS_LAYER_ID,
    CLUSTER_COUNT_LAYER_ID,
    SELECTED_HALO_LAYER_ID,
    UNCLUSTERED_RING_LAYER_ID,
    UNCLUSTERED_BASE_LAYER_ID,
    UNCLUSTERED_CORE_LAYER_ID,
    CLUSTER_ANOMALY_BADGE_LAYER_ID,
    PARAMETER_VALUE_LABEL_LAYER_ID
  ].forEach((layerId) => {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  });
  // Anomaly pulse halo has its own independent visibility toggle (Map
  // Options → Anomaly Overlay) — only force it off here when markers are
  // hidden entirely; turning markers back on restores it via that toggle's
  // own state in the caller (see AtherMap.tsx effect ordering).
  if (!visible) {
    [ANOMALY_PULSE_LAYER_ID, CLUSTER_ALERT_PULSE_LAYER_ID].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none');
    });
  }
}

/** Independent visibility control for the pulsing anomaly-alert halo layer
 * (Map Options → Anomaly Overlay), decoupled from the main AWS markers
 * on/off toggle. */
export function setAnomalyOverlayVisibility(map: maplibregl.Map, visible: boolean) {
  [ANOMALY_PULSE_LAYER_ID, CLUSTER_ALERT_PULSE_LAYER_ID, CLUSTER_ANOMALY_BADGE_LAYER_ID].forEach((id) => {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
    }
  });
}

/**
 * Drives the actual animation for the two alert-halo layers. The layer was
 * previously named "pulse" but rendered as a static circle — this is the
 * missing rAF loop. Radius and opacity breathe on a ~1.6s cycle; returns a
 * disposer the caller must invoke on unmount.
 *
 * Respects prefers-reduced-motion: when the user has asked for less motion,
 * the halos are drawn at a fixed mid-size instead of animating.
 */
export function startAnomalyPulse(map: maplibregl.Map): () => void {
  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  if (reduceMotion) {
    if (map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
      map.setPaintProperty(ANOMALY_PULSE_LAYER_ID, 'circle-radius', 14);
    }
    if (map.getLayer(CLUSTER_ALERT_PULSE_LAYER_ID)) {
      map.setPaintProperty(CLUSTER_ALERT_PULSE_LAYER_ID, 'circle-radius', 30);
    }
    return () => {};
  }

  let frame = 0;
  const PERIOD = 1600;
  const start = performance.now();

  const tick = (now: number) => {
    // 0 → 1 → 0 triangle wave, eased
    const t = ((now - start) % PERIOD) / PERIOD;
    const wave = 0.5 - 0.5 * Math.cos(t * Math.PI * 2);

    if (map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
      map.setPaintProperty(ANOMALY_PULSE_LAYER_ID, 'circle-radius', 12 + wave * 8);
      map.setPaintProperty(ANOMALY_PULSE_LAYER_ID, 'circle-stroke-opacity', 0.85 - wave * 0.45);
      map.setPaintProperty(ANOMALY_PULSE_LAYER_ID, 'circle-opacity', 0.9 - wave * 0.5);
    }
    if (map.getLayer(CLUSTER_ALERT_PULSE_LAYER_ID)) {
      map.setPaintProperty(CLUSTER_ALERT_PULSE_LAYER_ID, 'circle-radius', 24 + wave * 14);
      map.setPaintProperty(CLUSTER_ALERT_PULSE_LAYER_ID, 'circle-stroke-opacity', 0.6 - wave * 0.4);
    }

    frame = requestAnimationFrame(tick);
  };

  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}

/**
 * Flat, sorted list of every anomalous (then warning) station in the current
 * GeoJSON. Backs the "next incident" map control — the map's own clustering
 * makes a single bad station inside a 900-station cluster unreachable by
 * panning, so there has to be a way to jump straight to it.
 */
export interface IncidentTarget {
  id: string;
  name: string;
  status: string;
  center: [number, number];
}

export function collectIncidentTargets(
  data: GeoJSON.FeatureCollection | null
): IncidentTarget[] {
  if (!data?.features) return [];

  const rank = (s: string) => (s === 'ANOMALY' ? 0 : s === 'WARNING' ? 1 : 2);

  return data.features
    .filter((f) => {
      const s = f.properties?.status;
      return s === 'ANOMALY' || s === 'WARNING';
    })
    .map((f) => {
      const coords = (f.geometry as GeoJSON.Point).coordinates;
      return {
        id: String(f.properties?.id ?? ''),
        name: String(f.properties?.name ?? f.properties?.id ?? 'Unknown station'),
        status: String(f.properties?.status ?? ''),
        center: [coords[0], coords[1]] as [number, number]
      };
    })
    .sort((a, b) => rank(a.status) - rank(b.status) || a.name.localeCompare(b.name));
}
