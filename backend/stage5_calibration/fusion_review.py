"""
Phase 8: Evidence Fusion inspection — documents ACTUAL observed behavior
from reading fusion/conformal_fusion.py and app/anomaly/detector.py.
This is a static findings record, not a computation — no fusion code is
modified or exercised beyond what Phase 9's scenarios already do.
"""
from typing import Any, Dict


def fusion_architecture_findings() -> Dict[str, Any]:
    return {
        "score_ranges_per_layer": "All 5 layer scores (physics, temporal, multivariate, spatial, drift) are "
                                   "documented and enforced as float [0, 1] at their own layer boundary; "
                                   "conformal_fusion.py assumes this range without re-normalizing.",
        "layer_weights": {"physics": 0.35, "temporal": 0.25, "multivariate": 0.20, "spatial": 0.15, "drift": 0.05},
        "temporal_weight": 0.25,
        "normalization_mechanism": "compute_nonconformity_score() is a WEIGHTED AVERAGE of the 5 layer scores "
                                    "(weights above), normalized by sum of weights actually present. No further "
                                    "rescaling/normalization is applied to layer_scores themselves.",
        "acute_trigger_mechanism": "fuse() ALSO checks 'acute' per-layer overrides independent of the weighted "
                                    "average: acute_temporal = temporal_score >= 0.70 (also acute_physics>=0.75, "
                                    "acute_spatial>=0.70, acute_multi>=0.80, acute_drift>=0.75). If ANY acute "
                                    "trigger fires, is_anomaly=True regardless of the weighted nonconformity score. "
                                    "THIS is why Phase 3's finding (20.2% of normal traffic exceeded 0.70 BEFORE "
                                    "the Stage 5 calibration fix) was operationally severe, not just cosmetically "
                                    "noisy: it would have tripped this acute override on ~1 in 5 normal readings.",
        "confidence_calculation": "confidence starts from max(peak_score, 1-p_value), then is CAPPED by "
                                   "meaningful_layer_count (single-layer evidence capped at 0.65), scaled by "
                                   "coverage_ratio and agreement_factor. It does NOT sum/multiply independent "
                                   "layer confidences — it is evidence-quality-aware, not naive-Bayes-independent.",
        "severity_calculation": "severity = 0.6*peak_score + 0.4*nonconformity_score (a blend of the single "
                                  "worst layer and the overall weighted average) — NOT a simple average, so one "
                                  "very strong layer can dominate severity even if others are quiet.",
        "layer_independence_assumption": "The weighted-average nonconformity score implicitly treats the 5 "
                                          "layers as independent evidence sources (a standard weighted-ensemble "
                                          "assumption) — there is no explicit correlation/covariance modeling "
                                          "between layers anywhere in conformal_fusion.py.",
        "double_counting_analysis": {
            "finding": "Fusion receives EXACTLY ONE 'temporal' key in layer_scores (assembled in "
                       "app/anomaly/detector.py: layer_scores={'temporal': round(float(score_l2), 3), ...}). "
                       "score_l2 is the SINGLE value returned by TemporalPatternLayer.evaluate() — which "
                       "ALREADY merges rule-based and LSTM evidence internally via max() BEFORE returning. "
                       "There is no separate 'lstm' key, no second weight, and fusion has no way to know the "
                       "LSTM contributed at all. Structurally, fusion CANNOT double-count rule vs LSTM temporal "
                       "evidence, because it never sees them as two things — this was already true by Stage 4's "
                       "original design and required no Stage 5 change.",
            "conclusion": "No double-counting exists or was introduced. Architecture matches spec section 15 "
                          "exactly: Temporal Rules + LSTM -> ONE bounded temporal score -> Evidence Fusion.",
        },
        "root_cause_consumption": "root_cause/classifier.py reads layer_scores.get('temporal', 0.0) as a single "
                                    "scalar (e.g. 'GENUINE_EXTREME_WEATHER: temporal_score > 0.60 and spatial_score "
                                    "< 0.30') — again only ever sees the one merged value, never rule/LSTM "
                                    "separately.",
        "pre_existing_unrelated_issue_observed": (
            "app/anomaly/detector.py computes layer_coverage['temporal'] using "
            "detail_l2.get('history_points', 0) — but layer2_temporal.py actually stores this under "
            "detail['historical_points'] (plural, nested per-channel dict), not the scalar 'history_points' "
            "this reads. The .get() default (0) is always returned, so layer_coverage['temporal'] is ALWAYS "
            "0.2, regardless of how much real history exists. This is a PRE-EXISTING bug (present before Stage "
            "4/5, same class of bug already flagged with a 'BUGFIX' comment elsewhere in the same file for a "
            "different lookup) — NOT introduced by Stage 1-5, and NOT fixed here: fixing it means editing "
            "app/anomaly/detector.py's fusion-adjacent coverage logic, which is out of Temporal Intelligence's "
            "ownership boundary per this project's team-integration plan. Reported for whoever owns "
            "Evidence Fusion / detector.py to evaluate."
        ),
        "fusion_modification_made": False,
        "fusion_modification_reason": "Not needed — the double-counting concern was already structurally "
                                        "prevented by Stage 4's design (single merged temporal score). The "
                                        "actual Stage 5 problem (excessive normal-traffic scores) was fixed "
                                        "entirely inside Temporal Intelligence (engine/lstm_temporal.py's "
                                        "calibration factor) without touching fusion/conformal_fusion.py at all.",
    }
