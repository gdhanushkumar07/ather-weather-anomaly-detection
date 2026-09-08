"""
ATHER Stations Data Service
---------------------------
Manages weather station metadata, real-time telemetry, spatial querying,
and caching for the ATHER platform.
"""

import json
import math
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..anomaly.detector import detector

BASE_DIR = Path(__file__).resolve().parents[2] # backend directory
DATA_PATH = BASE_DIR.parent / "data" / "stations.json"

class StationService:
    def __init__(self):
        self._stations: Dict[str, Dict[str, Any]] = {}
        self._load_data()

    def _load_data(self):
        if not DATA_PATH.exists():
            print(f"Warning: {DATA_PATH} not found.")
            return

        with open(DATA_PATH, "r", encoding="utf-8") as f:
            station_list = json.load(f)

        for s in station_list:
            self._stations[s["id"]] = s
        print(f"StationService: Loaded {len(self._stations)} stations.")

    def get_all_stations(self, limit: Optional[int] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        res = list(self._stations.values())
        if status:
            res = [s for s in res if s.get("status", "").upper() == status.upper()]
        if limit:
            res = res[:limit]
        return res

    def get_geojson(
        self,
        min_lon: Optional[float] = None,
        min_lat: Optional[float] = None,
        max_lon: Optional[float] = None,
        max_lat: Optional[float] = None,
        limit: Optional[int] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        features = []
        count = 0

        for s in self._stations.values():
            lat = s.get("latitude", 0)
            lon = s.get("longitude", 0)

            # Viewport bounding box filtering if provided
            if min_lat is not None and max_lat is not None:
                if not (min_lat <= lat <= max_lat):
                    continue
            if min_lon is not None and max_lon is not None:
                if not (min_lon <= lon <= max_lon):
                    continue

            if status and s.get("status", "").upper() != status.upper():
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "id": s["id"],
                    "name": s["name"],
                    "town": s["town"],
                    "country": s["country"],
                    "region": s["region"],
                    "temperature": s["temperature"],
                    "pressure": s["pressure"],
                    "humidity": s["humidity"],
                    "windSpeed": s["windSpeed"],
                    "windDirection": s["windDirection"],
                    "condition": s.get("condition", "Reported"),
                    "timestamp": s.get("timestamp", "Recent"),
                    "status": s.get("status", "NORMAL"),
                    "hasAnomaly": 1 if s.get("anomaly") else 0,
                    "severity": s["anomaly"]["severity"] if s.get("anomaly") else "NONE"
                }
            })
            count += 1
            if limit and count >= limit:
                break

        return {
            "type": "FeatureCollection",
            "features": features,
            "total": count
        }

    def get_station(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self._stations.get(station_id)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        q = query.lower().strip()
        matches = []
        for s in self._stations.values():
            if (q in s.get("name", "").lower() or 
                q in s.get("town", "").lower() or 
                q in s.get("id", "").lower() or
                q in s.get("country", "").lower()):
                matches.append(s)
                if len(matches) >= limit:
                    break
        return matches

    def get_observations_history(self, station_id: str, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Generates realistic 24-hour observation time-series trend for the station.
        """
        stn = self._stations.get(station_id)
        if not stn:
            return []

        base_temp = stn.get("temperature") or 24.0
        base_press = stn.get("pressure") or 1013.2
        base_humid = stn.get("humidity") or 60
        base_wind = stn.get("windSpeed") or 12.0

        now = int(time.time())
        step_seconds = 3600  # 1 hour
        history = []

        for i in range(hours, -1, -1):
            t_stamp = now - (i * step_seconds)
            # Diurnal sinusoidal variation
            hour_of_day = (t_stamp // 3600) % 24
            diurnal_temp = math.sin((hour_of_day - 8) * math.pi / 12) * 4.5
            diurnal_press = -math.cos((hour_of_day - 4) * math.pi / 12) * 2.0
            diurnal_humid = -diurnal_temp * 3.0

            # If station has anomaly, inject spike in the latest 2 intervals
            temp_val = round(base_temp + diurnal_temp, 1)
            press_val = round(base_press + diurnal_press, 1)

            if stn.get("status") == "ANOMALY" and i <= 2:
                if stn["anomaly"] and stn["anomaly"]["parameter"] == "Temperature":
                    temp_val = stn["anomaly"]["observed"]
                elif stn["anomaly"] and stn["anomaly"]["parameter"] == "Pressure":
                    press_val = stn["anomaly"]["observed"]

            history.append({
                "timestamp": t_stamp,
                "timeLabel": time.strftime("%H:%M", time.gmtime(t_stamp)),
                "temperature": temp_val,
                "pressure": press_val,
                "humidity": max(10, min(100, int(round(base_humid + diurnal_humid)))),
                "windSpeed": round(max(0.0, base_wind + math.sin(i) * 3.0), 1)
            })

        return history

    def get_anomalies_summary(self) -> Dict[str, Any]:
        anomalies = []
        warnings = []
        for s in self._stations.values():
            if s.get("status") == "ANOMALY":
                anomalies.append(s)
            elif s.get("status") == "WARNING":
                warnings.append(s)

        return {
            "totalStations": len(self._stations),
            "normalCount": len(self._stations) - len(anomalies) - len(warnings),
            "warningCount": len(warnings),
            "anomalyCount": len(anomalies),
            "activeAnomalies": anomalies[:20],
            "activeWarnings": warnings[:20]
        }

    def ingest_observation(self, station_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives an observation update (WeeWX/WOW-BE format) and evaluates anomalies.
        """
        stn = self._stations.get(station_id)
        if not stn:
            stn = {
                "id": station_id,
                "name": payload.get("name", f"Station {station_id}"),
                "town": payload.get("town", "Unknown Location"),
                "latitude": float(payload.get("latitude", 0)),
                "longitude": float(payload.get("longitude", 0)),
                "country": payload.get("country", "Unknown"),
                "region": payload.get("region", "Unknown"),
            }

        # Update telemetry
        for k in ["temperature", "pressure", "humidity", "windSpeed", "windDirection", "condition"]:
            if k in payload and payload[k] is not None:
                stn[k] = payload[k]

        stn["timestamp"] = "Just now"

        # Re-evaluate with anomaly detector
        status, anomaly = detector.evaluate_station(stn)
        stn["status"] = status
        stn["anomaly"] = anomaly

        self._stations[station_id] = stn
        return stn

# Singleton instance
station_service = StationService()
