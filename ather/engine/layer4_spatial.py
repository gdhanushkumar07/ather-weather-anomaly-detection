"""
Layer 4: Spatial / Neighbor Analysis Engine.
Cross-validates an AWS station's telemetry against neighboring stations within geographical radius.
Features:
- Haversine distance weighting (IDW)
- Thermodynamic elevation / lapse-rate adjustments
- Cluster residual variance scoring
- Distinguishes localized sensor failure from regional weather fronts.
"""
from typing import Dict, List, Optional, Tuple
import numpy as np

from ather.config import CONFIG, SpatialThresholds
from ather.data.schema import AWSReading

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    r = 6371.0 # Earth radius in km
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)

    a = np.sin(dphi / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0)**2
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return float(r * c)

class SpatialNeighborLayer:
    """
    Evaluates spatial consistency with nearby weather stations.
    """
    def __init__(self, config: SpatialThresholds = CONFIG.spatial):
        self.cfg = config

    def evaluate(
        self,
        target_reading: AWSReading,
        neighbor_readings: List[AWSReading]
    ) -> Tuple[float, Dict[str, float], Optional[str]]:
        """
        Compares target_reading against contemporary neighbor_readings.
        Returns:
            anomaly_score: float [0.0, 1.0]
            estimated_values: Dict[str, float] (IDW consensus estimates)
            reason: Optional[str]
        """
        # Filter valid neighbors within max radius excluding the target station itself
        valid_neighbors = []
        weights = []

        for n in neighbor_readings:
            if n.station_id == target_reading.station_id:
                continue
            dist = haversine_distance_km(target_reading.lat, target_reading.lon, n.lat, n.lon)
            if dist <= self.cfg.neighbor_distance_km_max:
                valid_neighbors.append((n, dist))
                # Inverse distance squared weight
                w = 1.0 / (max(dist, 1.0) ** 2)
                weights.append(w)

        if len(valid_neighbors) < self.cfg.min_neighbors_required:
            # Not enough neighbors; return neutral score with no penalty
            return 0.0, {
                "temperature_c": target_reading.temperature_c,
                "pressure_hpa": target_reading.pressure_hpa,
                "humidity_pct": target_reading.humidity_pct
            }, None

        weights = np.array(weights)
        norm_weights = weights / np.sum(weights)

        # Apply elevation adjustment to neighbor readings before consensus
        # Lapse rates: T = -6.5°C / 1000m, P = ~0.12 hPa / m
        t_estimates = []
        p_estimates = []
        rh_estimates = []

        for n, _ in valid_neighbors:
            dh = target_reading.elevation_m - n.elevation_m
            t_adj = n.temperature_c - 0.0065 * dh
            p_adj = n.pressure_hpa - 0.12 * dh
            rh_adj = np.clip(n.humidity_pct, 0.0, 100.0)

            t_estimates.append(t_adj)
            p_estimates.append(p_adj)
            rh_estimates.append(rh_adj)

        # Weighted IDW consensus estimates
        t_consensus = float(np.sum(norm_weights * np.array(t_estimates)))
        p_consensus = float(np.sum(norm_weights * np.array(p_estimates)))
        rh_consensus = float(np.sum(norm_weights * np.array(rh_estimates)))

        # Compute deviations
        d_t = abs(target_reading.temperature_c - t_consensus)
        d_p = abs(target_reading.pressure_hpa - p_consensus)
        d_rh = abs(target_reading.humidity_pct - rh_consensus)

        # Standard deviations across neighbor cluster
        t_std = max(0.75, float(np.std(t_estimates)))
        p_std = max(0.50, float(np.std(p_estimates)))
        rh_std = max(3.0, float(np.std(rh_estimates)))

        z_t = d_t / t_std
        z_p = d_p / p_std
        z_rh = d_rh / rh_std

        reasons = []
        scores = []

        if z_t > self.cfg.spatial_z_threshold:
            s_t = min(1.0, (z_t - self.cfg.spatial_z_threshold) / 3.0 + 0.5)
            scores.append(s_t)
            reasons.append(f"Temperature disagrees with {len(valid_neighbors)} neighbors by {d_t:.1f}°C ({z_t:.1f} sigma)")

        if z_p > self.cfg.spatial_z_threshold:
            s_p = min(1.0, (z_p - self.cfg.spatial_z_threshold) / 3.0 + 0.5)
            scores.append(s_p)
            reasons.append(f"Pressure disagrees with neighbors by {d_p:.1f} hPa ({z_p:.1f} sigma)")

        if z_rh > self.cfg.spatial_z_threshold:
            s_rh = min(1.0, (z_rh - self.cfg.spatial_z_threshold) / 3.0 + 0.5)
            scores.append(s_rh)
            reasons.append(f"Humidity disagrees with neighbors by {d_rh:.1f}% ({z_rh:.1f} sigma)")

        overall_score = max(scores) if scores else 0.0
        reason_str = "; ".join(reasons) if reasons else None

        consensus_dict = {
            "temperature_c": t_consensus,
            "pressure_hpa": p_consensus,
            "humidity_pct": rh_consensus
        }

        return overall_score, consensus_dict, reason_str
