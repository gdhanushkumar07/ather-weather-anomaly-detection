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

S1 UPDATE (Spatial Neighborhood Foundation): neighbor identification
(coordinate validation, self-exclusion, distance calculation, radius
filtering, deterministic distance sorting, K-nearest capping) now goes
through the single shared pipeline in engine/spatial_neighbors.py instead
of this file's own ad hoc loop, so this layer and
AnomalyDetector.get_neighbors_for_reading() can never disagree about what
counts as a valid, ranked neighbor. Everything downstream of that
selection -- IDW consensus, elevation lapse-rate correction, z-scoring,
confidence capping -- is UNCHANGED.

S2 UPDATE (Robust Spatial Statistics): each channel now ALSO computes a
median/MAD-based robust regional baseline alongside the existing IDW
baseline (engine/spatial_statistics.py), on the SAME elevation-adjusted,
DataQuality-filtered neighbor estimates the IDW baseline already uses. This
is intentionally ADDITIONAL evidence, exposed in `channel_results[ch]` as
regional_median/regional_mad/robust_z (plus idw_mean/idw_std/idw_z, the IDW
baseline under matching names, factored out but numerically unchanged) --
the anomaly SCORE below still comes from the same IDW z-score vs
spatial_z_threshold comparison as before S2. It is not yet fed into
scoring because S3 (Regional Event Attribution) is where evidence from
multiple baselines gets combined into a single decision; changing the score
here first would mean re-deriving that combination twice. See the S2 final
report for the full reasoning.

S3 UPDATE (Regional Event Attribution): once a channel's ROBUST z-score
(not the IDW-based `flagged` used for `score` below) clears the existing
spatial_z_threshold, this layer now ALSO builds evidence
(engine/spatial_attribution.py) for whether that deviation looks more
like an isolated sensor fault or a coherent regional event, from the SAME
neighbor estimates/weights/median/MAD S1+S2 already computed -- nothing
is recomputed. Robust_z is used for this gate (rather than idw_z) because
the plain standard deviation behind idw_z can itself be inflated by the
very outlier/minority-cluster population S3 needs to reason about,
suppressing idw_z below threshold in exactly the scenario S3 targets.
Exposed additively as `ch_result["attribution_evidence"]` (per channel)
and a new top-level `detail["regional_attribution"]` (combined across
channels). `score` and
`overall_score` are UNCHANGED by S3, same as S2's own scoring guarantee.

