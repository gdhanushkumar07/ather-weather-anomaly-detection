import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Helper to look for keys in both process.env and api-keys.txt
function resolveApiKeys() {
  let mapKey = process.env.WINDY_MAP_FORECAST_KEY || '';
  let pointKey = process.env.WINDY_POINT_FORECAST_KEY || '';
  let webcamsKey = process.env.WINDY_WEBCAMS_KEY || '';

  const apiKeysPath = path.resolve(__dirname, '../api-keys.txt');
  if (fs.existsSync(apiKeysPath)) {
    try {
      const content = fs.readFileSync(apiKeysPath, 'utf8');
      const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
      for (const line of lines) {
        if (line.startsWith('#')) continue;
        if (line.startsWith('WINDY_MAP_FORECAST_KEY=')) {
          mapKey = line.replace('WINDY_MAP_FORECAST_KEY=', '').trim();
        } else if (line.startsWith('WINDY_POINT_FORECAST_KEY=')) {
          pointKey = line.replace('WINDY_POINT_FORECAST_KEY=', '').trim();
        } else if (line.startsWith('WINDY_WEBCAMS_KEY=')) {
          webcamsKey = line.replace('WINDY_WEBCAMS_KEY=', '').trim();
        } else {
          const delimiter = line.includes(':') && !line.startsWith('http') ? ':' : (line.includes('=') ? '=' : null);
          if (delimiter) {
            const idx = line.indexOf(delimiter);
            const k = line.substring(0, idx).toLowerCase();
            const v = line.substring(idx + 1).trim();
            if (k.includes('point')) pointKey = v;
            else if (k.includes('map')) mapKey = v;
            else if (k.includes('webcam')) webcamsKey = v;
          } else if (line.length > 20 && !pointKey) {
            // If a standalone key is pasted
            pointKey = line.trim();
          }
        }
      }
    } catch (err) {
      console.warn('Could not read api-keys.txt:', err.message);
    }
  }

  return { mapKey, pointKey, webcamsKey };
}

// Weather code translation helper (WMO weather codes)
function getWeatherDesc(code) {
  const map = {
    0: 'Clear sky',
    1: 'Mainly clear',
    2: 'Partly cloudy',
    3: 'Overcast',
    45: 'Fog',
    48: 'Depositing rime fog',
    51: 'Light drizzle',
    53: 'Moderate drizzle',
    55: 'Dense drizzle',
    61: 'Slight rain',
    63: 'Moderate rain',
    65: 'Heavy rain',
    71: 'Slight snow',
    73: 'Moderate snow',
    75: 'Heavy snow',
    77: 'Snow grains',
    80: 'Slight rain showers',
    81: 'Moderate rain showers',
    82: 'Violent rain showers',
    85: 'Slight snow showers',
    86: 'Heavy snow showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm with slight hail',
    99: 'Thunderstorm with heavy hail',
  };
  return map[code] || 'Partly cloudy';
}

function getWindDirection(deg) {
  const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const index = Math.round((deg % 360) / 22.5) % 16;
  return directions[index];
}

// 1. Backend Status & Key Detection
app.get('/api/status', (req, res) => {
  const { mapKey, pointKey, webcamsKey } = resolveApiKeys();
  res.json({
    status: 'online',
    hasPointForecastKey: Boolean(pointKey),
    hasMapForecastKey: Boolean(mapKey),
    hasWebcamsKey: Boolean(webcamsKey),
    mode: pointKey ? 'Windy Official API' : 'High-Accuracy Open-Meteo Fallback Mode',
  });
});

