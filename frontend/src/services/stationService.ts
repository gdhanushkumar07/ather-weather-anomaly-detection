/**
 * NOAA Integrated Surface Database (ISD) Station Service & Open-Meteo Live Observations
 * High-Performance Edition:
 * - In-memory Open-Meteo cache (15 min TTL)
 * - Single-request concurrency with AbortController cancellation
 * - Precomputed global Level 1 grid aggregation (15°x15° geographic density cells)
 * - Fast search indexing
 */

import { GlobalWeatherStation, StationLiveWeather } from '../types';

export interface GridDensityCell {
  cellId: string;
  lat: number;
  lon: number;
  count: number;
  sampleStation?: GlobalWeatherStation;
}

let cachedStations: GlobalWeatherStation[] | null = null;
let stationPromise: Promise<GlobalWeatherStation[]> | null = null;
let precomputedGridCells: GridDensityCell[] | null = null;

// Search index cache
interface SearchIndexEntry {
  idLower: string;
  nameLower: string;
  countryLower: string;
  icaoLower: string;
  station: GlobalWeatherStation;
}
let searchIndexCache: SearchIndexEntry[] | null = null;

// Open-Meteo Cache & Concurrency
const weatherCache = new Map<string, { data: StationLiveWeather; timestamp: number }>();
const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes
let activeWeatherAbortController: AbortController | null = null;
let totalOpenMeteoRequests = 0;

export function getOpenMeteoRequestCount(): number {
  return totalOpenMeteoRequests;
}

/**
 * Loads the global NOAA ISD station dataset generated from isd-history.csv.
 */
export async function loadGlobalStations(): Promise<GlobalWeatherStation[]> {
  if (cachedStations) {
    return cachedStations;
  }
  if (stationPromise) {
    return stationPromise;
  }

  stationPromise = (async () => {
    try {
      const response = await fetch('/data/stations.json');
      if (!response.ok) {
        throw new Error(`Failed to load stations dataset: HTTP ${response.status}`);
      }
      const data: GlobalWeatherStation[] = await response.json();
      cachedStations = data;

      // Build Level 1 Coarse Grid Aggregation once
      buildGridAggregation(data);

      // Build Fast Search Index once
      buildSearchIndex(data);

      return data;
    } catch (err) {
      stationPromise = null;
      console.error('Error loading global NOAA stations dataset:', err);
      throw err;
    }
  })();

  return stationPromise;
}

/**
 * Builds Level 1 geographic grid cells (~15° x 15° lat/lon).
 * Results in ~120-180 aggregate density circles globally.
 */
function buildGridAggregation(stations: GlobalWeatherStation[]) {
  const cellSize = 15;
  const gridMap = new Map<string, { count: number; sumLat: number; sumLon: number; sample: GlobalWeatherStation }>();

  for (let i = 0; i < stations.length; i++) {
    const s = stations[i];
    const gridX = Math.floor((s.lon + 180) / cellSize);
    const gridY = Math.floor((s.lat + 90) / cellSize);
    const key = `${gridX}_${gridY}`;

    const existing = gridMap.get(key);
    if (existing) {
      existing.count++;
      existing.sumLat += s.lat;
      existing.sumLon += s.lon;
    } else {
      gridMap.set(key, {
        count: 1,
        sumLat: s.lat,
        sumLon: s.lon,
        sample: s,
      });
    }
  }

  const cells: GridDensityCell[] = [];
  gridMap.forEach((val, key) => {
    cells.push({
      cellId: `grid-${key}`,
      lat: Math.round((val.sumLat / val.count) * 100) / 100,
      lon: Math.round((val.sumLon / val.count) * 100) / 100,
      count: val.count,
      sampleStation: val.sample,
    });
  });

  precomputedGridCells = cells;
}

export function getGlobalGridCells(): GridDensityCell[] {
  return precomputedGridCells || [];
}

/**
 * Builds a fast lightweight search index for instantaneous matching
 */
function buildSearchIndex(stations: GlobalWeatherStation[]) {
  const index: SearchIndexEntry[] = new Array(stations.length);
  for (let i = 0; i < stations.length; i++) {
    const s = stations[i];
    index[i] = {
      idLower: s.id.toLowerCase(),
      nameLower: s.name.toLowerCase(),
      countryLower: s.country ? s.country.toLowerCase() : '',
      icaoLower: s.icao ? s.icao.toLowerCase() : '',
      station: s,
    };
  }
  searchIndexCache = index;
}

