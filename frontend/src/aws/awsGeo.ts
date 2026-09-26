import { calculateHaversineDistance } from '../utils/atherEngine';

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
 * nothing here is invented). Reuses the project's existing Haversine
 * implementation (utils/atherEngine.ts) rather than a second one.
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
      distanceKm: calculateHaversineDistance(primaryLat, primaryLng, lat, lng),
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

export interface ParamComparison {
  parameter: string;
  unit: string;
  primaryValue: number | null;
  neighborAverage: number | null;
  delta: number | null;
}

function average(values: (number | null)[]): number | null {
  const valid = values.filter((v): v is number => v !== null);
  if (valid.length === 0) return null;
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

function buildComparison(
  parameter: string,
  unit: string,
  primaryValue: number | null | undefined,
  neighborValues: (number | null)[]
): ParamComparison {
  const neighborAverage = average(neighborValues);
  const primary = primaryValue ?? null;
  return {
    parameter,
    unit,
    primaryValue: primary,
    neighborAverage,
    delta: primary !== null && neighborAverage !== null ? primary - neighborAverage : null,
  };
}

/** Real primary-vs-neighbor comparison, built entirely from actual station telemetry. */
export function compareToNeighbors(
  primaryTemp: number | null | undefined,
  primaryPressure: number | null | undefined,
  primaryHumidity: number | null | undefined,
  neighbors: AWSNeighbor[]
): ParamComparison[] {
  return [
    buildComparison('Temperature', '°C', primaryTemp, neighbors.map((n) => n.temperature)),
    buildComparison('Pressure', 'hPa', primaryPressure, neighbors.map((n) => n.pressure)),
    buildComparison('Relative Humidity', '%', primaryHumidity, neighbors.map((n) => n.humidity)),
  ];
}

export type ValidationVerdict = 'CONSISTENT' | 'SUSPICIOUS' | 'ANOMALOUS' | 'INSUFFICIENT_DATA';

// Deliberately conservative, clearly-labeled client-side heuristic -- this is
// NOT the backend's 5-layer/spatial-consensus algorithm (see engine/layer4_spatial.py),
// which computes IDW consensus server-side. This only summarizes the plain
// primary-vs-neighbor-average deltas above in the UI; the panel keeps the
// real backend Spatial Consensus layer card as the authoritative source.
export function deriveValidationVerdict(comparisons: ParamComparison[]): ValidationVerdict {
  const withDelta = comparisons.filter((c) => c.delta !== null);
  if (withDelta.length === 0) return 'INSUFFICIENT_DATA';

  const thresholds: Record<string, number> = {
    Temperature: 5.0,
    Pressure: 15.0,
    'Relative Humidity': 25.0,
  };

  let flagged = 0;
  for (const c of withDelta) {
    const t = thresholds[c.parameter] ?? Infinity;
    if (Math.abs(c.delta as number) > t) flagged++;
  }

  if (flagged === 0) return 'CONSISTENT';
  if (flagged === 1) return 'SUSPICIOUS';
  return 'ANOMALOUS';
}

export interface NeighborCheckResult {
  neighbor: AWSNeighbor;
  consistent: boolean;
  reason: string;
}

const NEIGHBOR_CHECK_THRESHOLDS: Record<string, number> = {
  temperature: 5.0, // °C
  pressure: 15.0, // hPa
  humidity: 25.0, // %
};

/**
 * Per-neighbor consistency check (as opposed to compareToNeighbors, which
 * compares the primary against the neighbor AVERAGE). Used for the
 * per-neighbor "✓ / ⚠" validation checklist -- real data per neighbor, same
 * conservative thresholds as deriveValidationVerdict.
 */
export function checkNeighborConsistency(
  primaryTemp: number | null | undefined,
  primaryPressure: number | null | undefined,
  primaryHumidity: number | null | undefined,
  neighbor: AWSNeighbor
): NeighborCheckResult {
  const flaggedDeltas: string[] = [];
  let checkedCount = 0;

  const check = (label: string, unit: string, key: 'temperature' | 'pressure' | 'humidity', primary: number | null | undefined, neighborVal: number | null) => {
    if (primary === null || primary === undefined || neighborVal === null) return;
    checkedCount++;
    const delta = Math.abs(primary - neighborVal);
    if (delta > NEIGHBOR_CHECK_THRESHOLDS[key]) {
      flaggedDeltas.push(`${label} Δ${delta.toFixed(1)}${unit}`);
    }
  };

  check('T', '°C', 'temperature', primaryTemp, neighbor.temperature);
  check('P', 'hPa', 'pressure', primaryPressure, neighbor.pressure);
  check('RH', '%', 'humidity', primaryHumidity, neighbor.humidity);

  if (checkedCount === 0) {
    return { neighbor, consistent: true, reason: 'Insufficient overlapping data to compare' };
  }
  return {
    neighbor,
    consistent: flaggedDeltas.length === 0,
    reason: flaggedDeltas.length === 0 ? 'Within expected range of primary' : flaggedDeltas.join(', '),
  };
}
