import express from "express";
import path from "path";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3005;

app.use(express.json());

// In-memory cache for API requests to avoid spamming external endpoints
const cache = new Map<string, { timestamp: number; data: any }>();
const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes

// Lazy Gemini AI client
let aiClient: GoogleGenAI | null = null;
function getGeminiClient(): GoogleGenAI | null {
  if (!aiClient && process.env.GEMINI_API_KEY) {
    try {
      aiClient = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
    } catch (e) {
      console.warn("Failed to initialize GoogleGenAI client:", e);
    }
  }
  return aiClient;
}

// 1. Health check endpoint
app.get("/api/health", (req, res) => {
  res.json({
    status: "ok",
    hasGeminiKey: Boolean(process.env.GEMINI_API_KEY),
  });
});

// 2. Point Forecast API (High-Resolution Open-Meteo Integration)
app.get("/api/weather/point", async (req, res) => {
  try {
    const lat = parseFloat(req.query.lat as string);
    const lon = parseFloat(req.query.lon as string);
    const model = (req.query.model as string) || "ecmwf";

    if (isNaN(lat) || isNaN(lon)) {
      return res.status(400).json({ error: "Invalid lat/lon parameters" });
    }

    const cacheKey = `point:${lat.toFixed(2)}:${lon.toFixed(2)}:${model}`;
    const cached = cache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      return res.json(cached.data);
    }

    const forecastData = await fetchOpenMeteoForecast(lat, lon, model);
    cache.set(cacheKey, { timestamp: Date.now(), data: forecastData });
    return res.json(forecastData);
  } catch (error: any) {
    console.error("Error in /api/weather/point:", error);
    res.status(500).json({ error: error.message || "Failed to fetch forecast" });
  }
});

// 3. Webcams API
app.get("/api/weather/webcams", async (req, res) => {
  try {
    res.json(getCuratedWebcams());
  } catch (err: any) {
    console.error("Error in /api/weather/webcams:", err);
    res.json(getCuratedWebcams());
  }
});

// 4. SIH AI Anomaly Detection Engine (Gemini 2.5 Flash + Meteorological Index)
app.post("/api/weather/anomalies", async (req, res) => {
  try {
    const { lat, lon, weather } = req.body;
    const ai = getGeminiClient();

    if (ai) {
      const prompt = `You are an expert meteorological AI specialized in severe weather hazard and atmospheric anomaly classification (D0: Normal/Dry to D5: Exceptional/Catastrophic Anomaly).
Analyze this location and real-time weather readings:
Coordinates: Latitude ${lat}, Longitude ${lon}
Current Weather:
- Temperature: ${weather?.temp || 26} °C
- Wind Speed: ${weather?.windSpeed || 15} km/h
- Wind Gusts: ${weather?.windGusts || 22} km/h
- Barometric Pressure: ${weather?.pressure || 1012} hPa
- Precipitation: ${weather?.precipitation || 0} mm/h
- Humidity: ${weather?.humidity || 65}%

Evaluate atmospheric deviation from multi-year norms for this geographic region (e.g. cyclonic depression risk, severe heatwave, extreme convective storm, flash inundation, or drought index).
Return STRICTLY a JSON object with:
{
  "level": "D0" | "D1" | "D2" | "D3" | "D4" | "D5",
  "title": "short hazard title (e.g. D3 - Severe Convective Surge)",
  "description": "2 sentence diagnostic explanation of what causes this anomaly",
  "riskScore": number (0 to 100),
  "factors": [
    { "name": "Factor Name", "value": "value with unit", "severity": "normal"|"moderate"|"high"|"critical" }
  ]
}`;

      try {
        const response = await ai.models.generateContent({
          model: "gemini-2.5-flash",
          contents: prompt,
          config: {
            responseMimeType: "application/json",
          },
        });

        if (response.text) {
          const parsed = JSON.parse(response.text);
          parsed.timestamp = new Date().toISOString();
          return res.json(parsed);
        }
      } catch (geminiErr) {
        console.warn("Gemini Anomaly analysis failed, falling back to rule engine:", geminiErr);
      }
    }

    // Algorithmic rule engine fallback
    const fallbackAnomaly = evaluateRuleAnomaly(lat, lon, weather);
    res.json(fallbackAnomaly);
  } catch (e: any) {
    console.error("Error in /api/weather/anomalies:", e);
    res.json(evaluateRuleAnomaly(0, 0, {}));
  }
});