S6 UPDATE (Counterfactual Verification): once all 3 channels' S3 evidence
is collected, this layer ALSO builds a counterfactual verification result
(engine/spatial_counterfactual.py) answering "if the target were genuine,
do neighbors show the expected supporting response?" -- from the SAME
per-channel ChannelAttributionEvidence S3 already built, nothing
recomputed. Exposed additively as a new top-level
`detail["counterfactual_verification"]`. `score`, `overall_score`, and
`regional_attribution` are UNCHANGED by S6.
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from config import CONFIG, SpatialThresholds
from schema import AWSReading, DataQuality
from engine.spatial_neighbors import haversine_distance_km, select_k_nearest_neighbors  # noqa: F401 (re-exported for backward compatibility)
from engine.spatial_statistics import compute_robust_spatial_evidence
from engine.spatial_attribution import (
    ChannelAttributionEvidence,
    RegionalAttribution,
    compute_channel_attribution_evidence,
    aggregate_regional_attribution,
)
from engine.spatial_counterfactual import evaluate_counterfactual_verification


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

        # Find neighbors within radius — S1 foundation: coordinate
        # validation, self-exclusion, distance calc, radius filter,
        # deterministic distance sort, and K-nearest capping all happen in
        # one shared, tested place (engine/spatial_neighbors.py). This
        # replaces the previous ad hoc loop here without changing the IDW
        # weighting formula or anything downstream.
        selection = select_k_nearest_neighbors(
            target_reading,
            neighbor_readings,
            radius_km=self.cfg.neighbor_distance_km_max,
            k=self.cfg.spatial_k_neighbors,
        )
        # (reading, dist_km, idw_weight) — same shape/weight formula as before
        valid_neighbors: List[Tuple[AWSReading, float, float]] = [
            (c.reading, c.distance_km, 1.0 / max(c.distance_km, 1.0) ** 2)
            for c in selection.neighbors
        ]
        distances: List[float] = [c.distance_km for c in selection.neighbors]

        consensus_dict: Dict[str, Optional[float]] = {
            "temperature_c": None,
            "pressure_hpa":  None,
            "humidity_pct":  None,
        }
        detail: Dict[str, Any] = {
            # Total candidates within radius BEFORE the K-nearest cap — the
            # true pool size, unaffected by spatial_k_neighbors.
            "total_neighbors_in_radius": selection.within_radius_count,
            # Range of the neighbors actually used in this evaluation
            # (i.e. after the K-nearest cap).
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
            # S3: even the insufficient-evidence path reports a (trivial)
            # regional_attribution, so downstream consumers can always read
            # detail["regional_attribution"] without first branching on
            # status -- this IS the canonical "insufficient evidence"
            # UNCERTAIN case, not a special one.
            detail["regional_attribution"] = RegionalAttribution(
                classification="UNCERTAIN", confidence=0.0, applicable_channels=(),
                regional_event_evidence_strength=0.0, isolated_sensor_evidence_strength=0.0,
                explanation=(
                    f"Only {len(valid_neighbors)} station(s) within radius -- insufficient "
                    f"spatial evidence for attribution."
                ),
            ).to_dict({})
            # S6: same reasoning as regional_attribution above -- the
            # insufficient-neighbors path IS the canonical
            # INSUFFICIENT_EVIDENCE case for counterfactual verification too.
            detail["counterfactual_verification"] = evaluate_counterfactual_verification(
                {}, min_neighbors_required=self.cfg.min_neighbors_required,
                spatial_k_neighbors=self.cfg.spatial_k_neighbors,
            )
            return 0.0, consensus_dict, None, detail

        # Confidence modifier based on neighbor count
        # < 5 neighbors → reduce max possible score to reflect lower certainty
        n_count              = len(valid_neighbors)
        confidence_cap       = 1.0 if n_count >= 5 else (0.75 if n_count >= 3 else 0.5)
        detail["confidence_cap_reason"] = f"{n_count} neighbors (cap={confidence_cap})"

        reasons: List[str] = []
        scores:  List[float] = []
        channel_evidence: Dict[str, ChannelAttributionEvidence] = {}  # S3: populated per channel below

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

            # S2: one call computes BOTH the existing IDW baseline (mean/
            # std/z -- numerically identical to the previous inline code)
            # and the new median/MAD robust baseline, on the same
            # `estimates` (already DataQuality-filtered, already
            # elevation-lapse-adjusted). See engine/spatial_statistics.py.
            evidence  = compute_robust_spatial_evidence(estimates, weights, target_val, min_std)
            consensus = evidence["idw_mean"]
            deviation = evidence["deviation"]
            std       = evidence["idw_std"]
            z         = evidence["idw_z"]

            consensus_dict[ch_name] = round(consensus, 2)

            ch_result: Dict[str, Any] = {
                "target_value":   target_val,
                "consensus_value": round(consensus, 2),
                "deviation":      round(deviation, 3),
                "z_score":        round(z, 2),
                "usable_neighbors": usable,
                "method":         "IDW_lapse_rate_adjusted",
                # ── S2: robust spatial statistics (additional evidence;
                # does NOT change `score` below) ──────────────────────────
                "idw_mean":        round(evidence["idw_mean"], 3),
                "idw_std":         round(evidence["idw_std"], 3),
                "idw_z":           round(evidence["idw_z"], 3),
                "regional_median": round(evidence["regional_median"], 3),
                "regional_mad":    round(evidence["regional_mad"], 4),
                "robust_z":        round(evidence["robust_z"], 3),
                "robust_z_method": evidence["robust_z_method"],
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

            # S3: attribution evidence, built from the SAME estimates/
            # weights/regional_median/regional_mad S2 already computed
            # above -- nothing recomputed. The "is there anything to
            # attribute" gate deliberately uses ROBUST_Z vs the EXISTING
            # spatial_z_threshold, NOT the existing IDW-based `flagged`:
            # idw_z's plain standard deviation is itself inflated by the
            # very outlier population S3 needs to reason about (a minority
            # cluster of elevated neighbors pulls the ordinary std up,
            # which can suppress idw_z below threshold even when the
            # target's deviation from the ROBUST median is large and real
            # -- confirmed empirically while building this). robust_z is
            # exactly the statistic S2 built to resist that distortion, so
            # S3 uses it for its own applicability gate; the reused
            # threshold value (spatial_z_threshold) is unchanged, only the
            # statistic it is compared against differs from `score`/
            # `flagged` above. See engine/spatial_attribution.py.
            ch_evidence = compute_channel_attribution_evidence(
                channel=ch_name,
                target_value=target_val,
                target_flagged=abs(evidence["robust_z"]) > self.cfg.spatial_z_threshold,
                target_robust_z=evidence["robust_z"],
                regional_median=evidence["regional_median"],
                regional_mad=evidence["regional_mad"],
                neighbor_estimates=estimates,
                neighbor_weights=weights,
                min_std=min_std,
                spatial_k_neighbors=self.cfg.spatial_k_neighbors,
            )
            channel_evidence[ch_name] = ch_evidence
            ch_result["attribution_evidence"] = ch_evidence.to_dict()

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

        # S3: combine the per-channel attribution evidence collected above
        # into one overall classification. Purely additive -- overall_score/
        # consensus_dict/reason_str above are UNCHANGED by this call.
        regional_attribution = aggregate_regional_attribution(
            channel_evidence,
            min_neighbors_required=self.cfg.min_neighbors_required,
            spatial_k_neighbors=self.cfg.spatial_k_neighbors,
        )
        detail["regional_attribution"] = regional_attribution.to_dict(channel_evidence)

        # S6: counterfactual verification, built from the SAME
        # channel_evidence collected above -- nothing recomputed. Purely
        # additive; overall_score/consensus_dict/reason_str/
        # regional_attribution above are UNCHANGED by this call.
        detail["counterfactual_verification"] = evaluate_counterfactual_verification(
            channel_evidence,
            min_neighbors_required=self.cfg.min_neighbors_required,
            spatial_k_neighbors=self.cfg.spatial_k_neighbors,
            s3_classification=regional_attribution.classification,
            s3_confidence=regional_attribution.confidence,
        )

        return overall_score, consensus_dict, reason_str, detail
