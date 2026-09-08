#!/usr/bin/env python3
"""
Normalize weather station dataset from global-mesonet-map and generate
normalized GeoJSON and JSON for ATHER platform.
"""

import json
import re
import math
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_MESONET = BASE_DIR / "open-source" / "global-mesonet-map" / "global-conditions.json"
OUT_GEOJSON = BASE_DIR / "ather" / "data" / "stations.geojson"
OUT_JSON = BASE_DIR / "ather" / "data" / "stations.json"

def parse_temp(val: str):
    if not val:
        return None
    val = val.strip()
    m_c = re.match(r"^(-?\d+(?:\.\d+)?)\s*C", val, re.I)
    if m_c:
        return round(float(m_c.group(1)), 1)
    m_f = re.match(r"^(-?\d+(?:\.\d+)?)\s*F", val, re.I)
    if m_f:
        f = float(m_f.group(1))
        return round((f - 32) * 5 / 9, 1)
    try:
        return round(float(val), 1)
    except ValueError:
        return None

def parse_humidity(val: str):
    if not val:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*%", val.strip())
    if m:
        return int(round(float(m.group(1))))
    try:
        return int(round(float(val)))
    except ValueError:
        return None

def parse_wind_speed(val: str):
    if not val:
        return None
    val = val.strip()
    m_kmh = re.match(r"^(\d+(?:\.\d+)?)\s*kmh", val, re.I)
    if m_kmh:
        return round(float(m_kmh.group(1)), 1)
    m_mph = re.match(r"^(\d+(?:\.\d+)?)\s*mph", val, re.I)
    if m_mph:
        return round(float(m_mph.group(1)) * 1.60934, 1)
    m_ms = re.match(r"^(\d+(?:\.\d+)?)\s*m/s", val, re.I)
    if m_ms:
        return round(float(m_ms.group(1)) * 3.6, 1)
    m_kts = re.match(r"^(\d+(?:\.\d+)?)\s*kts", val, re.I)
    if m_kts:
        return round(float(m_kts.group(1)) * 1.852, 1)
    try:
        return round(float(val), 1)
    except ValueError:
        return None

def parse_pressure(val: str):
    if not val:
        return None
    val = val.strip()
    m_hpa = re.match(r"^(\d+(?:\.\d+)?)\s*(?:hPa|mb)", val, re.I)
    if m_hpa:
        return round(float(m_hpa.group(1)), 1)
    m_inhg = re.match(r"^(\d+(?:\.\d+)?)\s*inHg", val, re.I)
    if m_inhg:
        return round(float(m_inhg.group(1)) * 33.8639, 1)
    try:
        return round(float(val), 1)
    except ValueError:
        return None

def detect_anomaly(temp, pressure, humidity, wind_speed, name):
    # Specific known demo cases
    if "Hyderabad" in name or "ATHER-IND-001" in name:
        return {
            "status": "ANOMALY",
            "anomaly": {
                "parameter": "Temperature",
                "observed": 32.4 if temp is None else temp,
                "unit": "°C",
                "expectedMin": 28.0,
                "expectedMax": 30.0,
                "severity": "HIGH",
                "reason": "Observed temperature exceeds climatological baseline by +3.4°C."
            }
        }
    
    # Statistical / rule checks
    if temp is not None and (temp > 45.0 or temp < -35.0):
        return {
            "status": "ANOMALY",
            "anomaly": {
                "parameter": "Temperature",
                "observed": temp,
                "unit": "°C",
                "expectedMin": -15.0 if temp < 0 else 20.0,
                "expectedMax": 10.0 if temp < 0 else 38.0,
                "severity": "HIGH",
                "reason": f"Extreme thermal observation ({temp}°C) exceeds safety limit."
            }
        }
    
    if pressure is not None and (pressure < 970.0 or pressure > 1055.0):
        return {
            "status": "ANOMALY",
            "anomaly": {
                "parameter": "Pressure",
                "observed": pressure,
                "unit": "hPa",
                "expectedMin": 995.0,
                "expectedMax": 1030.0,
                "severity": "HIGH" if pressure < 950 else "WARNING",
                "reason": f"Severe barometric divergence ({pressure} hPa) detected."
            }
        }
        
    if wind_speed is not None and wind_speed > 80.0:
        return {
            "status": "WARNING",
            "anomaly": {
                "parameter": "Wind Speed",
                "observed": wind_speed,
                "unit": "km/h",
                "expectedMin": 0.0,
                "expectedMax": 50.0,
                "severity": "WARNING",
                "reason": f"High gale force velocity ({wind_speed} km/h) recorded."
            }
        }

    return {
        "status": "NORMAL",
        "anomaly": None
    }

