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
// NOTE: there are intentionally NO native cluster layers any more. Clusters are drawn as
// weather-station markers with a small count badge (StationMarkerLayer.tsx); the old
// cyan circle ('ather-clusters') and its text layer ('ather-cluster-count') were removed.
export const ANOMALY_PULSE_LAYER_ID = 'ather-anomaly-pulse';
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
      // MapLibre's built-in (supercluster) hierarchical clustering: clusters split as the
      // zoom increases, driven purely by station coordinates. Reused unchanged except that
      // each cluster now also carries how many of its stations are in each status, so the
      // cluster marker can show its highest severity without losing the individual statuses.
      cluster: true,
      clusterMaxZoom: 11,   // at zoom > 11 every station is individual (no clusters)
      clusterRadius: 60,    // px: sized for the AWS marker + count badge footprint
      clusterProperties: {
        anomalies: ['+', ['case', ['==', ['get', 'status'], 'ANOMALY'], 1, 0]],
        warnings: ['+', ['case', ['==', ['get', 'status'], 'WARNING'], 1, 0]],
        normals: ['+', ['case', ['==', ['get', 'status'], 'NORMAL'], 1, 0]]
      }
    });
  } else {
    const src = map.getSource(STATIONS_SOURCE_ID) as maplibregl.GeoJSONSource;
    src.setData(data);
  }

  // (Cluster circle + count layers removed: clusters are DOM weather-station markers with a count badge.)

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

    // Click handler for individual station: select station
    map.on('click', UNCLUSTERED_RING_LAYER_ID, (e) => {
      const features = map.queryRenderedFeatures(e.point, { layers: [UNCLUSTERED_RING_LAYER_ID] });
      if (!features.length) return;
      const stnId = features[0].properties?.id;
      if (stnId) {
        onSelectStation(stnId);
      }
    });

    // Hover cursor changes
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
    SELECTED_HALO_LAYER_ID,
    UNCLUSTERED_RING_LAYER_ID,
    UNCLUSTERED_BASE_LAYER_ID,
    UNCLUSTERED_CORE_LAYER_ID,
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
  if (!visible && map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
    map.setLayoutProperty(ANOMALY_PULSE_LAYER_ID, 'visibility', 'none');
  }
}

/** Independent visibility control for the pulsing anomaly-alert halo layer
 * (Map Options → Anomaly Overlay), decoupled from the main AWS markers
 * on/off toggle. */
export function setAnomalyOverlayVisibility(map: maplibregl.Map, visible: boolean) {
  if (map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
    map.setLayoutProperty(ANOMALY_PULSE_LAYER_ID, 'visibility', visible ? 'visible' : 'none');
  }
}

/**
 * Individual stations are now drawn as animated DOM weather-station markers
 * (see StationMarkerLayer.tsx / WeatherStationMarker.tsx). The native circle
 * layers above are kept as an automatic FALLBACK: this excludes the stations
 * that currently have a DOM marker so nothing is drawn twice, while any
 * station beyond the DOM-marker cap still gets its circle (and its existing
 * click handler). Pass an empty array to restore the circles for everyone.
 * Clusters are never affected.
 */
export function setDomMarkedStations(map: maplibregl.Map, markedIds: string[]) {
  const notCluster: any[] = ['!', ['has', 'point_count']];
  const notMarked: any[] | null = markedIds.length
    ? ['!', ['in', ['get', 'id'], ['literal', markedIds]]]
    : null;
  const withExclusion = (...extra: any[]) => ['all', notCluster, ...extra, ...(notMarked ? [notMarked] : [])] as any;

  [UNCLUSTERED_RING_LAYER_ID, UNCLUSTERED_BASE_LAYER_ID, UNCLUSTERED_CORE_LAYER_ID].forEach((layerId) => {
    if (map.getLayer(layerId)) map.setFilter(layerId, withExclusion());
  });
  // The static anomaly halo keeps its own predicate; the DOM marker's radar
  // replaces it for marked stations.
  if (map.getLayer(ANOMALY_PULSE_LAYER_ID)) {
    map.setFilter(ANOMALY_PULSE_LAYER_ID, withExclusion(['==', ['get', 'hasAnomaly'], 1]));
  }
}

/** Hides the native cyan selection ring when the selected station is drawn as a
 * DOM marker (the marker carries its own selected glow); restores it otherwise. */
export function setSelectedHaloSuppressed(map: maplibregl.Map, suppressed: boolean) {
  if (!map.getLayer(SELECTED_HALO_LAYER_ID)) return;
  map.setPaintProperty(SELECTED_HALO_LAYER_ID, 'circle-opacity', suppressed ? 0 : 1);
  map.setPaintProperty(SELECTED_HALO_LAYER_ID, 'circle-stroke-opacity', suppressed ? 0 : 1);
}

// ─────────────────────────────────────────────────────────────────────────
// Three-neighbor validation: connection lines + neighbor highlight markers.
// Native MapLibre GeoJSON source/layers -- geo-attachment, pan/zoom/rotate
// tracking, and rendering are all handled by the map itself, exactly like
// every other station layer above. No separate positioning system.
// ─────────────────────────────────────────────────────────────────────────

