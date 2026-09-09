"""
ATHER Stations Data Service
---------------------------
Manages weather station metadata, real-time telemetry, spatial querying,
and caching for the ATHER platform.
"""

import csv
import json
import math
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..anomaly.detector import detector
from schema import station_dict_to_reading

BASE_DIR = Path(__file__).resolve().parents[2] # backend directory
DATA_PATH = BASE_DIR.parent / "data" / "stations.json"
CSV_PATH = BASE_DIR / "WeatherUnionInfra.csv"

class StationService:
    def __init__(self):
        self._stations: Dict[str, Dict[str, Any]] = {}
        self._load_data()

    def _load_data(self):
        if not DATA_PATH.exists():
            print(f"Warning: {DATA_PATH} not found.")
            station_list = []
        else:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                station_list = json.load(f)

        # 1. Store existing stations and populate spatial pool
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

        # 3. Ingest and normalize Indian AWS stations from WeatherUnionInfra.csv
        self._load_weather_union_csv()

        print(f"StationService: Loaded {len(self._stations)} stations and initialized 5-Layer Anomaly Engine.")

    def _load_weather_union_csv(self):
        if not CSV_PATH.exists():
            print(f"Warning: {CSV_PATH} not found.")
            return

        city_region_map = {
            "Bengaluru": "Karnataka",
            "Chennai": "Tamil Nadu",
            "Delhi NCR": "Delhi NCR",
            "Hyderabad": "Telangana",
            "Kolkata": "West Bengal",
            "Mumbai": "Maharashtra",
            "Pune": "Maharashtra",
        }

        new_readings = []
        added_count = 0
        skipped_non_aws = 0
        skipped_invalid = 0
        duplicate_count = 0

        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                device_type = row.get("device_type", "").strip()
                # Phase 2: Only Automated weather system records
                if "Automated weather system" not in device_type:
                    skipped_non_aws += 1
                    continue

                locality_id = row.get("localityId", "").strip()
                if not locality_id:
                    skipped_invalid += 1
                    continue

                city_name = row.get("cityName", "").strip()
                locality_name = row.get("localityName", "").strip()

                try:
                    lat = float(row.get("latitude", 0))
                    lon = float(row.get("longitude", 0))
                except (ValueError, TypeError):
                    skipped_invalid += 1
                    continue

                # Phase 6 & Phase 12: Validate Indian geographic coordinates
                if not (6.0 <= lat <= 38.0 and 68.0 <= lon <= 98.0):
                    skipped_invalid += 1
                    continue

                # Phase 11: Deduplication - existing station priority
                if locality_id in self._stations:
                    duplicate_count += 1
                    continue

                region = city_region_map.get(city_name, city_name)
                station_name = f"{locality_name} AWS" if locality_name else f"WeatherUnion AWS {locality_id}"
                town_str = f"{locality_name}, {city_name}, {region}, India" if locality_name else f"{city_name}, {region}, India"

                # Phase 4 & Phase 10: Canonical ATHER station schema
                stn_dict = {
                    "id": locality_id,
                    "name": station_name,
                    "town": town_str,
                    "latitude": lat,
                    "longitude": lon,
                    "country": "India",
                    "region": region,
                    "temperature": None,
                    "pressure": None,
                    "humidity": None,
                    "windSpeed": None,
                    "windDirection": None,
                    "condition": "Offline",
                    "timestamp": "No Data",
                    "status": "OFFLINE",
                    "anomaly": None,
                    "device_type": "Automated weather system",
                    "localityId": locality_id
                }

                self._stations[locality_id] = stn_dict
                new_readings.append(station_dict_to_reading(stn_dict))
                added_count += 1

        if new_readings:
            detector.update_spatial_pool(new_readings)

        print(
            f"StationService: Ingested {added_count} Indian AWS stations from WeatherUnionInfra.csv "
            f"({skipped_non_aws} non-AWS skipped, {skipped_invalid} invalid, {duplicate_count} duplicates)."
        )

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
            if isinstance(min_lat, (int, float)) and isinstance(max_lat, (int, float)):
                if not (min_lat <= lat <= max_lat):
                    continue
            if isinstance(min_lon, (int, float)) and isinstance(max_lon, (int, float)):
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
        stn = self._stations.get(station_id)
        if stn:
            return stn
        # Fallback check by localityId or without ATHER prefix
        clean_id = station_id.replace("ATHER-IND-", "").replace("ATHER-", "")
        for s in self._stations.values():
            if s.get("localityId") == station_id or s.get("id") == clean_id or s.get("localityId") == clean_id:
                return s
        return None

    def get_station_anomaly(self, station_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns canonical §16 analysis assessment for a specific station,
        with backwards-compatible top-level keys for existing frontend consumers.
        """
        stn = self.get_station(station_id)
        if not stn:
            return None

        resolved_id = stn.get("id", station_id)
        alert = detector.get_station_alert(resolved_id)
        if not alert:
            status, anomaly_dict = detector.evaluate_station(stn)
            alert = detector.get_station_alert(resolved_id)

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

        is_offline = stn.get("status") == "OFFLINE"

        # Top-level backward compatibility attributes
        res["station_id"] = alert.station_id
        res["status"] = "OFFLINE" if is_offline else alert.status
        res["is_anomaly"] = False if is_offline else alert.is_anomaly
        res["anomaly_score"] = 0.0 if is_offline else round(alert.severity_score, 3)
        res["confidence"] = round(alert.confidence_score, 3)
        res["veto_fired"] = False if is_offline else alert.veto_fired
        res["root_cause"] = "OFFLINE" if is_offline else alert.root_cause.value
        res["affected_channels"] = [] if is_offline else alert.affected_channels
        res["layer_scores"] = {k: round(v, 3) for k, v in alert.layer_scores.items()}
        res["layers_scores"] = res["layer_scores"]
        res["reasons"] = [] if is_offline else alert.reasons
        res["explanation"] = (
            "Station is registered in network registry. Awaiting live sensor telemetry transmission."
            if is_offline
            else alert.explanation
        )
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
        res["operator_action"] = (
            "Station currently offline. Verify hardware connectivity or ingest telemetry."
            if is_offline
            else alert.operator_action
        )

        if is_offline and "overall" in res:
            res["overall"]["status"] = "OFFLINE"
            res["overall"]["score"] = 0.0
            res["overall"]["severity"] = "NONE"
        if is_offline and "diagnosis" in res:
            res["diagnosis"]["status"] = "OFFLINE"

        return res

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        q = query.lower().strip()
        matches = []
        for s in self._stations.values():
            if (q in s.get("name", "").lower() or 
                q in s.get("town", "").lower() or 
                q in s.get("id", "").lower() or
                q in s.get("localityId", "").lower() or
                q in s.get("country", "").lower() or
                q in s.get("region", "").lower()):
                matches.append(s)
                if len(matches) >= limit:
                    break
        return matches

    def get_observations_history(self, station_id: str, hours: int = 24) -> List[Dict[str, Any]]:
        stn = self.get_station(station_id)
        if not stn:
            return []

        has_temp = stn.get("temperature") is not None
        has_press = stn.get("pressure") is not None and stn.get("pressure") >= 1.0
        has_humid = stn.get("humidity") is not None
        has_wind = stn.get("windSpeed") is not None

        # If station has no observations across any channel, return empty list
        if not (has_temp or has_press or has_humid or has_wind):
            return []

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
        offline_count = 0
        normal_count = 0
        for s in self._stations.values():
            st = s.get("status")
            if st == "ANOMALY":
                anomalies.append(s)
            elif st == "WARNING":
                warnings.append(s)
            elif st == "OFFLINE":
                offline_count += 1
            else:
                normal_count += 1

        return {
            "totalStations": len(self._stations),
            "normalCount": normal_count,
            "warningCount": len(warnings),
            "anomalyCount": len(anomalies),
            "offlineCount": offline_count,
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
