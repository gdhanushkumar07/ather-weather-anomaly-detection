/** Great-circle distance in km (display geometry only — the backend's L4
 *  layer is the sole judge of spatial consistency). */
function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export interface AWSNeighbor {
  id: string;
  name: string;
  lng: number;
  lat: number;
  distanceKm: number;
  status: string;
  temperature: number | null;
  pressure: number | null;
  humidity: number | null;
}

/**
 * Finds the nearest N stations to a primary station using real coordinates
 * from the already-fetched station GeoJSON (all live backend stations --
 * nothing here is invented). Used to draw the selected station's
 * neighbour lines on the map.
 */
export function findNearestStations(
  primaryId: string,
  primaryLat: number,
  primaryLng: number,
  features: GeoJSON.Feature[],
  count: number = 3
): AWSNeighbor[] {
  const candidates: AWSNeighbor[] = [];

  for (const f of features) {
    const props = f.properties as Record<string, any> | null;
    if (!props || props.id === primaryId) continue;
    if (f.geometry.type !== 'Point') continue;

    const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates;
    if (typeof lat !== 'number' || typeof lng !== 'number' || Number.isNaN(lat) || Number.isNaN(lng)) continue;

    candidates.push({
      id: props.id,
      name: props.name || props.id,
      lng,
      lat,
      distanceKm: haversineKm(primaryLat, primaryLng, lat, lng),
      status: props.status || 'NORMAL',
      temperature: typeof props.temperature === 'number' ? props.temperature : null,
      // Pressure < 1 hPa is the backend's own missing-data sentinel (see schema.py) -- treat it as null here too.
      pressure: typeof props.pressure === 'number' && props.pressure >= 1.0 ? props.pressure : null,
      humidity: typeof props.humidity === 'number' ? props.humidity : null,
    });
  }

  candidates.sort((a, b) => a.distanceKm - b.distanceKm);
  return candidates.slice(0, count);
}
