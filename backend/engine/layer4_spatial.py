"""
Layer 4: Spatial / Neighbor Analysis Engine (v2).

CORRECTNESS RULES (v2):
  - Only uses neighbors whose target channel has DataQuality == VALID.
  - Reports neighbor_count and distance range in output.
  - Confidence in spatial conclusion scales with neighbor count:
      < 2 usable neighbors  → score capped at 0.5 (low confidence)
      2–4 neighbors         → normal scoring
      5+ neighbors          → full scoring
  - Distinguishes "no usable neighbors" from "insufficient neighbors for conclusion".
  - Returns structured detail with: neighbor_count, distance_range_km,
    target_value, consensus_value, deviation, z_score.
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from config import CONFIG, SpatialThresholds
from schema import AWSReading, DataQuality


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r    = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a    = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    return float(r * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a)))


class SpatialNeighborLayer:
    """
    Cross-validates a station's telemetry against nearby stations.
    """
    def __init__(self, config: SpatialThresholds = CONFIG.spatial):
        self.cfg = config

    def evaluate(
        self,
        target_reading:   AWSReading,
        neighbor_readings: List[AWSReading]
    ) -> Tuple[float, Dict[str, Optional[float]], Optional[str], Dict[str, Any]]:
        """
        Compares target_reading against valid neighbor_readings.
        Returns:
            anomaly_score:      float [0.0, 1.0]
            estimated_values:   Dict (IDW consensus per channel)
            reason:             Optional[str]
            detail:             Dict with neighbor_count, distances, deviations
        """
        target_lat  = target_reading.lat
        target_lon  = target_reading.lon
        target_elev = target_reading.elevation_m if target_reading.elevation_m is not None else 0.0

        # Find neighbors within radius
        valid_neighbors: List[Tuple[AWSReading, float, float]] = []  # (reading, dist_km, idw_weight)
        distances: List[float] = []

        for n in neighbor_readings:
            if n.station_id == target_reading.station_id:
                continue
            dist = haversine_distance_km(target_lat, target_lon, n.lat, n.lon)
            if dist <= self.cfg.neighbor_distance_km_max:
                w = 1.0 / max(dist, 1.0) ** 2
                valid_neighbors.append((n, dist, w))
                distances.append(dist)

        consensus_dict: Dict[str, Optional[float]] = {
            "temperature_c": None,
            "pressure_hpa":  None,
            "humidity_pct":  None,
        }
        detail: Dict[str, Any] = {
            "total_neighbors_in_radius": len(valid_neighbors),
            "distance_range_km": {
                "min": round(min(distances), 1) if distances else None,
                "max": round(max(distances), 1) if distances else None,
            },
            "channel_results": {},
        }

        if len(valid_neighbors) < self.cfg.min_neighbors_required:
            detail["status"] = "INSUFFICIENT_NEIGHBORS"
            detail["note"]   = (
                f"Only {len(valid_neighbors)} station(s) within {self.cfg.neighbor_distance_km_max} km. "
                f"Spatial analysis requires ≥ {self.cfg.min_neighbors_required}."
            )
            return 0.0, consensus_dict, None, detail

        # Confidence modifier based on neighbor count
        # < 5 neighbors → reduce max possible score to reflect lower certainty
        n_count              = len(valid_neighbors)
        confidence_cap       = 1.0 if n_count >= 5 else (0.75 if n_count >= 3 else 0.5)
        detail["confidence_cap_reason"] = f"{n_count} neighbors (cap={confidence_cap})"

        reasons: List[str] = []
        scores:  List[float] = []

        def _channel_consensus(
            ch_name:      str,
            get_val:      callable,
            lapse_adj:    callable,
            min_std:      float,
        ):
            """Compute IDW consensus for a single channel using only VALID neighbor readings."""
            target_val = get_val(target_reading)
            t_quality  = target_reading.data_quality.get(ch_name, DataQuality.MISSING)

            if t_quality != DataQuality.VALID or target_val is None:
                detail["channel_results"][ch_name] = {
                    "status": f"TARGET_{t_quality.upper()}", "score": 0.0
                }
                return 0.0, None

            estimates: List[float] = []
            weights:   List[float] = []

            for (n, dist, w) in valid_neighbors:
                n_val     = get_val(n)
                n_quality = n.data_quality.get(ch_name, DataQuality.MISSING)
                if n_quality == DataQuality.VALID and n_val is not None:
                    n_elev  = n.elevation_m if n.elevation_m is not None else 0.0
                    adj_val = lapse_adj(n_val, target_elev, n_elev)
                    estimates.append(adj_val)
                    weights.append(w)

            usable = len(estimates)
            if usable < self.cfg.min_neighbors_required:
                detail["channel_results"][ch_name] = {
                    "status": "INSUFFICIENT_VALID_NEIGHBORS",
                    "usable_neighbors": usable,
                    "score": 0.0
                }
                return 0.0, None

            w_arr     = np.array(weights)
            w_norm    = w_arr / np.sum(w_arr)
            consensus = float(np.sum(w_norm * np.array(estimates)))

            deviation = abs(target_val - consensus)
            std       = max(min_std, float(np.std(estimates)))
            z         = deviation / std

            consensus_dict[ch_name] = round(consensus, 2)

            ch_result: Dict[str, Any] = {
                "target_value":   target_val,
                "consensus_value": round(consensus, 2),
                "deviation":      round(deviation, 3),
                "z_score":        round(z, 2),
                "usable_neighbors": usable,
                "method":         "IDW_lapse_rate_adjusted",
            }

            raw_score = 0.0
            if z > self.cfg.spatial_z_threshold:
                raw_score = min(1.0, (z - self.cfg.spatial_z_threshold) / 3.0 + 0.5)
                raw_score = min(raw_score, confidence_cap)
                ch_result["score"] = round(raw_score, 3)
                ch_result["flagged"] = True
            else:
                ch_result["score"] = 0.0
                ch_result["flagged"] = False

            detail["channel_results"][ch_name] = ch_result
            return raw_score, ch_result

        # ── Temperature ───────────────────────────────────────────────────
        t_score, t_res = _channel_consensus(
            "temperature_c",
            lambda r: r.temperature_c,
            lambda val, te, ne: val - 0.0065 * (te - ne),  # lapse rate -6.5°C/1000m
            min_std=1.0
        )
        if t_score > 0 and t_res:
            scores.append(t_score)
            reasons.append(
                f"Temperature {t_res['target_value']:.1f}°C disagrees with "
                f"{t_res['usable_neighbors']} neighbor consensus "
                f"({t_res['consensus_value']:.1f}°C) by {t_res['deviation']:.1f}°C "
                f"({t_res['z_score']:.1f}σ)"
            )

        # ── Pressure ──────────────────────────────────────────────────────
        p_score, p_res = _channel_consensus(
            "pressure_hpa",
            lambda r: r.pressure_hpa,
            lambda val, te, ne: val - 0.12 * (te - ne),    # -0.12 hPa/m lapse
            min_std=0.8
        )
        if p_score > 0 and p_res:
            scores.append(p_score)
            reasons.append(
                f"Pressure {p_res['target_value']:.1f} hPa disagrees with neighbor "
                f"consensus ({p_res['consensus_value']:.1f} hPa) by {p_res['deviation']:.1f} hPa "
                f"({p_res['z_score']:.1f}σ)"
            )

        # ── Humidity ──────────────────────────────────────────────────────
        rh_score, rh_res = _channel_consensus(
            "humidity_pct",
            lambda r: r.humidity_pct,
            lambda val, te, ne: float(np.clip(val, 0.0, 100.0)),  # no lapse adj for RH
            min_std=4.0
        )
        if rh_score > 0 and rh_res:
            scores.append(rh_score)
            reasons.append(
                f"Humidity {rh_res['target_value']:.1f}% disagrees with neighbor "
                f"consensus ({rh_res['consensus_value']:.1f}%) by {rh_res['deviation']:.1f}%"
            )

        overall_score = max(scores) if scores else 0.0
        detail["status"] = "EVALUATED"
        reason_str = "; ".join(reasons) if reasons else None
        return overall_score, consensus_dict, reason_str, detail