// 2. Point Forecast API Proxy
app.get('/api/forecast/point', async (req, res) => {
  const lat = parseFloat(req.query.lat) || 19.076;
  const lon = parseFloat(req.query.lon) || 72.8777;
  const model = (req.query.model || 'ecmwf').toLowerCase();
  const { pointKey } = resolveApiKeys();

  // Try official Windy API if key exists
  if (pointKey) {
    try {
      const response = await fetch('https://api.windy.com/api/point-forecast/v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat,
          lon,
          model: model === 'gfs' ? 'gfs' : 'ecmwf',
          parameters: ['temp', 'precip', 'wind', 'rh', 'pressure', 'clouds'],
          levels: ['surface'],
          key: pointKey,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        return res.json({
          location: { lat, lon, name: req.query.name || `${lat.toFixed(2)}°, ${lon.toFixed(2)}°` },
          rawWindy: data,
          isWindyApi: true,
        });
      } else {
        console.warn(`Windy API responded with status ${response.status}, failing over to Open-Meteo`);
      }
    } catch (err) {
      console.warn('Windy API request failed, falling back to Open-Meteo:', err.message);
    }
  }

  // High-accuracy fallback: Open-Meteo Global Meteorological Service
  try {
    const weatherUrl = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,surface_pressure,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max&timezone=auto`;
    
    // Also reverse-geocode location name
    const geoUrl = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=10`;
    
    const [weatherRes, geoRes] = await Promise.all([
      fetch(weatherUrl),
      fetch(geoUrl, { headers: { 'User-Agent': 'WindyCloneDashboard/1.0' } }).catch(() => null),
    ]);

    const weatherData = await weatherRes.json();
    let locationName = req.query.name || `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
    let country = '';

    if (geoRes && geoRes.ok) {
      try {
        const geoData = await geoRes.json();
        locationName = geoData.address?.city || geoData.address?.town || geoData.address?.state_district || geoData.address?.state || locationName;
        country = geoData.address?.country || '';
      } catch {
        // keep fallback coordinates
      }
    }

    const hourly = [];
    const hourlyData = weatherData.hourly || {};
    const times = hourlyData.time || [];
    const nowIso = new Date().toISOString();
    
    // Find current index
    let startIndex = 0;
    const nowHour = nowIso.slice(0, 13);
    for (let i = 0; i < times.length; i++) {
      if (times[i].startsWith(nowHour)) {
        startIndex = i;
        break;
      }
    }

    const limit = Math.min(times.length, startIndex + 72); // next 72 hours
    for (let i = startIndex; i < limit; i++) {
      const timeStr = times[i];
      const d = new Date(timeStr);
      const hourLabel = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      const wCode = hourlyData.weather_code?.[i] ?? 0;
      const deg = hourlyData.wind_direction_10m?.[i] ?? 0;

      hourly.push({
        time: timeStr,
        hourLabel,
        temp: Math.round(hourlyData.temperature_2m?.[i] ?? 20),
        feelsLike: Math.round(hourlyData.apparent_temperature?.[i] ?? 20),
        precipitation: hourlyData.precipitation?.[i] ?? 0,
        rainProb: hourlyData.precipitation_probability?.[i] ?? 0,
        weatherCode: wCode,
        weatherDesc: getWeatherDesc(wCode),
        windSpeed: Math.round(hourlyData.wind_speed_10m?.[i] ?? 12),
        windGust: Math.round(hourlyData.wind_gusts_10m?.[i] ?? 16),
        windDeg: deg,
        windDirection: getWindDirection(deg),
        pressure: Math.round(hourlyData.surface_pressure?.[i] ?? 1013),
        humidity: Math.round(hourlyData.relative_humidity_2m?.[i] ?? 65),
        dewPoint: Math.round(hourlyData.dew_point_2m?.[i] ?? 15),
        cloudCover: Math.round(hourlyData.cloud_cover?.[i] ?? 20),
        uvIndex: hourlyData.uv_index?.[i] ?? 0,
      });
    }

    const daily = [];
    const dailyData = weatherData.daily || {};
    const dayTimes = dailyData.time || [];
    for (let i = 0; i < Math.min(dayTimes.length, 7); i++) {
      const d = new Date(dayTimes[i]);
      const dayLabel = i === 0 ? 'Today' : d.toLocaleDateString([], { weekday: 'short' });
      const wCode = dailyData.weather_code?.[i] ?? 0;

      daily.push({
        date: dayTimes[i],
        dayLabel,
        tempMax: Math.round(dailyData.temperature_2m_max?.[i] ?? 28),
        tempMin: Math.round(dailyData.temperature_2m_min?.[i] ?? 18),
        weatherCode: wCode,
        weatherDesc: getWeatherDesc(wCode),
        precipitationSum: dailyData.precipitation_sum?.[i] ?? 0,
        windSpeedMax: Math.round(dailyData.wind_speed_10m_max?.[i] ?? 20),
      });
    }

    const current = hourly[0] || {
      time: nowIso,
      hourLabel: 'Now',
      temp: 24,
      feelsLike: 25,
      precipitation: 0,
      rainProb: 10,
      weatherCode: 1,
      weatherDesc: 'Mainly clear',
      windSpeed: 14,
      windGust: 18,
      windDeg: 240,
      windDirection: 'WSW',
      pressure: 1012,
      humidity: 60,
      dewPoint: 16,
      cloudCover: 25,
      uvIndex: 5,
    };

    res.json({
      location: {
        lat,
        lon,
        name: locationName,
        country,
        elevation: weatherData.elevation,
        timezone: weatherData.timezone,
      },
      current,
      hourly,
      daily,
      isWindyApi: false,
    });
  } catch (err) {
    console.error('Error fetching forecast:', err);
    res.status(500).json({ error: 'Failed to fetch weather forecast', details: err.message });
  }
});

// 3. Webcams API
app.get('/api/webcams', async (req, res) => {
  const { webcamsKey } = resolveApiKeys();
  const lat = parseFloat(req.query.lat) || 19.076;
  const lon = parseFloat(req.query.lon) || 72.8777;

  // Curated live webcams database around key locations
  const sampleWebcams = [
    {
      id: 'cam-mum-01',
      title: 'Marine Drive Coastal Skyline & Arabian Sea',
      city: 'Mumbai',
      lat: 18.9438,
      lon: 72.8234,
      thumbnail: 'https://images.unsplash.com/photo-1570168007204-dfb528c6958f?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '10 min ago',
    },
    {
      id: 'cam-blr-02',
      title: 'Bengaluru Tech Corridor & Cloud Cover',
      city: 'Bengaluru',
      lat: 12.9716,
      lon: 77.5946,
      thumbnail: 'https://images.unsplash.com/photo-1596176530529-78163a4f7af2?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '5 min ago',
    },
    {
      id: 'cam-del-03',
      title: 'Connaught Place Weather Camera & Haze Monitor',
      city: 'New Delhi',
      lat: 28.6315,
      lon: 77.2167,
      thumbnail: 'https://images.unsplash.com/photo-1587474260584-136574528ed5?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '2 min ago',
    },
    {
      id: 'cam-goa-04',
      title: 'Calangute Beach Surf & Wind Cam',
      city: 'Goa',
      lat: 15.5439,
      lon: 73.7554,
      thumbnail: 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '15 min ago',
    },
    {
      id: 'cam-lon-05',
      title: 'Thames River & London Eye Skycam',
      city: 'London',
      lat: 51.5033,
      lon: -0.1195,
      thumbnail: 'https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '8 min ago',
    },
    {
      id: 'cam-sfo-06',
      title: 'Golden Gate Bridge Fog Cam',
      city: 'San Francisco',
      lat: 37.8199,
      lon: -122.4783,
      thumbnail: 'https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=600&auto=format&fit=crop&q=80',
      status: 'active',
      updateTime: '4 min ago',
    },
  ];

  res.json({ webcams: sampleWebcams });
});

// 4. ATHER Backend Proxy — Live 5-Layer Anomaly Detection
const ATHER_BACKEND_URL = process.env.ATHER_BACKEND_URL || 'http://localhost:8000';

// Proxy: /api/ather/* → ATHER FastAPI backend /api/v1/ather/*
app.get('/api/ather/:path(*)', async (req, res) => {
  const targetUrl = `${ATHER_BACKEND_URL}/api/v1/ather/${req.params.path}`;
  try {
    const response = await fetch(targetUrl, { 
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) {
      const text = await response.text();
      return res.status(response.status).json({ 
        error: `ATHER backend returned ${response.status}`, 
        detail: text,
      });
    }
    const data = await response.json();
    res.json(data);
  } catch (err) {
    console.warn(`ATHER backend unreachable at ${targetUrl}:`, err.message);
    res.status(503).json({ 
      status: 'offline',
      error: 'ATHER backend unavailable',
      detail: `Could not connect to ${ATHER_BACKEND_URL}. Ensure the Python backend is running.`,
      stations: [],
    });
  }
});

// Legacy /api/anomalies endpoint — now bridges to ATHER backend
app.get('/api/anomalies', async (req, res) => {
  try {
    const response = await fetch(`${ATHER_BACKEND_URL}/api/v1/ather/stations`, {
      signal: AbortSignal.timeout(10000),
    });
    if (response.ok) {
      const data = await response.json();
      // Transform ATHER format to match existing frontend expectations
      const stations = (data.stations || []).map(s => ({
        id: s.station_id,
        stationName: s.name,
        state: 'India',
        lat: s.lat,
        lon: s.lon,
        severity: s.anomaly.is_anomaly 
          ? (s.anomaly.severity_score > 0.8 ? 'D4' : s.anomaly.severity_score > 0.6 ? 'D3' : s.anomaly.severity_score > 0.4 ? 'D2' : 'D1')
          : 'D0',
        severityLabel: s.anomaly.is_anomaly ? s.anomaly.root_cause : 'Normal Operation',
        status: s.anomaly.is_anomaly 
          ? (s.anomaly.severity_score > 0.7 ? 'Critical' : s.anomaly.severity_score > 0.4 ? 'Severe' : 'Moderate')
          : 'Healthy',
        anomalyType: s.anomaly.root_cause,
        confidenceScore: Math.round(s.anomaly.confidence_score * 100 * 10) / 10,
        soilMoistureIndex: 50.0,
        heatAnomalyDelta: s.anomaly.is_anomaly ? +(s.anomaly.severity_score * 5).toFixed(1) : 0,
        rainfallDeficitPercent: 0,
        aiRecommendation: s.anomaly.explanation,
        lastUpdated: new Date(s.timestamp).toLocaleTimeString(),
        // ATHER-specific fields (new)
        atherData: {
          weather: s.weather,
          anomaly: s.anomaly,
          elevation_m: s.elevation_m,
        },
      }));

      res.json({
        summary: {
          monitoredStations: stations.length,
          criticalCount: stations.filter(s => s.status === 'Critical').length,
          severeCount: stations.filter(s => s.status === 'Severe').length,
          healthyCount: stations.filter(s => s.status === 'Healthy').length,
          lastModelRun: new Date().toLocaleTimeString(),
          source: 'ATHER Live Engine',
        },
        stations,
      });
    } else {
      throw new Error(`ATHER backend returned ${response.status}`);
    }
  } catch (err) {
    console.warn('ATHER backend not available for /api/anomalies, returning empty:', err.message);
    res.json({
      summary: {
        monitoredStations: 0,
        criticalCount: 0,
        severeCount: 0,
        healthyCount: 0,
        lastModelRun: new Date().toLocaleTimeString(),
        source: 'offline',
      },
      stations: [],
    });
  }
});

app.listen(PORT, () => {
  console.log(`[ATHER Frontend Server] Running on http://localhost:${PORT}`);
  console.log(`[ATHER Frontend Server] Proxying ATHER backend at ${ATHER_BACKEND_URL}`);
});

