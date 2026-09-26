import type maplibregl from 'maplibre-gl';

const SOURCE_ID = 'ather-graticule';
const GRID_LAYER_ID = 'ather-graticule-lines';
const EQUATOR_LAYER_ID = 'ather-graticule-equator';

const STEP_DEG = 15;
const SAMPLE_DEG = 2; // points along each line, so lines curve smoothly on the globe

function buildGraticule(): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const features: GeoJSON.Feature<GeoJSON.LineString>[] = [];

  // Meridians (constant longitude), pole to pole.
  for (let lng = -180; lng < 180; lng += STEP_DEG) {
    const coords: [number, number][] = [];
    for (let lat = -90; lat <= 90; lat += SAMPLE_DEG) coords.push([lng, lat]);
    features.push({ type: 'Feature', properties: { kind: 'meridian' }, geometry: { type: 'LineString', coordinates: coords } });
  }

  // Parallels (constant latitude); the poles themselves are points, so skip them.
  for (let lat = -90 + STEP_DEG; lat < 90; lat += STEP_DEG) {
    const coords: [number, number][] = [];
    for (let lng = -180; lng <= 180; lng += SAMPLE_DEG) coords.push([lng, lat]);
    features.push({
      type: 'Feature',
      properties: { kind: lat === 0 ? 'equator' : 'parallel' },
      geometry: { type: 'LineString', coordinates: coords }
    });
  }

  return { type: 'FeatureCollection', features };
}

/**
 * Adds latitude/longitude grid lines (every 15 degrees) with a brighter
 * equator. They fade out as you zoom toward station level so they never
 * clutter the flat map. Idempotent -- safe to call again after a style reload.
 */
export function setupGraticule(map: maplibregl.Map): void {
  if (map.getSource(SOURCE_ID)) return;

  map.addSource(SOURCE_ID, { type: 'geojson', data: buildGraticule() });

  const fade = (max: number) => ['interpolate', ['linear'], ['zoom'], 3.5, max, 6.5, 0] as any;

  map.addLayer({
    id: GRID_LAYER_ID,
    type: 'line',
    source: SOURCE_ID,
    filter: ['!=', ['get', 'kind'], 'equator'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': 0.7, 'line-opacity': fade(0.22) }
  });

  map.addLayer({
    id: EQUATOR_LAYER_ID,
    type: 'line',
    source: SOURCE_ID,
    filter: ['==', ['get', 'kind'], 'equator'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': 1.3, 'line-opacity': fade(0.6) }
  });
}
