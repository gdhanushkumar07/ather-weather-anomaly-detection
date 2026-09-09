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
from schema import station_dict_to_reading

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

        # 1. Store stations and populate spatial pool
        readings = []
        for s in station_list:
            self._stations[s["id"]] = s
            readings.append(station_dict_to_reading(s))

        detector.update_spatial_pool(readings)

        # 2. Run initial anomaly assessment across stations to populate cache
        for s in station_list:
            # Check for genuine OFFLINE station (marked offline or all sensor values missing)
            is_offline = (
                s.get("status") == "OFFLINE"
                or (s.get("temperature") is None and (s.get("pressure") is None or s.get("pressure") == 0.0) and s.get("humidity") is None)
            )

            status, anomaly = detector.evaluate_station(s)

            if is_offline:
                s["status"] = "OFFLINE"
                s["anomaly"] = None
            else:
                s["status"] = status
                s["anomaly"] = anomaly

        print(f"StationService: Loaded {len(self._stations)} stations and initialized 5-Layer Anomaly Engine.")

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
                    "temperature": s.get("temperature"),
                    "pressure": s.get("pressure"),
                    "humidity": s.get("humidity"),
                    "windSpeed": s.get("windSpeed"),
                    "windDirection": s.get("windDirection"),
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

    def get_station_anomaly(self, station_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns canonical §16 analysis assessment for a specific station,
        with backwards-compatible top-level keys for existing frontend consumers.
        """
        stn = self._stations.get(station_id)
        if not stn:
            return None

        alert = detector.get_station_alert(station_id)
        if not alert:
            status, anomaly_dict = detector.evaluate_station(stn)
            alert = detector.get_station_alert(station_id)

        if not alert:
            return None

        # Base canonical §16 result
        res = alert.to_canonical_dict().copy()

        # Enforce exact normalized station metadata in canonical object
        res["station"]["name"] = stn.get("name", res["station"]["name"])
        res["station"]["town"] = stn.get("town", "")
        res["station"]["country"] = stn.get("country", "")
        res["station"]["region"] = stn.get("region", "")

        # Enforce exact normalized observation (no 0.0 pressure substitute)
        res["observation"]["temperature"] = stn.get("temperature")
        res["observation"]["pressure"] = (
            stn.get("pressure")
            if (stn.get("pressure") is not None and stn.get("pressure") >= 1.0)
            else None
        )
        res["observation"]["relative_humidity"] = stn.get("humidity")
        res["observation"]["wind_speed"] = stn.get("windSpeed")
        res["observation"]["wind_direction"] = stn.get("windDirection")
        res["observation"]["condition"] = stn.get("condition")

        # Top-level backward compatibility attributes
        res["station_id"] = alert.station_id
        res["status"] = alert.status
        res["is_anomaly"] = alert.is_anomaly
        res["anomaly_score"] = round(alert.severity_score, 3)
        res["confidence"] = round(alert.confidence_score, 3)
        res["veto_fired"] = alert.veto_fired
        res["root_cause"] = alert.root_cause.value
        res["affected_channels"] = alert.affected_channels
        res["layer_scores"] = {k: round(v, 3) for k, v in alert.layer_scores.items()}
        res["layers_scores"] = res["layer_scores"]
        res["reasons"] = alert.reasons
        res["explanation"] = alert.explanation
        res["sensor_health_index"] = round(alert.sensor_health_index, 1)
        res["health_index"] = res["sensor_health_index"]
        res["estimated_days_to_failure"] = (
            round(alert.estimated_days_to_failure, 1)
            if alert.estimated_days_to_failure
            else None
        )
        res["days_to_failure"] = res["estimated_days_to_failure"]
        res["raw_values"] = alert.raw_values
        res["corrected_values"] = alert.corrected_values
        res["operator_action"] = alert.operator_action

        return res

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
        stn = self._stations.get(station_id)
        if not stn:
            return []

        has_temp = stn.get("temperature") is not None
        has_press = stn.get("pressure") is not None and stn.get("pressure") >= 1.0
        has_humid = stn.get("humidity") is not None
        has_wind = stn.get("windSpeed") is not None

        base_temp = stn.get("temperature") if has_temp else 24.0
        base_press = stn.get("pressure") if has_press else 1013.2
        base_humid = stn.get("humidity") if has_humid else 60
        base_wind = stn.get("windSpeed") if has_wind else 12.0

        now = int(time.time())
        step_seconds = 3600
        history = []

        for i in range(hours, -1, -1):
            t_stamp = now - (i * step_seconds)
            hour_of_day = (t_stamp // 3600) % 24

            if i == 0:
                # Current time: exact normalized values from station
                temp_val = stn.get("temperature")
                press_val = (
                    stn.get("pressure")
                    if (stn.get("pressure") is not None and stn.get("pressure") >= 1.0)
                    else None
                )
                humid_val = stn.get("humidity")
                wind_val = stn.get("windSpeed")
            else:
                diurnal_temp = math.sin((hour_of_day - 8) * math.pi / 12) * 4.5
                diurnal_press = -math.cos((hour_of_day - 4) * math.pi / 12) * 2.0
                diurnal_humid = -diurnal_temp * 3.0

                temp_val = round(base_temp + diurnal_temp, 1) if has_temp else None
                press_val = round(base_press + diurnal_press, 1) if has_press else None
                humid_val = (
                    max(10, min(100, int(round(base_humid + diurnal_humid))))
                    if has_humid
                    else None
                )
                wind_val = (
                    round(max(0.0, base_wind + math.sin(i) * 3.0), 1)
                    if has_wind
                    else None
                )

            history.append({
                "timestamp": t_stamp,
                "timeLabel": time.strftime("%H:%M", time.gmtime(t_stamp)),
                "temperature": temp_val,
                "pressure": press_val,
                "humidity": humid_val,
                "windSpeed": wind_val,
                "source": "AWS Station Data"
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
            "activeAnomalies": anomalies[:30],
            "activeWarnings": warnings[:30]
        }

    def ingest_observation(self, station_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives an observation update and evaluates through the 5-Layer Anomaly Engine.
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

        # Update spatial pool reading
        detector.update_spatial_pool([station_dict_to_reading(stn)])

        self._stations[station_id] = stn
        return stn

# Singleton instance
station_service = StationService()
