"""
ATHER Anomaly Detection Engine (v2)
-----------------------------------
Integrates the 5-Layer Physics, Temporal, Multivariate, Spatial, and Sensor Drift layers
with Conformal Evidence Fusion, Root-Cause Diagnosis, Self-Healing Imputation,
Meteorological Weather Analysis, and Canonical AnalysisResult generation.
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from config import CONFIG
from schema import (
    AWSReading, AnomalyAlert, FaultType, DiagnosisConfidence,
    DataQuality, station_dict_to_reading
)

from engine.layer1_physics import PhysicsValidationLayer
from engine.layer2_temporal import TemporalPatternLayer
from engine.layer3_multivariate import MultivariateConsistencyLayer, resolve_pressure_convention
from engine.layer4_spatial import SpatialNeighborLayer
from engine.spatial_neighbors import NeighborSelectionResult, observation_time, select_k_nearest_neighbors
from engine.layer5_drift import SensorDriftHealthLayer
from engine.spatial_clustering import ClusterCandidate, build_cluster_candidate, cluster_anomalous_stations
from engine.spatial_event_tracking import SpatialEventTracker
from fusion.conformal_fusion import ConformalEvidenceFusion
from root_cause.classifier import RootCauseClassifier, DiagnosisResult
from root_cause.explainability import ExplanationGenerator
from root_cause.self_healing import SelfHealingImputer


class AnomalyDetector:
    """
    Comprehensive anomaly detection system combining 5 meteorological detection layers,
    conformal evidence fusion, automated root cause analysis, weather interpretation,
    and canonical result synthesis.
    """
    def __init__(self):
        self.layer1 = PhysicsValidationLayer(CONFIG.physics)
        self.layer2 = TemporalPatternLayer(CONFIG.temporal)
        self.layer3 = MultivariateConsistencyLayer()
        self.layer4 = SpatialNeighborLayer(CONFIG.spatial)
        self.layer5 = SensorDriftHealthLayer(CONFIG.drift)

        self.fusion = ConformalEvidenceFusion(CONFIG.fusion)
        self.classifier = RootCauseClassifier()
        self.explainer = ExplanationGenerator()
        self.imputer = SelfHealingImputer()

        # Cache of latest AnomalyAlert and CanonicalResult per station
        self._alerts_cache: Dict[str, AnomalyAlert] = {}
        self._canonical_cache: Dict[str, Dict[str, Any]] = {}
        # Reference readings for spatial neighbor lookups
        self._spatial_pool: Dict[str, AWSReading] = {}
        # Station metadata cache (name, etc.)
        self._station_meta: Dict[str, Dict[str, Any]] = {}
        # S5 — Event Evolution: one explicitly-owned tracker per detector
        # instance (never a module-level global; see
        # engine/spatial_event_tracking.py's "STATE MANAGEMENT" section).
        self._spatial_event_tracker = SpatialEventTracker()

    @staticmethod
    def _guarded_layer(name: str, call, neutral):
        """Runs one layer; on any exception returns neutral(detail) where
        detail marks the layer as unavailable (never a fabricated result)."""
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 -- deliberate: no single layer may abort evaluation
            return neutral({
                "layer_unavailable": True,
                "status": "UNAVAILABLE",
                "unavailable_layer": name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    def update_spatial_pool(self, readings: List[AWSReading]):
        """Updates the internal spatial neighbor registry (latest observation
        per station).

        An OLDER observation never overwrites a NEWER one for the same
        station: if both carry a known observation time and the incoming one is
        strictly earlier (an out-of-order / replayed / backfilled reading), the
        registry keeps the newer reading. Readings with an unknown observation
        time cannot be ordered, so they replace as before."""
        for r in readings:
            existing = self._spatial_pool.get(r.station_id)
            if existing is not None:
                new_t, old_t = observation_time(r), observation_time(existing)
                if new_t is not None and old_t is not None and new_t < old_t:
                    continue
            self._spatial_pool[r.station_id] = r

    def register_station_metadata(self, station_id: str, meta: Dict[str, Any]):
        """Stores station metadata for canonical result enrichment."""
        self._station_meta[station_id] = meta

    def get_neighbors_for_reading(
        self, reading: AWSReading, max_neighbors: Optional[int] = None
    ) -> List[AWSReading]:
        """
        Finds the K nearest valid neighbor readings within the spatial
        radius, ranked by true great-circle distance (S1 foundation, see
        engine/spatial_neighbors.py). Deterministic: same pool + same
        target always yields the same ordered neighbor list, independent
        of dict-iteration order.

        max_neighbors overrides the configured K (CONFIG.spatial.
        spatial_k_neighbors) for this call only; omit it to use the
        configured default (8, unchanged from the previous hardcoded value).
        """
        return [c.reading for c in self._select_neighbors(reading, max_neighbors).neighbors]

    def _select_neighbors(
        self, reading: AWSReading, max_neighbors: Optional[int] = None
    ) -> NeighborSelectionResult:
        """Pool-level neighbor selection WITH its exclusion accounting.

        Only same-source neighbors observed within
        CONFIG.spatial.neighbor_time_tolerance_minutes of the target are
        eligible (see engine/spatial_neighbors.select_k_nearest_neighbors)."""
        k = max_neighbors if max_neighbors is not None else CONFIG.spatial.spatial_k_neighbors
        return select_k_nearest_neighbors(
            reading,
            self._spatial_pool.values(),
            radius_km=CONFIG.spatial.neighbor_distance_km_max,
            k=k,
            max_time_diff_minutes=CONFIG.spatial.neighbor_time_tolerance_minutes,
            require_same_source=True,
        )

    def evaluate_station(
        self,
        station_data: Dict[str, Any],
        neighbors: Optional[List[AWSReading]] = None
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Evaluates current station observations and returns:
        (status, legacy_anomaly_dict_or_None)
        """
        stn_id = str(station_data.get("id", ""))
        if stn_id and station_data.get("name"):
            self.register_station_metadata(stn_id, station_data)

        reading = station_dict_to_reading(station_data)
        alert = self.evaluate_reading(reading, neighbors=neighbors, station_data=station_data)
        return alert.status, alert.to_legacy_dict()

    def evaluate_reading(
        self,
        reading: AWSReading,
        neighbors: Optional[List[AWSReading]] = None,
        station_data: Optional[Dict[str, Any]] = None
    ) -> AnomalyAlert:
        """
        Full 5-layer anomaly evaluation pipeline producing both an AnomalyAlert
        and a Canonical §16 AnalysisResult.
        """
        stn_id = reading.station_id
        meta = station_data or self._station_meta.get(stn_id, {})
        stn_name = meta.get("name", f"Station {stn_id}")

        # S7 graceful degradation: every layer call is guarded (see
        # _guarded_layer). A layer that raises contributes a NEUTRAL score
        # (0.0, the same value the layers already use for "no evidence"),
        # no reason text, and an explicit {"layer_unavailable": True}
        # marker that the canonical card surfaces as status UNAVAILABLE --
        # missing evidence is exposed, never turned into a fault signal,
        # and the remaining layers still reach fusion.
        # ── 1. Layer 1: Physics Validation (MetPy & Psychrometric boundaries) ──
        score_l1, veto_fired, reason_l1, detail_l1 = self._guarded_layer(
            "physics", lambda: self.layer1.evaluate(reading),
            lambda d: (0.0, False, None, d))

        # ── 2. Layer 2: Temporal Pattern (Spikes, Frozen Sensor, Statistical Z-score) ──
        score_l2, ch_scores_l2, reason_l2, detail_l2 = self._guarded_layer(
            "temporal", lambda: self.layer2.evaluate(reading),
            lambda d: (0.0, {}, None, d))

        # ── 3. Layer 3: Multivariate Consistency (Joint State Manifold) ──
        score_l3, reason_l3, detail_l3 = self._guarded_layer(
            "multivariate", lambda: self.layer3.evaluate(reading),
            lambda d: (0.0, None, d))

        # ── 4. Layer 4: Spatial Neighbor Consensus (IDW Lapse-rate cross check) ──
        pool_selection: Optional[NeighborSelectionResult] = None
        if neighbors is None:
            pool_selection = self._select_neighbors(reading)
            neighbors = [c.reading for c in pool_selection.neighbors]
        # Only pass the pool-level selection accounting when this detector
        # itself selected the neighbors from its pool (a caller-supplied
        # neighbor list has no pool-level accounting to forward).
        layer4_kwargs = {"upstream_selection": pool_selection} if pool_selection is not None else {}
        score_l4, spatial_consensus, reason_l4, detail_l4 = self._guarded_layer(
            "spatial", lambda: self.layer4.evaluate(reading, neighbors, **layer4_kwargs),
            lambda d: (0.0, {"temperature_c": None, "pressure_hpa": None, "humidity_pct": None}, None, d))

        # ── 5. Layer 5: Sensor Drift & Health Tracking (CUSUM & Days to failure) ──
        recent_is_anomaly = bool(veto_fired or score_l1 > 0.7 or score_l2 > 0.7)
        score_l5, health_score, days_to_failure, reason_l5, detail_l5 = self._guarded_layer(
            "drift", lambda: self.layer5.evaluate(reading, recent_is_anomaly=recent_is_anomaly),
            lambda d: (0.0, 100.0, None, None, d))
        # Default to True (assume physical) unless the source is AFFIRMATIVELY
        # known to be a model reference — an UNKNOWN/untagged source (legacy
        # callers, tests) must not be treated as non-physical by default.
        is_physical_sensor = reading.source != "NWP_MODEL_REFERENCE"
        if not is_physical_sensor:
            # "Days to hardware-tolerance-breach" is meaningless for a value
            # that was never measured by a physical sensor (Phase 27 guard).
            days_to_failure = None
            detail_l5["note_non_physical_source"] = (
                "Sensor Health/Drift metrics are not applicable: this observation "
                "is a NWP model reference, not a physical AWS sensor reading."
            )

        # Assemble layer scores
        layer_scores = {
            "physics": round(float(score_l1), 3),
            "temporal": round(float(score_l2), 3),
            "multivariate": round(float(score_l3), 3),
            "spatial": round(float(score_l4), 3),
            "drift": round(float(score_l5), 3)
        }

        # Gather diagnostic reasons
        reasons = [r for r in [reason_l1, reason_l2, reason_l3, reason_l4, reason_l5] if r]

        # Identify affected channels
        affected = []
        if ch_scores_l2.get("temperature_c", 0) > 0.5 or (score_l1 > 0.5 and "temp" in (reason_l1 or "").lower()):
            affected.append("temperature_c")
        if ch_scores_l2.get("pressure_hpa", 0) > 0.5 or (score_l1 > 0.5 and "press" in (reason_l1 or "").lower()):
            affected.append("pressure_hpa")
        if ch_scores_l2.get("humidity_pct", 0) > 0.5 or (score_l1 > 0.5 and "humid" in (reason_l1 or "").lower()):
            affected.append("humidity_pct")
        if not affected and (score_l4 > 0.5 or score_l3 > 0.5 or veto_fired):
            if reading.channel_valid("temperature_c"):
                affected.append("temperature_c")
            elif reading.channel_valid("pressure_hpa"):
                affected.append("pressure_hpa")
            elif reading.channel_valid("humidity_pct"):
                affected.append("humidity_pct")

        # Layer coverage metrics for conformal fusion
        layer_coverage = {
            "physics": len(detail_l1.get("channels_evaluated", [])) / 3.0,
            "temporal": 1.0 if detail_l2.get("history_points", 0) >= 3 else 0.2,
            # Interface contract: layer3 reports its valid-channel count as "n_valid"; this used to
            # read "valid_channel_count" (never set), so multivariate coverage was ALWAYS 0. Both keys
            # are accepted so a change of the layer's key name cannot silently zero it again.
            "multivariate": detail_l3.get("n_valid", detail_l3.get("valid_channel_count", 0)) / 3.0,
            # S7 BUGFIX: layer4_spatial.py has always set
            # "total_neighbors_in_radius" (never "neighbor_count"), so this
            # used to always evaluate to 0 -- forcing fusion's
            # "spatial_score > 0.1 and spatial_neighbor_count < 3 -> x0.85
            # confidence" scarcity penalty to fire on every station with any
            # spatial signal, regardless of real neighbor availability.
            "spatial": min(1.0, detail_l4.get("total_neighbors_in_radius", 0) / 4.0),
            "drift": min(1.0, detail_l5.get("samples_tracked", 0) / 20.0),
        }

        spatial_neighbor_count = detail_l4.get("total_neighbors_in_radius", 0)
        temporal_history_count = detail_l2.get("history_points", 0)

        # ── 6. Evidence Fusion (evidence-availability aware; heuristic, NOT calibrated) ──
        # A layer that could not assess the observation is UNAVAILABLE - not "assessed and normal".
        layer_availability = self._layer_availability(
            detail_l1, detail_l2, detail_l3, detail_l4, detail_l5, reading
        )
        spatial_context = {
            "attribution": (detail_l4.get("regional_attribution") or {}).get("classification"),
            "counterfactual": (detail_l4.get("counterfactual_verification") or {}).get("overall_status"),
        }
        is_anomaly, status, severity, confidence, p_val, detail_fusion = self.fusion.fuse(
            layer_scores=layer_scores,
            veto_fired=veto_fired,
            layer_coverage=layer_coverage,
            spatial_neighbor_count=spatial_neighbor_count,
            temporal_history_count=temporal_history_count,
            layer_availability=layer_availability,
            spatial_context=spatial_context,
        )

        layer_details = {
            "physics": detail_l1,
            "temporal": detail_l2,
            "multivariate": detail_l3,
            "spatial": detail_l4,
            "drift": detail_l5,
            "fusion": detail_fusion,
        }

        # ── 7. Root Cause Analysis (v2: uncertainty tiers & weather vs sensor) ──
        diagnosis_res: DiagnosisResult = self.classifier.classify(
            is_anomaly=is_anomaly,
            layer_scores=layer_scores,
            veto_fired=veto_fired,
            channel_scores=ch_scores_l2,
            spatial_score=score_l4,
            reasons=reasons,
            layer_details=layer_details,
            valid_channel_count=reading.valid_channel_count
        )
        diagnosis_res = self._contextualize_diagnosis_for_source(diagnosis_res, reading.source)

        # ── 8. Explainability (v2: confidence-gated language) ──
        explanation = self.explainer.generate_explanation(
            reading=reading,
            fault_type=diagnosis_res.fault_type,
            diagnosis_confidence=diagnosis_res.confidence,
            layer_scores=layer_scores,
            reasons=reasons,
            sensor_health=health_score,
            days_to_failure=days_to_failure,
            primary_signal=diagnosis_res.primary_signal,
            alternatives=diagnosis_res.alternatives,
            layer_details=layer_details
        )

        # ── 9. Self-Healing Imputation (EVIDENCE-GATED) ──
        # The raw observation is NEVER overwritten (raw_values / observation always carry it). An
        # estimated / trusted value is produced ONLY when the evidence justifies replacing a
        # specific channel: see _estimation_decision.
        temporal_fallback = {
            "temperature_c": reading.temperature_c,
            "pressure_hpa": reading.pressure_hpa,
            "humidity_pct": reading.humidity_pct
        }
        estimation = self._estimation_decision(is_anomaly, diagnosis_res, affected, detail_l4)
        corrected = self.imputer.correct_reading(
            reading=reading,
            is_anomaly=estimation["justified"],
            affected_channel=estimation["channel"],
            spatial_consensus=spatial_consensus,
            temporal_fallback=temporal_fallback
        )
        estimation["applied_channels"] = [
            ch for ch, v in corrected.items()
            if v is not None and getattr(reading, ch, None) is not None and v != getattr(reading, ch)
        ]
        estimation["applied"] = bool(estimation["applied_channels"])
        if estimation["justified"] and not estimation["applied"]:
            estimation["reason"] = "Justified, but no independent estimate was available (insufficient neighbor consensus); the raw value is kept."

        # ── 10. Meteorological Weather Analysis (Section 14) ──
        weather_analysis = self._generate_weather_analysis(
            reading=reading,
            layer_details=layer_details,
            status=status
        )

        # ── 11. Human-Operator Insights (Section 15) ──
        insights = self._generate_insights(
            reading=reading,
            diagnosis=diagnosis_res,
            status=status,
            severity=severity,
            confidence=confidence,
            layer_scores=layer_scores,
            layer_details=layer_details,
            explanation=explanation
        )

        # ── 12. Data Quality Provenance (Section 4, 16) ──
        data_quality_dict = self._generate_data_quality(
            reading=reading,
            layer_details=layer_details
        )

        # ── 13. Canonical Layer Cards (Section 21) ──
        canonical_layers = self._format_canonical_layers(
            layer_scores=layer_scores,
            layer_details=layer_details,
            veto_fired=veto_fired,
            reason_l1=reason_l1,
            reason_l2=reason_l2,
            reason_l3=reason_l3,
            reason_l4=reason_l4,
            reason_l5=reason_l5,
            health_score=health_score,
            is_physical_sensor=is_physical_sensor,
        )

        # Build Canonical §16 Analysis Object
        canonical_result = {
            "station": {
                "id": stn_id,
                "name": stn_name,
                "latitude": reading.lat,
                "longitude": reading.lon,
            },
            "observation": {
                "timestamp": (reading.observation_timestamp or reading.received_timestamp).isoformat(),
                "temperature": reading.temperature_c,
                "pressure": reading.pressure_hpa,
                # MSL / SURFACE / UNKNOWN as resolved for this reading (never guessed).
                "pressure_convention": resolve_pressure_convention(reading)[0],
                "relative_humidity": reading.humidity_pct,
                "wind_speed": reading.wind_speed_kmh,
                # Never hardcode "AWS Station Data" — reflect the verified
                # provenance computed at ingestion (Phase 1-4, 20, 27).
                "source": reading.source,
                "freshness": reading.freshness,
                "observation_timestamp": reading.observation_timestamp.isoformat() if reading.observation_timestamp else None,
                "received_timestamp": reading.received_timestamp.isoformat() if reading.received_timestamp else None,
            },
            "evidence_availability": layer_availability,
            "estimation": estimation,
            "overall": {
                "status": status,
                "score": round(severity, 3),
                "anomaly_score": round(severity, 3),
                "confidence": round(confidence, 3),
                # honest labeling: not a calibrated probability
                "confidence_basis": detail_fusion.get("confidence_basis"),
                "evidence_sufficiency": detail_fusion.get("evidence_sufficiency"),
                "threshold": 0.45,
                "severity": (
                    "HIGH" if severity >= 0.75 else
                    "WARNING" if severity >= 0.45 else
                    "LOW" if severity > 0.0 else "NONE"
                ),
            },
            "layers": canonical_layers,
            "diagnosis": {
                "primary": diagnosis_res.fault_type.value,
                "confidence": diagnosis_res.confidence.value,
                "confidence_level": diagnosis_res.confidence.value,
                "evidence": diagnosis_res.evidence,
                "alternatives": diagnosis_res.alternatives,
                "affected_channels": affected,
                "operator_action": diagnosis_res.operator_action,
                # S7: S3/S6 spatial corroboration state (additive; None when
                # not applicable). Evidence states, not probabilities.
                "spatial_corroboration": diagnosis_res.spatial_corroboration,
            },
            "weather_analysis": weather_analysis,
            "insights": insights,
            "data_quality": data_quality_dict
        }

        # Build AnomalyAlert
        alert = AnomalyAlert(
            station_id=stn_id,
            timestamp=reading.timestamp,
            status=status,
            is_anomaly=is_anomaly,
            severity_score=severity,
            confidence_score=confidence,
            veto_fired=veto_fired,
            root_cause=diagnosis_res.fault_type,
            diagnosis_confidence=diagnosis_res.confidence,
            affected_channels=affected,
            layer_scores=layer_scores,
            layer_details=layer_details,
            reasons=reasons,
            explanation=explanation,
            primary_signal=diagnosis_res.primary_signal,
            alternative_causes=diagnosis_res.alternatives,
            raw_values={
                "temperature_c": reading.temperature_c,
                "pressure_hpa": reading.pressure_hpa,
                "humidity_pct": reading.humidity_pct,
                "wind_speed_kmh": reading.wind_speed_kmh,
            },
            corrected_values=corrected,
            sensor_health_index=health_score,
            estimated_days_to_failure=days_to_failure,
            spatial_neighbor_count=spatial_neighbor_count,
            spatial_neighbor_range_km=(detail_l4.get("distance_range_km") or {}).get("min"),
            temporal_history_points=temporal_history_count,
            data_quality_summary=data_quality_dict,
            operator_action=diagnosis_res.operator_action,
            canonical_result=canonical_result
        )

        self._alerts_cache[stn_id] = alert
        self._canonical_cache[stn_id] = canonical_result
        return alert

    @staticmethod
    def _layer_availability(d1, d2, d3, d4, d5, reading) -> Dict[str, Dict[str, Any]]:
        """Which layers could actually ASSESS this observation. Distinguishes
        "assessed and normal" (available, score 0) from "could not assess"
        (unavailable: insufficient history / neighbors / samples, layer failure,
        not applicable). Uses each layer's own reported status."""
        def entry(available: bool, reason: Optional[str]) -> Dict[str, Any]:
            return {"available": bool(available), "reason": None if available else reason}

        def failed(d):  # a guarded layer that raised
            return bool(d.get("layer_unavailable"))

        out: Dict[str, Dict[str, Any]] = {}
        out["physics"] = entry(
            not failed(d1) and bool(d1.get("channels_evaluated")),
            "layer failed" if failed(d1) else "no valid channel could be physically evaluated")
        out["temporal"] = entry(
            not failed(d2) and d2.get("status") == "EVALUATED",
            "layer failed" if failed(d2) else (d2.get("note") or "insufficient temporal history"))
        out["multivariate"] = entry(
            not failed(d3) and d3.get("status") == "EVALUATED",
            "layer failed" if failed(d3) else (d3.get("note") or "fewer than 2 valid channels"))
        out["spatial"] = entry(
            not failed(d4) and d4.get("status") == "EVALUATED",
            "layer failed" if failed(d4) else (d4.get("note") or "insufficient simultaneous same-source neighbors"))
        non_physical = reading.source == "NWP_MODEL_REFERENCE"
        out["drift"] = entry(
            not failed(d5) and d5.get("status") == "EVALUATED" and not non_physical,
            "layer failed" if failed(d5) else (
                "not a physical sensor (NWP model reference)" if non_physical
                else (d5.get("note") or "insufficient samples for drift assessment")))
        return out

    # Fault categories that assert a sensor-side problem for which replacing the reading with an
    # independent estimate can be justified. CALIBRATION_DRIFT is excluded on purpose: a drifting
    # sensor's value is evidence to investigate, not an outlier to overwrite.
    _ESTIMATION_ELIGIBLE_FAULTS = {
        FaultType.SENSOR_SPIKE, FaultType.FROZEN_SENSOR,
        FaultType.SINGLE_CHANNEL_FAULT, FaultType.NOISE_BURST,
    }

    def _estimation_decision(self, is_anomaly: bool, diagnosis_res, affected: List[str],
                             detail_l4: Dict[str, Any]) -> Dict[str, Any]:
        """Decides whether an estimated/trusted value is JUSTIFIED. All of:
          - the observation is anomalous and diagnosed as a sensor-side fault (never genuine
            weather, never INSUFFICIENT_EVIDENCE / NORMAL / drift);
          - the diagnosis is at least MEDIUM confidence;
          - neighbors do NOT support the reading (counterfactual not SUPPORTED, attribution not
            REGIONAL_EVENT) - if the region backs the value, it is not replaced;
          - a specific affected channel was identified (never a blanket replacement).
        The raw value is preserved in every case."""
        cf = (detail_l4.get("counterfactual_verification") or {}).get("overall_status")
        ra = (detail_l4.get("regional_attribution") or {}).get("classification")
        verdict = {"justified": False, "channel": None, "applied": False, "applied_channels": [],
                   "reason": None, "raw_value_preserved": True, "basis": None}
        if not is_anomaly:
            verdict["reason"] = "No anomaly: the observation is used as reported."
        elif diagnosis_res.fault_type not in self._ESTIMATION_ELIGIBLE_FAULTS:
            verdict["reason"] = f"Diagnosis {diagnosis_res.fault_type.value} does not justify replacing the observation."
        elif diagnosis_res.confidence not in (DiagnosisConfidence.MEDIUM, DiagnosisConfidence.HIGH):
            verdict["reason"] = f"Diagnosis confidence {diagnosis_res.confidence.value} is too low to justify an estimate."
        elif cf == "SUPPORTED" or ra == "REGIONAL_EVENT":
            verdict["reason"] = "Nearby stations support this reading (counterfactual SUPPORTED / REGIONAL_EVENT): it is not replaced."
        elif not affected:
            verdict["reason"] = "No specific affected channel was identified: nothing is replaced."
        else:
            verdict.update(justified=True, channel=affected[0],
                           basis="independent neighbor consensus (or physical inversion) for the affected channel only",
                           reason="Sensor-side fault diagnosed with at least MEDIUM confidence and no regional support for the reading.")
        return verdict

    def get_station_alert(self, station_id: str) -> Optional[AnomalyAlert]:
        """Returns cached AnomalyAlert for station."""
        return self._alerts_cache.get(station_id)

    def get_station_canonical(self, station_id: str) -> Optional[Dict[str, Any]]:
        """Returns cached Canonical AnalysisResult for station."""
        return self._canonical_cache.get(station_id)

    def compute_spatial_events(
        self, station_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        S4 — Spatial Clustering & Event Fingerprinting (regional batch
        operation; see engine/spatial_clustering.py's module docstring for
        the full architecture rationale).

        Deliberately NOT called from evaluate_reading()/evaluate_station():
        clustering needs to see the CURRENT set of already-anomalous
        stations together, which is a property of the whole pool at a
        point in time, not of any single station's own evaluation. Running
        it inside each station's evaluate() would mean re-clustering the
        same small candidate set once per station in the pool (wasteful,
        and not how the problem is shaped) -- so it is exposed here as an
        explicit, on-demand call instead.

        Uses ONLY already-cached results (self._alerts_cache /
        self._spatial_pool, populated by evaluate_reading() calls that
        already happened) -- this method never re-runs Spatial evaluation
        for any station itself, only reads what was already computed.

        station_ids: restrict to a subset of currently-known stations
        (default: every station with a cached alert). Stations with no
        cached alert, or whose spatial detail shows no applicable channel
        (i.e. no meaningful deviation was found -- see
        engine.spatial_clustering.build_cluster_candidate), are excluded
        from clustering entirely; normal/quiet stations never become
        cluster candidates.
        """
        candidates: List[ClusterCandidate] = []
        ids = station_ids if station_ids is not None else list(self._alerts_cache.keys())

        for sid in ids:
            alert = self._alerts_cache.get(sid)
            reading = self._spatial_pool.get(sid)
            if alert is None or reading is None:
                continue
            spatial_detail = alert.layer_details.get("spatial", {})
            regional_attribution = spatial_detail.get("regional_attribution")
            if not regional_attribution:
                continue
            candidate = build_cluster_candidate(
                station_id=sid,
                latitude=reading.lat,
                longitude=reading.lon,
                regional_attribution=regional_attribution,
                timestamp=alert.timestamp.isoformat() if alert.timestamp else None,
            )
            if candidate is not None:
                candidates.append(candidate)

        result = cluster_anomalous_stations(candidates)
        return result.to_dict()

    def update_spatial_event_tracking(
        self,
        station_ids: Optional[List[str]] = None,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        S5 — Event Evolution (regional batch operation; see
        engine/spatial_event_tracking.py's module docstring for the full
        association/matching/gap-policy rationale).

        Calls compute_spatial_events() (S4) ONCE to get the current
        snapshot, then feeds it into this detector's OWN
        SpatialEventTracker instance. Like compute_spatial_events(),
        deliberately NOT called from evaluate_reading()/evaluate_station()
        -- event tracking is a property of successive REGIONAL snapshots,
        not of any single station's own evaluation.

        timestamp: the observation time this snapshot represents. Defaults
        to now(UTC) only when the caller does not supply one (matching the
        existing codebase's own default-timestamp convention, e.g.
        AWSReading.timestamp) -- tests should always pass an explicit
        timestamp for determinism.
        """
        events_result = self.compute_spatial_events(station_ids=station_ids)
        ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
        return self._spatial_event_tracker.update(events_result, ts)

    def reset_spatial_event_tracking(self) -> None:
        """Clears all S5 tracked event state (fresh event numbering, no
        remembered previous snapshot). Does not affect S1-S4 caches."""
        self._spatial_event_tracker.reset()

    # ─────────────────────────────────────────────────────────────────
    # Private Helpers for §14, §15, §16, §21
    # ─────────────────────────────────────────────────────────────────

    # Fault categories that assert a physical sensor hardware fault. These are
    # meaningless (and dishonest) when the observation did not come from a
    # physical AWS sensor in the first place.
    _HARDWARE_ONLY_FAULTS = {
        FaultType.FROZEN_SENSOR,
        FaultType.SENSOR_SPIKE,
        FaultType.CALIBRATION_DRIFT,
        FaultType.SINGLE_CHANNEL_FAULT,
    }

    def _contextualize_diagnosis_for_source(
        self, diagnosis_res: DiagnosisResult, source: str
    ) -> DiagnosisResult:
        """
        Phase 14/27 guard: ATHER must never claim a physical sensor hardware
        fault (FROZEN_SENSOR, SENSOR_SPIKE, CALIBRATION_DRIFT, etc.) against a
        reading that did not come from a physical AWS sensor. When the source
        is a NWP model reference (or otherwise not AWS_IN_SITU), any
        hardware-fault diagnosis is remapped to MODEL_REFERENCE_INCONSISTENCY
        with corrected evidence and operator guidance.
        """
        # Only remap when the source is AFFIRMATIVELY known to be non-physical
        # (e.g. NWP_MODEL_REFERENCE). An UNKNOWN source (legacy callers,
        # directly-constructed AWSReading in tests) is NOT assumed to be a
        # model reference — that would suppress legitimate hardware-fault
        # diagnoses whenever provenance simply wasn't tagged.
        if source != "NWP_MODEL_REFERENCE" or diagnosis_res.fault_type not in self._HARDWARE_ONLY_FAULTS:
            return diagnosis_res

        note = (
            "This station has no connected AWS in-situ sensor feed — the analyzed "
            "value is a NWP model reference (Open-Meteo), not a physical hardware "
            "measurement. The pattern below describes model-output behavior, not "
            "sensor health."
        )
        # S7: the spatial-corroboration note (appended last) talks about an
        # "isolated sensor anomaly", which must not be claimed for a model
        # reference -- drop it here; spatial_corroboration stays None.
        base_evidence = diagnosis_res.evidence[:-1] if diagnosis_res.spatial_corroboration else diagnosis_res.evidence
        return DiagnosisResult(
            fault_type=FaultType.MODEL_REFERENCE_INCONSISTENCY,
            confidence=diagnosis_res.confidence,
            primary_signal=note,
            evidence=[note] + base_evidence,
            alternatives=diagnosis_res.alternatives + [
                "Model grid-cell artifact or forecast update discontinuity"
            ],
            operator_action=(
                "No physical sensor to inspect. If AWS in-situ telemetry becomes "
                "available for this station, re-run diagnostics against the real feed."
            ),
        )

    def _generate_weather_analysis(
        self,
        reading: AWSReading,
        layer_details: Dict[str, Any],
        status: str
    ) -> Dict[str, Any]:
        """
        Generates genuine meteorological analysis strictly grounded in validated measurements.
        Never outputs generic AI filler. Traceable to actual numbers.
        """
        evidence: List[str] = []
        summary_parts: List[str] = []

        valid_count = reading.valid_channel_count
        if valid_count == 0:
            return {
                "summary": "Insufficient observational data to evaluate current meteorological conditions.",
                "evidence": ["All primary sensor channels (T, P, RH) are missing or offline."]
            }

        # Temperature observation
        if reading.channel_valid("temperature_c") and reading.temperature_c is not None:
            t = reading.temperature_c
            evidence.append(f"Ambient air temperature: {t:.1f}°C")
            if t > 35.0:
                summary_parts.append("Elevated heat conditions")
            elif t < 5.0:
                summary_parts.append("Cold surface temperatures")

        # Pressure observation
        if reading.channel_valid("pressure_hpa") and reading.pressure_hpa is not None:
            p = reading.pressure_hpa
            evidence.append(f"Surface barometric pressure: {p:.1f} hPa")
            if p < 1000.0:
                summary_parts.append("Low-pressure system influence")
            elif p > 1025.0:
                summary_parts.append("High-pressure anticyclonic conditions")

        # Humidity observation
        if reading.channel_valid("humidity_pct") and reading.humidity_pct is not None:
            rh = reading.humidity_pct
            evidence.append(f"Relative humidity: {rh:.1f}%")
            if rh >= 90.0:
                summary_parts.append("Near-saturated atmospheric moisture")
            elif rh <= 20.0:
                summary_parts.append("Arid low-humidity regime")

        # Temporal rate of change evidence
        temporal_detail = layer_details.get("temporal", {})
        if "temp_spike" in temporal_detail:
            ts = temporal_detail["temp_spike"]
            evidence.append(
                f"Rapid temperature shift: {ts['delta_c']:+.1f}°C change in {ts['interval_s']}s "
                f"(previous {ts['previous']:.1f}°C → current {ts['current']:.1f}°C)"
            )
            summary_parts.append("Abrupt thermal transition")

        if "press_spike" in temporal_detail:
            ps = temporal_detail["press_spike"]
            interval_s = ps.get("interval_s", 0)
            delta_hpa = ps.get("delta_hpa", 0.0)
            evidence.append(
                f"Barometric pressure surge: {delta_hpa:+.1f} hPa in {interval_s}s"
            )
            summary_parts.append("Barometric gradient shift")

        # Spatial consistency evidence
        spatial_detail = layer_details.get("spatial", {})
        # S7 BUGFIX: use the keys layer4_spatial.py actually sets
        # (total_neighbors_in_radius, nested distance_range_km,
        # channel_results[ch] with target_value/consensus_value/deviation/
        # usable_neighbors). channel_results[ch] can also be a short
        # status-only dict (target invalid / too few valid neighbors), so
        # the full-evaluation fields are only used when present.
        neighbor_count = spatial_detail.get("total_neighbors_in_radius", 0)
        if neighbor_count >= 2:
            dist_range = spatial_detail.get("distance_range_km") or {}
            dist_min = dist_range.get("min") or 0.0
            dist_max = dist_range.get("max") or 0.0
            deviations = spatial_detail.get("channel_results", {})
            dev = deviations.get("temperature_c") or {}
            if "deviation" in dev and "consensus_value" in dev:
                signed_dev = dev["target_value"] - dev["consensus_value"]
                evidence.append(
                    f"Regional temperature comparison: {signed_dev:+.1f}°C deviation from "
                    f"{dev['usable_neighbors']} neighbors within {dist_min:.0f}–{dist_max:.0f} km "
                    f"(target {dev['target_value']:.1f}°C vs regional consensus {dev['consensus_value']:.1f}°C)"
                )
                if abs(signed_dev) > 5.0:
                    summary_parts.append("Localized thermal discrepancy relative to regional mesh")
                else:
                    summary_parts.append("Consistent with regional temperature field")
        else:
            evidence.append(f"Regional cross-validation limited: only {neighbor_count} nearby station(s) within radius.")

        if not summary_parts:
            summary_parts.append("Stable atmospheric conditions within seasonal expectations")

        summary = ". ".join(summary_parts) + "."
        met_context = "Regional mesoscale analysis based on in-situ AWS station observations."
        if neighbor_count >= 2:
            met_context = f"Mesoscale analysis synthesized from local station and {neighbor_count} neighboring observations."
        
        phenomenon = "Nominal atmospheric regime"
        if "Abrupt thermal transition" in summary_parts:
            phenomenon = "Localized frontal boundary passage or microclimate transition"
        elif "Low-pressure system influence" in summary_parts:
            phenomenon = "Cyclonic or depression trough system"
        elif "Elevated heat conditions" in summary_parts:
            phenomenon = "Diurnal heat peak or local thermal plume"
        elif "Near-saturated atmospheric moisture" in summary_parts:
            phenomenon = "Surface saturation, mist, or active precipitation"
            
        weather_confidence = "HIGH" if valid_count >= 2 and neighbor_count >= 2 else ("MEDIUM" if valid_count >= 1 else "LOW")

        return {
            "summary": summary,
            "meteorological_context": met_context,
            "likely_phenomenon": phenomenon,
            "confidence": weather_confidence,
            "evidence": evidence
        }

    def _generate_insights(
        self,
        reading: AWSReading,
        diagnosis: DiagnosisResult,
        status: str,
        severity: float,
        confidence: float,
        layer_scores: Dict[str, float],
        layer_details: Dict[str, Any],
        explanation: str
    ) -> List[Dict[str, Any]]:
        """
        Generates structured, actionable insights answering:
        WHAT? WHY? EVIDENCE? WHAT SHOULD THE OPERATOR DO?
        Categories: monitor, verify observation, compare with neighboring stations, inspect sensor, continue monitoring, insufficient evidence.
        """
        insights = []

        if status == "NORMAL":
            insights.append({
                "what": "Telemetry operates within certified normal boundaries.",
                "why": "All 5 analytical layers confirm physical, temporal, and spatial coherence.",
                "evidence": f"Physics score: {layer_scores['physics']:.2f}, Temporal: {layer_scores['temporal']:.2f}, Spatial: {layer_scores['spatial']:.2f}.",
                "action": "Continue automated routine monitoring."
            })
            return insights

        # If data is insufficient
        if status == "INSUFFICIENT_DATA" or diagnosis.confidence == DiagnosisConfidence.INSUFFICIENT_DATA:
            insights.append({
                "what": "Telemetry baseline insufficient for conclusive fault diagnosis.",
                "why": diagnosis.primary_signal,
                "evidence": "; ".join(diagnosis.evidence) if diagnosis.evidence else "Limited historical or spatial data points.",
                "action": "Collect additional telemetry frames before initiating hardware intervention."
            })
            return insights

        # Anomaly / Warning case
        action_verb = "Inspect" if diagnosis.confidence == DiagnosisConfidence.HIGH else "Monitor & Verify"
        insights.append({
            "what": f"{diagnosis.confidence.value} confidence detection: {diagnosis.fault_type.value}.",
            "why": diagnosis.primary_signal,
            "evidence": "; ".join(diagnosis.evidence) if diagnosis.evidence else explanation,
            "action": diagnosis.operator_action or f"{action_verb} station telemetry before making operational adjustments."
        })

        # Spatial corroboration insight
        spatial_detail = layer_details.get("spatial", {})
        # S7 BUGFIX: real keys are total_neighbors_in_radius / distance_range_km{min,max}.
        if spatial_detail.get("total_neighbors_in_radius", 0) >= 2:
            _dist_range = spatial_detail.get("distance_range_km") or {}
            insights.append({
                "what": "Regional spatial peer comparison available.",
                "why": f"Cross-referenced against {spatial_detail['total_neighbors_in_radius']} stations.",
                "evidence": f"Consensus comparison range: {(_dist_range.get('min') or 0):.0f}–{(_dist_range.get('max') or 0):.0f} km.",
                "action": "Cross-check station siting and microclimate exposure."
            })

        return insights

    def _generate_data_quality(
        self,
        reading: AWSReading,
        layer_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Builds the provenance and data quality summary block.
        """
        missing = []
        zero_sub = []
        valid = []
        for ch, q in reading.data_quality.items():
            if q == DataQuality.MISSING:
                missing.append(ch)
            elif q == DataQuality.ZERO_SUBSTITUTED:
                zero_sub.append(ch)
            elif q == DataQuality.VALID:
                valid.append(ch)

        temporal_detail = layer_details.get("temporal", {})
        spatial_detail = layer_details.get("spatial", {})

        history_pts = temporal_detail.get("history_points", 0)
        neighbors = spatial_detail.get("total_neighbors_in_radius", 0)  # S7 BUGFIX: real key name

        limitations = []
        if zero_sub:
            limitations.append(f"Fields with 0.0 treated as missing (not genuine zero): {', '.join(zero_sub)}")
        if missing:
            limitations.append(f"Missing channels: {', '.join(missing)}")
        if history_pts < 3:
            limitations.append(f"Limited historical sequence ({history_pts} points); temporal rate-of-change check restricted")
        if neighbors < 2:
            limitations.append(f"Sparse regional coverage ({neighbors} neighbors within radius); spatial consensus check limited")

        dq_status = (
            "VALID" if len(valid) == 3 and not limitations else
            "DEGRADED" if len(valid) >= 1 else
            "INSUFFICIENT_DATA"
        )

        return {
            "status": dq_status,
            "valid_fields": valid,
            "missing_fields": missing,
            "zero_substituted_fields": zero_sub,
            "historical_points": history_pts,
            "nearby_stations": neighbors,
            "limitations": limitations
        }

    @staticmethod
    def _compact_regional_attribution(spatial_detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ra = spatial_detail.get("regional_attribution")
        if not ra:
            return None
        return {
            "classification": ra.get("classification"),
            "evidence_strength": ra.get("confidence"),
            "applicable_channels": ra.get("applicable_channels", []),
            "explanation": ra.get("explanation"),
        }

    @staticmethod
    def _compact_counterfactual(spatial_detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cv = spatial_detail.get("counterfactual_verification")
        if not cv:
            return None
        return {
            "overall_status": cv.get("overall_status"),
            "channel_status": {ch: v.get("status") for ch, v in cv.get("channels", {}).items()},
            "summary": cv.get("summary"),
        }

    def _format_canonical_layers(
        self,
        layer_scores: Dict[str, float],
        layer_details: Dict[str, Any],
        veto_fired: bool,
        reason_l1: Optional[str],
        reason_l2: Optional[str],
        reason_l3: Optional[str],
        reason_l4: Optional[str],
        reason_l5: Optional[str],
        health_score: float,
        is_physical_sensor: bool = True,
    ) -> Dict[str, Any]:
        """
        Formats the 5 layer diagnostic cards according to §21:
        LAYER NAME, STATUS, SCORE, CONFIDENCE / EVIDENCE QUALITY, ONE-LINE REASON.
        """
        d1 = layer_details.get("physics", {})
        d2 = layer_details.get("temporal", {})
        d3 = layer_details.get("multivariate", {})
        d4 = layer_details.get("spatial", {})
        d5 = layer_details.get("drift", {})

        # 1. Physics
        ch_eval1 = d1.get("channels_evaluated", [])
        if not ch_eval1:
            l1_status = "LIMITED"
            l1_conf = "INSUFFICIENT_DATA"
            l1_reason = "No valid channels available for physical limit verification"
        elif veto_fired:
            l1_status = "VETO"
            l1_conf = "HIGH"
            l1_reason = reason_l1 or "Real telemetry violates fundamental thermodynamic constraints"
        elif layer_scores["physics"] >= 0.70:
            l1_status = "WARNING"
            l1_conf = "HIGH"
            l1_reason = reason_l1 or "Physical boundary proximity detected"
        else:
            l1_status = "PASS"
            l1_conf = "HIGH"
            l1_reason = "All observed parameters fall within thermodynamic terrestrial envelopes"

        # 2. Temporal
        # BUGFIX: layer2_temporal.py stores per-channel counts under
        # "historical_points" (plural, nested dict) — not the scalar
        # "history_points" this used to look up, which always defaulted to 0
        # and forced this card to show INSUFFICIENT_DATA / "0 samples" even
        # when real temporal history existed and was actively used above.
        h_pts = max(d2.get("historical_points", {}).values(), default=0)
        if h_pts < 3 or d2.get("status") == "INSUFFICIENT_DATA":
            l2_status = "INSUFFICIENT_DATA"
            l2_conf = "INSUFFICIENT_DATA"
            l2_reason = f"Insufficient temporal history ({h_pts} samples recorded, 3 required)"
        elif layer_scores["temporal"] >= 0.70:
            l2_status = "ANOMALY"
            l2_conf = "HIGH" if h_pts >= 6 else "MEDIUM"
            l2_reason = reason_l2 or "Step-rate or frozen value anomaly detected"
        elif layer_scores["temporal"] >= 0.40:
            l2_status = "WARNING"
            l2_conf = "MEDIUM"
            l2_reason = reason_l2 or "Elevated rate of change observed"
        else:
            l2_status = "PASS"
            l2_conf = "HIGH"
            l2_reason = "Time-series variance and rate of change within nominal thresholds"

        # 3. Multivariate
        # The layer reports the validated channel count as BOTH "n_valid" and
        # "valid_channel_count" (the card previously read a key that was never
        # set, so it always saw 0). Never report "0 available" when channels are valid.
        v_cnt = d3.get("n_valid", d3.get("valid_channel_count", 0))
        if v_cnt < 2 or d3.get("status") == "INSUFFICIENT_DATA":
            l3_status = "INSUFFICIENT_DATA"
            l3_conf = "INSUFFICIENT_DATA"
            if v_cnt < 2:
                l3_reason = f"Multivariate analysis requires ≥2 valid channels ({v_cnt} available)"
            else:
                # Enough valid channels, but the models could not run (e.g. the pressure
                # convention is unknown): state the layer's own reason instead.
                l3_reason = d3.get("skip_reason") or d3.get("note") or "Multivariate evidence unavailable"
        elif layer_scores["multivariate"] >= 0.75:
            l3_status = "ANOMALY"
            l3_conf = "HIGH" if v_cnt == 3 else "MEDIUM"
            l3_reason = reason_l3 or "Unfeasible joint atmospheric state distribution"
        elif layer_scores["multivariate"] >= 0.50:
            l3_status = "WARNING"
            l3_conf = "MEDIUM"
            l3_reason = reason_l3 or "Moderate joint-channel divergence"
        else:
            l3_status = "PASS"
            l3_conf = "HIGH"
            # Name the method that ACTUALLY executed (layer3 detail["method_executed"]).
            l3_reason = f"Joint state manifold ({d3.get('method_executed') or d3.get('method') or 'bivariate'}) consistent"

        # 4. Spatial
        # S7 BUGFIX: real key is total_neighbors_in_radius; layer4 also reports
        # its own insufficiency status as "INSUFFICIENT_NEIGHBORS" (not the
        # "INSUFFICIENT_DATA" string this card originally checked), so both
        # are honored.
        n_cnt = d4.get("total_neighbors_in_radius", 0)
        if n_cnt < 2 or d4.get("status") in ("INSUFFICIENT_DATA", "INSUFFICIENT_NEIGHBORS"):
            l4_status = "INSUFFICIENT_DATA"
            l4_conf = "INSUFFICIENT_DATA"
            l4_reason = d4.get("note") or f"Insufficient neighboring stations within radius ({n_cnt} found, 2 required)"
        elif layer_scores["spatial"] >= 0.70:
            l4_status = "ANOMALY"
            l4_conf = "HIGH" if n_cnt >= 4 else "MEDIUM"
            l4_reason = reason_l4 or "Severe divergence from regional consensus"
        elif layer_scores["spatial"] >= 0.45:
            l4_status = "WARNING"
            l4_conf = "MEDIUM"
            l4_reason = reason_l4 or "Marginal divergence from regional cluster"
        else:
            l4_status = "PASS"
            l4_conf = "HIGH" if n_cnt >= 4 else "MEDIUM"
            l4_reason = f"Consistent with {n_cnt} regional stations"

        # 5. Sensor Health / Drift
        # This layer diagnoses PHYSICAL sensor hardware reliability. It is not
        # applicable to a NWP model reference — there is no hardware to assess.
        if not is_physical_sensor:
            l5_status = "NOT_APPLICABLE"
            l5_conf = "INSUFFICIENT_DATA"
            l5_reason = "Not applicable: this station has no connected AWS in-situ sensor; value is a NWP model reference."
        else:
            # BUGFIX: layer5_drift.py never sets a top-level "samples_tracked"
            # key (per-channel counts live under detail["channel_drift"][ch]
            # ["samples_tracked"]) — this always defaulted to 0, forcing the
            # card to show "Drift monitoring initializing" indefinitely.
            # detail["samples_in_radius"] is actually total readings processed
            # for this station (a misleading name, but the right scalar here).
            s_cnt = d5.get("samples_in_radius", 0)
            if s_cnt < 5:
                l5_status = "INSUFFICIENT_DATA"
                l5_conf = "INSUFFICIENT_DATA"
                l5_reason = f"Drift monitoring initializing ({s_cnt} samples tracked)"
            elif layer_scores["drift"] >= 0.70:
                l5_status = "ANOMALY"
                l5_conf = "HIGH" if s_cnt >= 20 else "MEDIUM"
                l5_reason = reason_l5 or "Progressive sensor calibration drift detected"
            elif layer_scores["drift"] >= 0.40:
                l5_status = "WARNING"
                l5_conf = "MEDIUM"
                l5_reason = reason_l5 or "Minor cumulative calibration bias accumulating"
            else:
                l5_status = "PASS"
                l5_conf = "HIGH"
                l5_reason = f"Sensor health index nominal ({health_score:.0f}%)"

        cards = {
            "physics": {
                "name": "Physics Validation",
                "status": l1_status,
                "score": layer_scores["physics"],
                "evidence_quality": l1_conf,
                "reason": l1_reason,
                "details": d1,
            },
            "temporal": {
                "name": "Temporal Pattern",
                "status": l2_status,
                "score": layer_scores["temporal"],
                "evidence_quality": l2_conf,
                "reason": l2_reason,
                "details": d2,
            },
            "multivariate": {
                "name": "Multivariate Consistency",
                "status": l3_status,
                "score": layer_scores["multivariate"],
                "evidence_quality": l3_conf,
                "reason": l3_reason,
                "details": d3,
            },
            "spatial": {
                "name": "Spatial Consensus",
                "status": l4_status,
                "score": layer_scores["spatial"],
                "evidence_quality": l4_conf,
                "reason": l4_reason,
                "details": d4,
                # S7: compact, dashboard-ready views of the S3/S6 evidence
                # (full detail remains in "details"). These are evidence
                # states, not calibrated probabilities. None when spatial
                # evidence is unavailable -- never fabricated.
                "regional_attribution": self._compact_regional_attribution(d4),
                "counterfactual_verification": self._compact_counterfactual(d4),
            },
            "sensor_health": {
                "name": "Sensor Health & Drift",
                "status": l5_status,
                "score": layer_scores["drift"],
                "evidence_quality": l5_conf,
                "reason": l5_reason,
                "details": d5,
            },
        }
        # S7: a layer that raised is reported as UNAVAILABLE (missing
        # evidence), never as PASS/ANOMALY.
        for card in cards.values():
            if (card.get("details") or {}).get("layer_unavailable"):
                card["status"] = "UNAVAILABLE"
                card["evidence_quality"] = "INSUFFICIENT_DATA"
                card["reason"] = "Layer unavailable for this evaluation; its evidence is excluded, not assumed normal."
        return cards


# Singleton detector instance
detector = AnomalyDetector()