/**
 * Fetches real-time meteorological observations from Open-Meteo for a specific station.
 * - Keyless, official endpoint
 * - In-memory cached for 15 minutes
 * - Auto-cancels previous pending request if a new station is clicked
 */
export async function fetchStationWeather(
  stationId: string,
  lat: number,
  lon: number,
  forceRefresh = false
): Promise<StationLiveWeather> {
  // 1. Check in-memory cache
  if (!forceRefresh) {
    const cached = weatherCache.get(stationId);
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      return cached.data;
    }
  }

  // 2. Abort previous in-flight request
  if (activeWeatherAbortController) {
    try {
      activeWeatherAbortController.abort();
    } catch {
      // ignore
    }
  }
  activeWeatherAbortController = new AbortController();
  const signal = activeWeatherAbortController.signal;

  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,pressure_msl&timezone=auto`;

  totalOpenMeteoRequests++;
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`Weather data request failed with status ${res.status}`);
  }

  const data = await res.json();
  if (!data || !data.current) {
    throw new Error('Weather data unavailable');
  }

  const cur = data.current;
  const result: StationLiveWeather = {
    stationId,
    temperature: typeof cur.temperature_2m === 'number' ? cur.temperature_2m : 0,
    humidity: typeof cur.relative_humidity_2m === 'number' ? cur.relative_humidity_2m : 0,
    windSpeed: typeof cur.wind_speed_10m === 'number' ? cur.wind_speed_10m : 0,
    pressure: typeof cur.pressure_msl === 'number' ? cur.pressure_msl : 1013,
    fetchedAt: cur.time ? new Date(cur.time).toISOString() : new Date().toISOString(),
    raw: data,
  };

  weatherCache.set(stationId, { data: result, timestamp: Date.now() });
  return result;
}

/**
 * Fast search global stations by query using the prebuilt search index.
 */
export function searchStations(
  query: string,
  stations: GlobalWeatherStation[],
  maxResults = 12
): GlobalWeatherStation[] {
  if (!query || query.trim().length < 2) return [];

  const q = query.trim().toLowerCase();

  // Check if query is coordinates "lat, lon"
  const coordMatch = q.match(/^(-?\d+(\.\d+)?)[,\s]+(-?\d+(\.\d+)?)$/);
  if (coordMatch) {
    const lat = parseFloat(coordMatch[1]);
    const lon = parseFloat(coordMatch[3]);
    if (!isNaN(lat) && !isNaN(lon)) {
      return stations
        .map((s) => ({
          station: s,
          dist: Math.hypot(s.lat - lat, s.lon - lon),
        }))
        .sort((a, b) => a.dist - b.dist)
        .slice(0, maxResults)
        .map((x) => x.station);
    }
  }

  const index = searchIndexCache;
  if (!index) {
    return [];
  }

  const results: GlobalWeatherStation[] = [];
  const seenIds = new Set<string>();

  // Pass 1: exact ID, USAF, or ICAO match
  for (let i = 0; i < index.length; i++) {
    const entry = index[i];
    if (entry.idLower === q || entry.icaoLower === q) {
      results.push(entry.station);
      seenIds.add(entry.station.id);
      if (results.length >= maxResults) return results;
    }
  }

  // Pass 2: name starts with query
  for (let i = 0; i < index.length; i++) {
    const entry = index[i];
    if (!seenIds.has(entry.station.id) && entry.nameLower.startsWith(q)) {
      results.push(entry.station);
      seenIds.add(entry.station.id);
      if (results.length >= maxResults) return results;
    }
  }

  // Pass 3: name contains query or country code matches
  for (let i = 0; i < index.length; i++) {
    const entry = index[i];
    if (
      !seenIds.has(entry.station.id) &&
      (entry.nameLower.includes(q) || entry.idLower.includes(q) || entry.countryLower === q)
    ) {
      results.push(entry.station);
      seenIds.add(entry.station.id);
      if (results.length >= maxResults) return results;
    }
  }

  return results;
}

/**
 * Formats coordinates in meteorological standard representation (e.g. 17.38° N, 78.48° E).
 */
export function formatCoordinates(lat: number, lon: number): { latStr: string; lonStr: string } {
  const latDir = lat >= 0 ? 'N' : 'S';
  const lonDir = lon >= 0 ? 'E' : 'W';
  return {
    latStr: `${Math.abs(lat).toFixed(2)}° ${latDir}`,
    lonStr: `${Math.abs(lon).toFixed(2)}° ${lonDir}`,
  };
}
