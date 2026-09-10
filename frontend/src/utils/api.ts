import { AtherStationData } from '../types/weather';
import * as servicesApi from '../services/api';

export * from '../services/api';

export async function fetchAtherStations(): Promise<{ stations: AtherStationData[] }> {
  try {
    const geojson = await servicesApi.fetchStationsGeoJSON();
    const stations: AtherStationData[] = (geojson.features || []).map((f: any) => {
      const p = f.properties || {};
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const isAnomaly = p.hasAnomaly === 1 || p.status === 'ANOMALY';
      const isWarning = p.status === 'WARNING';
      const severityScore = isAnomaly ? 0.88 : (isWarning ? 0.45 : 0.05);

      return {
        station_id: p.id,
        id: p.id,
        name: p.name || `Station ${p.id}`,
        town: p.town || '',
        country: p.country || 'India',
        region: p.region || '',
        lat,
        lon,
        latitude: lat,
        longitude: lon,
        weather: {
          temperature_c: p.temperature ?? 24.5,
          humidity_pct: p.humidity ?? 55,
          pressure_hpa: p.pressure ?? 1013.25,
          wind_kph: p.windSpeed ?? 12.0,
          condition: p.condition ?? 'Reported',
        },
        temperature: p.temperature ?? 24.5,
        pressure: p.pressure,
        humidity: p.humidity,
        windSpeed: p.windSpeed,
        windDirection: p.windDirection,
        condition: p.condition ?? 'Reported',
        status: p.status || (isAnomaly ? 'ANOMALY' : 'NORMAL'),
        anomaly: {
          is_anomaly: isAnomaly,
          severity_score: severityScore,
          severity_label: p.severity || (isAnomaly ? 'HIGH' : 'NORMAL'),
          root_cause: isAnomaly ? 'Sensor Anomaly' : 'None',
          explanation: isAnomaly ? `Anomaly detected in telemetry from ${p.name}` : undefined,
        },
      };
    });
    return { stations };
  } catch (err) {
    console.warn('fetchAtherStations: fallback due to error:', err);
    return { stations: [] };
  }
}
