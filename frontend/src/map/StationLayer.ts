import maplibregl from 'maplibre-gl';

export const STATIONS_SOURCE_ID = 'ather-stations-source';
export const CLUSTERS_LAYER_ID = 'ather-clusters';
export const CLUSTER_COUNT_LAYER_ID = 'ather-cluster-count';
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
      cluster: true,
      clusterMaxZoom: 11,
      clusterRadius: 45
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
        'circle-radius': [
          'step',
          ['get', 'point_count'],
          14,
          20,
          18,
          100,
          23
        ],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#00e5ff',
        'circle-opacity': 0.98
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
        'circle-radius': 13,
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
        'circle-radius': 15,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#00e5ff'
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
        'circle-radius': 4,
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
        'circle-radius': 2.2,
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

    // Hover cursor changes
    map.on('mouseenter', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
    map.on('mouseenter', UNCLUSTERED_RING_LAYER_ID, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', UNCLUSTERED_RING_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
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
    ANOMALY_PULSE_LAYER_ID,
    SELECTED_HALO_LAYER_ID,
    UNCLUSTERED_RING_LAYER_ID,
    UNCLUSTERED_BASE_LAYER_ID,
    UNCLUSTERED_CORE_LAYER_ID
  ].forEach((layerId) => {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  });
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
        'circle-stroke-opacity': 0.9
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
    const t = Math.min(1, (now - start) / durationMs);
    const eased = 1 - Math.pow(1 - t, 3);
    map.setPaintProperty(NEIGHBOR_LINES_LAYER_ID, 'line-opacity', NEIGHBOR_LINE_OPACITY * eased);
    map.setPaintProperty(NEIGHBOR_LINES_GLOW_LAYER_ID, 'line-opacity', NEIGHBOR_LINE_GLOW_OPACITY * eased);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
