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

    // Hover cursor changes
    map.on('mouseenter', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', CLUSTERS_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
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