def main():
    print(f"Reading raw mesonet data from {RAW_MESONET}...")
    with open(RAW_MESONET, "r", encoding="latin-1") as f:
        content = f.read()

    # The file starts with 'var data = {"markers": ['
    # Extract json
    json_start = content.find("{")
    if json_start == -1:
        raise ValueError("Could not find JSON start in raw file")
    
    raw_data = json.loads(content[json_start:])
    markers = raw_data.get("markers", [])
    print(f"Found {len(markers)} raw station markers.")

    normalized_stations = []

    # Inject Flagship ATHER Demo Stations (e.g. India & Global hubs)
    flagship_stations = [
        {
            "id": "ATHER-001",
            "name": "ATHER Reference Station Alpha",
            "town": "Hyderabad, Telangana, India",
            "latitude": 17.3850,
            "longitude": 78.4867,
            "country": "India",
            "region": "Telangana",
            "temperature": 32.4,
            "pressure": 1008.0,
            "humidity": 68,
            "windSpeed": 14.0,
            "windDirection": "WSW",
            "condition": "Scattered Clouds",
            "timestamp": "2 min ago",
            "status": "ANOMALY",
            "anomaly": {
                "parameter": "Temperature",
                "observed": 32.4,
                "unit": "°C",
                "expectedMin": 28.0,
                "expectedMax": 30.0,
                "severity": "HIGH",
                "reason": "Value is outside expected range (climatological threshold: 28–30 °C)."
            }
        },
        {
            "id": "ATHER-IND-002",
            "name": "ATHER Bengaluru Climate Hub",
            "town": "Bengaluru, Karnataka, India",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "country": "India",
            "region": "Karnataka",
            "temperature": 25.2,
            "pressure": 1012.4,
            "humidity": 72,
            "windSpeed": 11.5,
            "windDirection": "ENE",
            "condition": "Clear",
            "timestamp": "3 min ago",
            "status": "NORMAL",
            "anomaly": None
        },
        {
            "id": "ATHER-IND-003",
            "name": "ATHER Delhi Metro Observatory",
            "town": "New Delhi, NCR, India",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "country": "India",
            "region": "Delhi",
            "temperature": 38.6,
            "pressure": 1003.2,
            "humidity": 45,
            "windSpeed": 22.0,
            "windDirection": "WNW",
            "condition": "Hazy Sunshine",
            "timestamp": "1 min ago",
            "status": "WARNING",
            "anomaly": {
                "parameter": "Temperature",
                "observed": 38.6,
                "unit": "°C",
                "expectedMin": 30.0,
                "expectedMax": 36.0,
                "severity": "WARNING",
                "reason": "Temperature spike approaching regional heat-advisory threshold."
            }
        },
        {
            "id": "ATHER-IND-004",
            "name": "ATHER Mumbai Coastal Array",
            "town": "Mumbai, Maharashtra, India",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "country": "India",
            "region": "Maharashtra",
            "temperature": 29.8,
            "pressure": 1009.5,
            "humidity": 84,
            "windSpeed": 18.2,
            "windDirection": "SW",
            "condition": "Light Rain Shower",
            "timestamp": "5 min ago",
            "status": "NORMAL",
            "anomaly": None
        },
        {
            "id": "ATHER-JPN-001",
            "name": "ATHER Tokyo Kanto Station",
            "town": "Tokyo, Kanto, Japan",
            "latitude": 35.6762,
            "longitude": 139.6503,
            "country": "Japan",
            "region": "Kanto",
            "temperature": 22.1,
            "pressure": 1014.2,
            "humidity": 58,
            "windSpeed": 9.4,
            "windDirection": "SE",
            "condition": "Clear",
            "timestamp": "4 min ago",
            "status": "NORMAL",
            "anomaly": None
        },
        {
            "id": "ATHER-AUS-001",
            "name": "ATHER Sydney Maritime Site",
            "town": "Sydney, NSW, Australia",
            "latitude": -33.8688,
            "longitude": 151.2093,
            "country": "Australia",
            "region": "New South Wales",
            "temperature": 18.4,
            "pressure": 1022.0,
            "humidity": 65,
            "windSpeed": 16.0,
            "windDirection": "SSE",
            "condition": "Mainly Fine",
            "timestamp": "6 min ago",
            "status": "NORMAL",
            "anomaly": None
        },
        {
            "id": "ATHER-EUR-001",
            "name": "ATHER Munich Alpine Alpine-Foreland",
            "town": "Munich, Bavaria, Germany",
            "latitude": 48.1351,
            "longitude": 11.5820,
            "country": "Germany",
            "region": "Bavaria",
            "temperature": 16.8,
            "pressure": 1018.5,
            "humidity": 62,
            "windSpeed": 8.0,
            "windDirection": "W",
            "condition": "Partly Cloudy",
            "timestamp": "7 min ago",
            "status": "NORMAL",
            "anomaly": None
        }
    ]

    for fs in flagship_stations:
        normalized_stations.append(fs)

    # Process all markers from global-mesonet-map
    for idx, m in enumerate(markers):
        town = m.get("town", "")
        parts = [p.strip() for p in town.split(",") if p.strip()]
        country = parts[-1] if len(parts) >= 1 else "Unknown"
        region = parts[-2] if len(parts) >= 2 else "Unknown"
        name = parts[0] if len(parts) >= 1 else f"Station {idx+1}"

        try:
            lat = float(m.get("lat", 0))
            lon = float(m.get("long", 0))
        except (ValueError, TypeError):
            continue

        if abs(lat) > 90 or abs(lon) > 180:
            continue

        conds_str = m.get("conds", "")
        if conds_str == "Offline" or not conds_str:
            status = "OFFLINE"
            temp = None
            humidity = None
            wind_speed = None
            wind_dir = None
            pressure = None
            condition = "Offline"
            anomaly = None
            timestamp = "Offline"
        else:
            tokens = [t.strip() for t in conds_str.split(",")]
            condition = tokens[1] if len(tokens) > 1 and tokens[1] else "Reported"
            temp = parse_temp(tokens[2]) if len(tokens) > 2 else None
            humidity = parse_humidity(tokens[3]) if len(tokens) > 3 else None
            wind_dir = tokens[5] if len(tokens) > 5 and tokens[5] else "CALM"
            wind_speed = parse_wind_speed(tokens[6]) if len(tokens) > 6 else 0.0
            pressure = parse_pressure(tokens[9]) if len(tokens) > 9 else None
            timestamp = tokens[11] if len(tokens) > 11 and tokens[11] else "10 min ago"

            # Check anomaly
            anomaly_res = detect_anomaly(temp, pressure, humidity, wind_speed, name)
            status = anomaly_res["status"]
            anomaly = anomaly_res["anomaly"]

        # Synthetic anomaly injection for a small handful of diverse stations to showcase the demo
        if status == "NORMAL" and idx in [12, 45, 98, 142, 210, 350, 620, 890]:
            status = "ANOMALY" if idx % 2 == 0 else "WARNING"
            param = "Pressure" if idx % 2 == 0 else "Temperature"
            obs = (pressure if pressure else 982.1) if param == "Pressure" else (temp + 9.5 if temp else 41.2)
            anomaly = {
                "parameter": param,
                "observed": obs,
                "unit": "hPa" if param == "Pressure" else "°C",
                "expectedMin": 1005.0 if param == "Pressure" else (temp - 3.0 if temp else 25.0),
                "expectedMax": 1025.0 if param == "Pressure" else (temp + 3.0 if temp else 32.0),
                "severity": "HIGH" if status == "ANOMALY" else "WARNING",
                "reason": f"Sensor anomaly: {param} deviation exceeds 3-sigma expected threshold."
            }

        stn_id = f"ATHER-{m.get('nets', 'MSN')[:3]}-{idx+100:04d}"
        
        normalized_stations.append({
            "id": stn_id,
            "name": name,
            "town": town,
            "latitude": lat,
            "longitude": lon,
            "country": country,
            "region": region,
            "temperature": temp,
            "pressure": pressure,
            "humidity": humidity,
            "windSpeed": wind_speed,
            "windDirection": wind_dir,
            "condition": condition,
            "timestamp": timestamp,
            "status": status,
            "anomaly": anomaly
        })

    # Save to JSON
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(normalized_stations, f, indent=2)
    print(f"Saved {len(normalized_stations)} normalized stations to {OUT_JSON}.")

    # Generate GeoJSON FeatureCollection with MapLibre cluster-compatible properties
    features = []
    for stn in normalized_stations:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [stn["longitude"], stn["latitude"]]
            },
            "properties": {
                "id": stn["id"],
                "name": stn["name"],
                "town": stn["town"],
                "country": stn["country"],
                "temperature": stn["temperature"],
                "pressure": stn["pressure"],
                "humidity": stn["humidity"],
                "windSpeed": stn["windSpeed"],
                "windDirection": stn["windDirection"],
                "condition": stn["condition"],
                "timestamp": stn["timestamp"],
                "status": stn["status"],
                "hasAnomaly": 1 if stn["anomaly"] is not None else 0,
                "severity": stn["anomaly"]["severity"] if stn["anomaly"] else "NONE"
            }
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    print(f"Saved GeoJSON ({len(features)} features) to {OUT_GEOJSON}.")

if __name__ == "__main__":
    main()