export const NEIGHBOR_LINES_SOURCE_ID = 'ather-neighbor-lines-source';
export const NEIGHBOR_LINES_GLOW_LAYER_ID = 'ather-neighbor-lines-glow';
export const NEIGHBOR_LINES_LAYER_ID = 'ather-neighbor-lines';
export const NEIGHBOR_HIGHLIGHT_SOURCE_ID = 'ather-neighbor-highlight-source';
export const NEIGHBOR_HIGHLIGHT_LAYER_ID = 'ather-neighbor-highlight';

const NEIGHBOR_LINE_OPACITY = 0.85;
const NEIGHBOR_LINE_GLOW_OPACITY = 0.14;

export function ensureNeighborLayers(map: maplibregl.Map) {
  if (!map.getSource(NEIGHBOR_LINES_SOURCE_ID)) {
    map.addSource(NEIGHBOR_LINES_SOURCE_ID, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });
  }
  if (!map.getSource(NEIGHBOR_HIGHLIGHT_SOURCE_ID)) {
    map.addSource(NEIGHBOR_HIGHLIGHT_SOURCE_ID, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });
  }

  // Soft glow beneath the crisp line -- thin and understated, not a thick bar.
  if (!map.getLayer(NEIGHBOR_LINES_GLOW_LAYER_ID)) {
    map.addLayer({
      id: NEIGHBOR_LINES_GLOW_LAYER_ID,
      type: 'line',
      source: NEIGHBOR_LINES_SOURCE_ID,
      paint: {
        'line-color': '#00e5ff',
        'line-width': 5,
        'line-opacity': 0,
        'line-blur': 3
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' }
    });
  }
  if (!map.getLayer(NEIGHBOR_LINES_LAYER_ID)) {
    map.addLayer({
      id: NEIGHBOR_LINES_LAYER_ID,
      type: 'line',
      source: NEIGHBOR_LINES_SOURCE_ID,
      paint: {
        'line-color': '#00e5ff',
        'line-width': 1.5,
        'line-opacity': 0
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' }
    });
  }
  // Neighbor highlight ring -- distinguishes the 3 nearest stations from
  // every other unclustered marker without replacing the marker itself.
  if (!map.getLayer(NEIGHBOR_HIGHLIGHT_LAYER_ID)) {
    map.addLayer({
      id: NEIGHBOR_HIGHLIGHT_LAYER_ID,
      type: 'circle',
      source: NEIGHBOR_HIGHLIGHT_SOURCE_ID,
      paint: {
        'circle-color': 'rgba(0, 229, 255, 0.0)',
        'circle-radius': 12,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#00e5ff',
        // Drawn on the DOM marker itself (`is-neighbor`, a thin ground ring) instead of a cyan
        // circle around it; the layer stays so nothing that references it breaks.
        'circle-stroke-opacity': 0
      }
    });
  }
}

export interface NeighborLinePoint {
  lng: number;
  lat: number;
}

/** Draws primary->neighbor connection lines and highlights the neighbor markers. */
export function updateNeighborConnections(
  map: maplibregl.Map,
  primary: NeighborLinePoint,
  neighbors: NeighborLinePoint[]
) {
  ensureNeighborLayers(map);

  const lineFeatures: GeoJSON.Feature[] = neighbors.map((n) => ({
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'LineString',
      coordinates: [
        [primary.lng, primary.lat],
        [n.lng, n.lat]
      ]
    }
  }));

  const pointFeatures: GeoJSON.Feature[] = neighbors.map((n) => ({
    type: 'Feature',
    properties: {},
    geometry: { type: 'Point', coordinates: [n.lng, n.lat] }
  }));

  const linesSrc = map.getSource(NEIGHBOR_LINES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  linesSrc?.setData({ type: 'FeatureCollection', features: lineFeatures });

  const highlightSrc = map.getSource(NEIGHBOR_HIGHLIGHT_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  highlightSrc?.setData({ type: 'FeatureCollection', features: pointFeatures });

  animateNeighborLinesIn(map);
}

export function clearNeighborConnections(map: maplibregl.Map) {
  const linesSrc = map.getSource(NEIGHBOR_LINES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  linesSrc?.setData({ type: 'FeatureCollection', features: [] });
  const highlightSrc = map.getSource(NEIGHBOR_HIGHLIGHT_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  highlightSrc?.setData({ type: 'FeatureCollection', features: [] });
}

/** Subtle "lines drawing outward" fade-in when a primary station is selected. */
function animateNeighborLinesIn(map: maplibregl.Map, durationMs = 600) {
  const start = performance.now();
  function step(now: number) {
    if (!map.getLayer(NEIGHBOR_LINES_LAYER_ID)) return;
    // rAF timestamps can precede performance.now(): clamp so opacity is never negative
    const t = Math.max(0, Math.min(1, (now - start) / durationMs));
    const eased = 1 - Math.pow(1 - t, 3);
    map.setPaintProperty(NEIGHBOR_LINES_LAYER_ID, 'line-opacity', NEIGHBOR_LINE_OPACITY * eased);
    map.setPaintProperty(NEIGHBOR_LINES_GLOW_LAYER_ID, 'line-opacity', NEIGHBOR_LINE_GLOW_OPACITY * eased);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
