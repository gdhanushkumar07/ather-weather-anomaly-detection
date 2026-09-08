import { 
  PointForecastData, 
  WeatherModel, 
  LocationCoords, 
  WebcamItem, 
  AIAnomalyData,
  WindSpeedUnit,
  TempUnit,
  PressureUnit
} from '../types';

export async function fetchPointForecast(
  lat: number,
  lon: number,
  model: WeatherModel = 'ecmwf'
): Promise<PointForecastData> {
  try {
    const res = await fetch(`/api/weather/point?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}&model=${model}`);
    if (!res.ok) {
      throw new Error(`Forecast request failed with status ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.warn('API route failed, falling back to direct open-meteo provider:', err);
    return fetchDirectOpenMeteo(lat, lon, model);
  }
}

export async function searchCities(query: string): Promise<LocationCoords[]> {
  if (!query || query.trim().length < 2) return [];
  try {
    const res = await fetch(
      `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=6&language=en&format=json`
    );
    if (!res.ok) return [];
    const data = await res.json();
    if (!data.results) return [];
    return data.results.map((item: any) => ({
      name: item.name,
      country: item.country,
      admin1: item.admin1,
      lat: item.latitude,
      lon: item.longitude,
      elevation: item.elevation,
    }));
  } catch (e) {
    console.error('Error searching cities:', e);
    return [];
  }
}

export async function fetchWebcams(bbox?: { south: number; west: number; north: number; east: number }): Promise<WebcamItem[]> {
  try {
    const params = bbox 
      ? `?south=${bbox.south}&west=${bbox.west}&north=${bbox.north}&east=${bbox.east}`
      : '';
    const res = await fetch(`/api/weather/webcams${params}`);
    if (!res.ok) return getDefaultWebcams();
    return await res.json();
  } catch (err) {
    return getDefaultWebcams();
  }
}

export async function fetchAIAnomaly(lat: number, lon: number, weather?: any): Promise<AIAnomalyData> {
  try {
    const res = await fetch('/api/weather/anomalies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat, lon, weather }),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    // Fallback to local rule calculation below
  }
  return calculateLocalAnomaly(lat, lon, weather);
}

export function calculateLocalAnomaly(lat: number, lon: number, weather?: any): AIAnomalyData {
  const wind = weather?.windSpeed || 18;
  const temp = weather?.temp || 26;
  const precip = weather?.precipitation || 0;
  const pressure = weather?.pressure || 1012;

  let risk = 15;
  let level: AIAnomalyData['level'] = 'D0';
  let title = 'D0 - Normal / Minimal Risk';
  let desc = 'Atmospheric dynamics within seasonal climatic norms. No cyclonic or heat anomalies detected.';

  if (wind > 80 || pressure < 985 || precip > 50) {
    level = 'D5';
    risk = 94;
    title = 'D5 - Severe Cyclonic / Storm Anomaly';
    desc = 'Critical pressure depression and extreme gust velocity indicating high cyclonic circulation hazard.';
  } else if (wind > 55 || temp > 43 || precip > 30) {
    level = 'D4';
    risk = 82;
    title = 'D4 - Extreme Weather Alert';
    desc = 'High-velocity wind gusts and severe precipitation intensity flagged for immediate monitoring.';
  } else if (wind > 40 || temp > 38 || precip > 15) {
    level = 'D3';
    risk = 65;
    title = 'D3 - Elevated Anomaly';
    desc = 'Significant thermal or convective anomaly detected relative to multi-year baselines.';
  } else if (temp > 34 || precip > 8 || wind > 30) {
    level = 'D2';
    risk = 45;
    title = 'D2 - Moderate Meteorological Anomaly';
    desc = 'Moderate wind shear and elevated surface thermal signatures observed.';
  } else if (temp > 30 || wind > 22) {
    level = 'D1';
    risk = 28;
    title = 'D1 - Low / Developing Anomaly';
    desc = 'Slight deviation from average humidity and temperature indices.';
  }

  return {
    level,
    title,
    description: desc,
    riskScore: risk,
    factors: [
      {
        name: 'Wind Shear Velocity',
        value: `${wind.toFixed(1)} km/h`,
        severity: wind > 50 ? 'critical' : wind > 35 ? 'high' : wind > 20 ? 'moderate' : 'normal',
      },
      {
        name: 'Barometric Anomaly',
        value: `${pressure.toFixed(0)} hPa`,
        severity: pressure < 995 ? 'critical' : pressure < 1005 ? 'moderate' : 'normal',
      },
      {
        name: 'Thermal Deviation',
        value: `${temp.toFixed(1)} °C`,
        severity: temp > 40 ? 'critical' : temp > 35 ? 'high' : 'normal',
      },
      {
        name: 'Convective Precip Rate',
        value: `${precip.toFixed(1)} mm/h`,
        severity: precip > 25 ? 'critical' : precip > 10 ? 'high' : 'normal',
      },
    ],
    timestamp: new Date().toISOString(),
  };
}

export function getDefaultWebcams(): WebcamItem[] {
  return [
    {
      id: 'cam-1',
      title: 'Marine Drive Coastal Observatory',
      lat: 18.944,
      lon: 72.823,
      city: 'Mumbai',
      country: 'India',
      thumbnailUrl: 'https://images.unsplash.com/photo-1570168007204-dfb528c6958f?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1570168007204-dfb528c6958f?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-2',
      title: 'Hussain Sagar Lake Weather Cam',
      lat: 17.423,
      lon: 78.473,
      city: 'Hyderabad',
      country: 'India',
      thumbnailUrl: 'https://images.unsplash.com/photo-1605007493699-ce65834f8a00?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1605007493699-ce65834f8a00?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-3',
      title: 'Connaught Place Weather Station',
      lat: 28.632,
      lon: 77.219,
      city: 'New Delhi',
      country: 'India',
      thumbnailUrl: 'https://images.unsplash.com/photo-1587474260584-136574528ed5?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1587474260584-136574528ed5?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-4',
      title: 'Marina Beach Coastal Station',
      lat: 13.050,
      lon: 80.282,
      city: 'Chennai',
      country: 'India',
      thumbnailUrl: 'https://images.unsplash.com/photo-1582510003544-4d00b7f74220?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1582510003544-4d00b7f74220?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-5',
      title: 'Vidyasagar Setu Panorama',
      lat: 22.556,
      lon: 88.328,
      city: 'Kolkata',
      country: 'India',
      thumbnailUrl: 'https://images.unsplash.com/photo-1558431382-27e303142255?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1558431382-27e303142255?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-6',
      title: 'London Westminster Bridge SkyCam',
      lat: 51.501,
      lon: -0.124,
      city: 'London',
      country: 'United Kingdom',
      thumbnailUrl: 'https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-7',
      title: 'Tokyo Skytree Meteorological Observation',
      lat: 35.710,
      lon: 139.810,
      city: 'Tokyo',
      country: 'Japan',
      thumbnailUrl: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    },
    {
      id: 'cam-8',
      title: 'Dubai Marina Skyline View',
      lat: 25.080,
      lon: 55.140,
      city: 'Dubai',
      country: 'UAE',
      thumbnailUrl: 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=400&q=80',
      previewUrl: 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=1200&q=80',
      status: 'active',
      updatedAt: 'Live',
    }
  ];
}

export async function fetchDirectOpenMeteo(lat: number, lon: number, model: WeatherModel = 'ecmwf'): Promise<PointForecastData> {
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,surface_pressure,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset&current=temperature_2m,relative_humidity_2m,apparent_temperature,dew_point_2m,precipitation,weather_code,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto&forecast_days=7`;

  const res = await fetch(url);
  const data = await res.json();

  const currentHour: any = {
    time: data.current?.time || new Date().toISOString(),
    timestamp: new Date(data.current?.time || Date.now()).getTime(),
    temp: data.current?.temperature_2m ?? 24,
    feelsLike: data.current?.apparent_temperature ?? 24,
    dewPoint: data.current?.dew_point_2m ?? 16,
    humidity: data.current?.relative_humidity_2m ?? 60,
    precipitation: data.current?.precipitation ?? 0,
    precipitationProb: 0,
    pressure: data.current?.surface_pressure ?? 1013,
    windSpeed: data.current?.wind_speed_10m ?? 15,
    windDirection: data.current?.wind_direction_10m ?? 180,
    windGusts: data.current?.wind_gusts_10m ?? 22,
    cloudCover: data.current?.cloud_cover ?? 30,
    uvIndex: 4,
    weatherCode: data.current?.weather_code ?? 0,
    condition: getWeatherDescription(data.current?.weather_code ?? 0),
  };

  const hourly: any[] = (data.hourly?.time || []).slice(0, 72).map((t: string, i: number) => ({
    time: t,
    timestamp: new Date(t).getTime(),
    temp: data.hourly.temperature_2m[i] ?? 20,
    feelsLike: data.hourly.apparent_temperature[i] ?? 20,
    dewPoint: data.hourly.dew_point_2m[i] ?? 14,
    humidity: data.hourly.relative_humidity_2m[i] ?? 50,
    precipitation: data.hourly.precipitation[i] ?? 0,
    precipitationProb: data.hourly.precipitation_probability?.[i] ?? 0,
    pressure: data.hourly.surface_pressure[i] ?? 1013,
    windSpeed: data.hourly.wind_speed_10m[i] ?? 12,
    windDirection: data.hourly.wind_direction_10m[i] ?? 180,
    windGusts: data.hourly.wind_gusts_10m[i] ?? 18,
    cloudCover: data.hourly.cloud_cover[i] ?? 20,
    uvIndex: data.hourly.uv_index?.[i] ?? 0,
    weatherCode: data.hourly.weather_code[i] ?? 0,
    condition: getWeatherDescription(data.hourly.weather_code[i] ?? 0),
  }));

  const daily: any[] = (data.daily?.time || []).map((t: string, i: number) => {
    const d = new Date(t);
    const dayName = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    return {
      date: t,
      dayName,
      tempMax: data.daily.temperature_2m_max[i] ?? 28,
      tempMin: data.daily.temperature_2m_min[i] ?? 18,
      precipitationSum: data.daily.precipitation_sum[i] ?? 0,
      windSpeedMax: data.daily.wind_speed_10m_max[i] ?? 20,
      windDirectionDominant: data.daily.wind_direction_10m_dominant[i] ?? 180,
      weatherCode: data.daily.weather_code[i] ?? 0,
      condition: getWeatherDescription(data.daily.weather_code[i] ?? 0),
      sunrise: data.daily.sunrise[i] ? data.daily.sunrise[i].split('T')[1] : '06:00',
      sunset: data.daily.sunset[i] ? data.daily.sunset[i].split('T')[1] : '18:30',
    };
  });

  return {
    location: {
      lat,
      lon,
      elevation: data.elevation,
    },
    current: currentHour,
    hourly,
    daily,
    model,
    source: 'open-meteo',
  };
}

export function getWeatherDescription(code: number): string {
  switch (code) {
    case 0: return 'Clear sky';
    case 1: return 'Mainly clear';
    case 2: return 'Partly cloudy';
    case 3: return 'Overcast';
    case 45: case 48: return 'Fog';
    case 51: case 53: case 55: return 'Drizzle';
    case 61: case 63: case 65: return 'Rain';
    case 66: case 67: return 'Freezing rain';
    case 71: case 73: case 75: return 'Snow fall';
    case 77: return 'Snow grains';
    case 80: case 81: case 82: return 'Rain showers';
    case 85: case 86: return 'Snow showers';
    case 95: return 'Thunderstorm';
    case 96: case 99: return 'Thunderstorm with hail';
    default: return 'Fair';
  }
}

export function convertSpeed(kmh: number, unit: WindSpeedUnit): { value: number; unit: string } {
  switch (unit) {
    case 'kt': return { value: Math.round(kmh * 0.539957), unit: 'kt' };
    case 'ms': return { value: Math.round((kmh / 3.6) * 10) / 10, unit: 'm/s' };
    case 'mph': return { value: Math.round(kmh * 0.621371), unit: 'mph' };
    case 'kmh':
    default: return { value: Math.round(kmh), unit: 'km/h' };
  }
}

export function convertTemp(celsius: number, unit: TempUnit): { value: number; unit: string } {
  if (unit === 'f') {
    return { value: Math.round((celsius * 9) / 5 + 32), unit: '°F' };
  }
  return { value: Math.round(celsius), unit: '°C' };
}

export function convertPressure(hpa: number, unit: PressureUnit): { value: number; unit: string } {
  if (unit === 'inhg') {
    return { value: Math.round(hpa * 0.02953 * 100) / 100, unit: 'inHg' };
  }
  if (unit === 'mmhg') {
    return { value: Math.round(hpa * 0.750062), unit: 'mmHg' };
  }
  return { value: Math.round(hpa), unit: 'hPa' };
}

export function getWindCompass(deg: number): string {
  const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const index = Math.round((((deg % 360) + 360) % 360) / 22.5) % 16;
  return directions[index];
}