// Helper: Open-Meteo Forecast
async function fetchOpenMeteoForecast(lat: number, lon: number, model: string) {
  // Try to reverse geocode name
  let locationName = "Observation Point";
  let countryName = "";
  try {
    const geoResp = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=10`,
      { headers: { "User-Agent": "AtherWeatherDashboard/1.0" } }
    );
    if (geoResp.ok) {
      const geoData = await geoResp.json();
      locationName = geoData.address?.city || geoData.address?.town || geoData.address?.county || geoData.address?.state || "Selected Area";
      countryName = geoData.address?.country || "";
    }
  } catch (e) {
    // Ignore reverse geocode failures
  }

  const omUrl = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,surface_pressure,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset&current=temperature_2m,relative_humidity_2m,apparent_temperature,dew_point_2m,precipitation,weather_code,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto&forecast_days=7`;

  const resp = await fetch(omUrl);
  if (!resp.ok) {
    throw new Error(`Open-Meteo returned status ${resp.status}`);
  }
  const data = await resp.json();

  const currentHour = {
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

  const hourly = (data.hourly?.time || []).slice(0, 72).map((t: string, i: number) => ({
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

  const daily = (data.daily?.time || []).map((t: string, i: number) => {
    const d = new Date(t);
    const dayName = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
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
      sunrise: data.daily.sunrise?.[i] ? data.daily.sunrise[i].split("T")[1] : "06:00",
      sunset: data.daily.sunset?.[i] ? data.daily.sunset[i].split("T")[1] : "18:30",
    };
  });

  return {
    location: {
      lat,
      lon,
      name: locationName,
      country: countryName,
      elevation: data.elevation ?? 100,
    },
    current: currentHour,
    hourly,
    daily,
    model,
    source: "open-meteo",
  };
}

function evaluateRuleAnomaly(lat: number, lon: number, weather: any) {
  const wind = weather?.windSpeed || 18;
  const temp = weather?.temp || 26;
  const precip = weather?.precipitation || 0;
  const pressure = weather?.pressure || 1012;

  let level = "D0";
  let risk = 18;
  let title = "D0 - Atmospheric Equilibrium";
  let desc = "Atmospheric conditions align with seasonal baseline averages. Normal stability.";

  if (wind > 75 || pressure < 988 || precip > 45) {
    level = "D5";
    risk = 95;
    title = "D5 - Extreme Cyclonic Hazard Alert";
    desc = "Intense low pressure trough and severe wind shear indicating high cyclonic or tropical storm anomaly.";
  } else if (wind > 50 || temp > 42 || precip > 25) {
    level = "D4";
    risk = 82;
    title = "D4 - Severe Convective Weather Alert";
    desc = "Major thermal or precipitation anomaly detected with localized flash flood or gale hazards.";
  } else if (wind > 35 || temp > 37 || precip > 12) {
    level = "D3";
    risk = 64;
    title = "D3 - Elevated Weather Anomaly";
    desc = "Noticeable deviation from 10-year climatological baselines. Continued monitoring advised.";
  } else if (temp > 32 || wind > 25) {
    level = "D2";
    risk = 42;
    title = "D2 - Moderate Meteorological Anomaly";
    desc = "Elevated surface temperature and gust profiles observed over the region.";
  } else if (temp > 28 || wind > 20) {
    level = "D1";
    risk = 26;
    title = "D1 - Mild Atmospheric Departure";
    desc = "Minor fluctuations in relative humidity and boundary layer velocity.";
  }

  return {
    level,
    title,
    description: desc,
    riskScore: risk,
    factors: [
      {
        name: "Surface Wind Shear",
        value: `${wind.toFixed(1)} km/h`,
        severity: wind > 50 ? "critical" : wind > 30 ? "high" : "normal",
      },
      {
        name: "Barometric Gradient",
        value: `${pressure.toFixed(0)} hPa`,
        severity: pressure < 995 ? "critical" : pressure < 1006 ? "moderate" : "normal",
      },
      {
        name: "Thermal Departure",
        value: `${temp.toFixed(1)} °C`,
        severity: temp > 40 ? "critical" : temp > 35 ? "high" : "normal",
      },
      {
        name: "Convective Rainfall",
        value: `${precip.toFixed(1)} mm/h`,
        severity: precip > 25 ? "critical" : precip > 10 ? "high" : "normal",
      },
    ],
    timestamp: new Date().toISOString(),
  };
}

function getWeatherDescription(code: number): string {
  switch (code) {
    case 0: return "Clear sky";
    case 1: return "Mainly clear";
    case 2: return "Partly cloudy";
    case 3: return "Overcast";
    case 45: case 48: return "Fog";
    case 51: case 53: case 55: return "Drizzle";
    case 61: case 63: case 65: return "Rain";
    case 71: case 73: case 75: return "Snow";
    case 80: case 81: case 82: return "Rain showers";
    case 95: return "Thunderstorm";
    default: return "Fair";
  }
}

function getCuratedWebcams() {
  return [
    {
      id: "cam-1",
      title: "Marine Drive Promenade",
      lat: 18.944,
      lon: 72.823,
      city: "Mumbai",
      country: "India",
      thumbnailUrl: "https://images.unsplash.com/photo-1570168007204-dfb528c6958f?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1570168007204-dfb528c6958f?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    },
    {
      id: "cam-2",
      title: "Hussain Sagar Observation",
      lat: 17.423,
      lon: 78.473,
      city: "Hyderabad",
      country: "India",
      thumbnailUrl: "https://images.unsplash.com/photo-1605007493699-ce65834f8a00?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1605007493699-ce65834f8a00?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    },
    {
      id: "cam-3",
      title: "Connaught Central Weather Cam",
      lat: 28.632,
      lon: 77.219,
      city: "New Delhi",
      country: "India",
      thumbnailUrl: "https://images.unsplash.com/photo-1587474260584-136574528ed5?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1587474260584-136574528ed5?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    },
    {
      id: "cam-4",
      title: "Marina Coastal Radar Station",
      lat: 13.050,
      lon: 80.282,
      city: "Chennai",
      country: "India",
      thumbnailUrl: "https://images.unsplash.com/photo-1582510003544-4d00b7f74220?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1582510003544-4d00b7f74220?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    },
    {
      id: "cam-5",
      title: "Victoria Memorial SkyCam",
      lat: 22.544,
      lon: 88.342,
      city: "Kolkata",
      country: "India",
      thumbnailUrl: "https://images.unsplash.com/photo-1558431382-27e303142255?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1558431382-27e303142255?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    },
    {
      id: "cam-6",
      title: "London Westminster Meteorological View",
      lat: 51.501,
      lon: -0.124,
      city: "London",
      country: "United Kingdom",
      thumbnailUrl: "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=400&q=80",
      previewUrl: "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=1200&q=80",
      status: "active",
      updatedAt: "Live",
    }
  ];
}

// Vite middleware & Static serving
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`ATHER Global Weather Dashboard Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
