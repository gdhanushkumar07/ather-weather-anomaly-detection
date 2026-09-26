"""
S3 — Regional Event Attribution.

Answers, per station evaluation: given that a channel shows a meaningful
deviation from its robust regional baseline (S2), is that deviation more
consistent with (a) an ISOLATED_SENSOR_ANOMALY, (b) a coherent
REGIONAL_EVENT, or (c) UNCERTAIN (evidence insufficient or contradictory)?

This module computes evidence ONLY. It does not replace, duplicate, or
re-derive anything S1 (neighbor selection) or S2 (IDW / median / MAD /
robust_z) already computed -- every function here takes those results as
direct inputs (estimates, weights, regional_median, regional_mad,
robust_z, min_std, usable_neighbors) and adds one more layer of reasoning
on top: does the NEIGHBOR POPULATION, taken individually, corroborate the
target's own deviation?

WHY COMPARING EACH NEIGHBOR AGAINST THE SAME regional_median/regional_mad
IS NOT CIRCULAR (important, non-obvious design justification):

The median is "breakdown robust" up to ~50% contamination: as long as the
stations sharing the target's deviation are a MINORITY of the neighbor
pool, the median stays anchored near the unaffected majority. This is
exactly the case where the target is flagged in the first place --
because if the deviating stations were the MAJORITY, the median would
already have shifted toward them, and the target's robust_z would be
small (NOT flagged), by design (S2). So: whenever this module's evidence
actually matters (target_flagged=True), regional_median/regional_mad are,
by construction, dominated by the UNAFFECTED subset of neighbors -- which
means checking whether OTHER neighbors also deviate from that SAME,
still-mostly-unaffected baseline is a genuine, non-circular corroboration
signal, not a self-referential one. A single-instant Spatial evaluation
has no independent "what these stations used to read" baseline to compare
against (that is Temporal's job) -- this median-derived baseline is the
only one available to Spatial, and it degrades gracefully rather than
lying: if a TRUE majority of neighbors share the deviation, the target
simply will not be flagged at all, and this module reports
`applicable=False` for that channel rather than fabricating attribution
evidence Spatial cannot actually support from a single snapshot.

This module explicitly does NOT implement DBSCAN/HDBSCAN clustering,
event fingerprinting, event evolution, or counterfactual verification
(S4/S5/S6) -- it only reasons about the CURRENTLY OBSERVED neighbor
evidence for the CURRENT evaluation, exactly as S3 is scoped to do.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from engine.spatial_statistics import compute_robust_z

# ── Centralized, documented S3 constants (no unexplained magic numbers) ──

# A neighbor's OWN robust z-score must clear this bar to count as showing
# "a real deviation" (support or disagreement) rather than noise. 1.0 is
# one channel-appropriate noise-floor unit -- the SAME unit min_std/z-scores
# already use throughout this layer (a z of 1.0 means "one min_std-sized
# step away from the median"), not a new, unrelated scale.
MIN_MEANINGFUL_NEIGHBOR_Z = 1.0

# Tolerant multiplicative band for "reasonably similar magnitude" (task
# requirement: do NOT require exact equality). Symmetric in ratio-space
# (log(3) ~= -log(1/3)), so "half as strong" and "twice as strong" are
# treated with equal tolerance -- the simplest non-arbitrary symmetric band.
MAGNITUDE_CONSISTENCY_LOW_RATIO = 1.0 / 3.0
MAGNITUDE_CONSISTENCY_HIGH_RATIO = 3.0

# Fixed, deterministic channel order used everywhere in this module's
# aggregation/explanation output (never dict-iteration order).
CHANNEL_ORDER: Tuple[str, ...] = ("temperature_c", "pressure_hpa", "humidity_pct")

CHANNEL_LABELS: Dict[str, str] = {
    "temperature_c": "temperature",
    "pressure_hpa": "pressure",
    "humidity_pct": "humidity",
}


def _direction(z: float) -> int:
    """Sign of a z-score: -1, 0, or +1. 0 only for an exact-zero deviation."""
    if z > 0:
        return 1
    if z < 0:
        return -1
    return 0


@dataclass(frozen=True)
class ChannelAttributionEvidence:
    """Per-channel S3 evidence. See module docstring for the reasoning
    behind each field. `applicable=False` means this channel showed no
    meaningful deviation (same `flagged` gate S2/existing scoring already
    uses) -- there is nothing to attribute, and every other field is a
    zero/neutral placeholder rather than fabricated evidence."""
    channel: str
    applicable: bool
    target_value: Optional[float]
    target_robust_z: Optional[float]
    target_direction: int
    usable_neighbors: int
    spatial_coverage: float
    neighbor_support_count: int
    neighbor_disagreement_count: int
    neighbor_neutral_count: int
    neighbor_support_ratio: float
    neighbor_disagreement_ratio: float
    distance_weighted_support: float
    # S6 addition (Counterfactual Verification): the symmetric counterpart
    # to distance_weighted_support -- the fraction of TOTAL neighbor IDW
    # weight held by neighbors whose own robust_z opposes the target's
    # direction (the same "disagree" branch neighbor_disagreement_count
    # already counts, just distance-weighted instead of a plain count).
    # Purely additive: computed in the SAME existing loop below at zero
    # extra cost, does not change any existing field's value or meaning.
    distance_weighted_contradiction: float
    magnitude_consistency: Optional[float]
    regional_event_evidence_strength: float
    isolated_sensor_evidence_strength: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "applicable": self.applicable,
            "target_value": self.target_value,
            "target_robust_z": round(self.target_robust_z, 3) if self.target_robust_z is not None else None,
            "target_direction": self.target_direction,
            "usable_neighbors": self.usable_neighbors,
            "spatial_coverage": round(self.spatial_coverage, 3),
            "regional_event_evidence": {
                "neighbor_support_count": self.neighbor_support_count,
                "neighbor_support_ratio": round(self.neighbor_support_ratio, 3),
                "directional_agreement": self.neighbor_support_count > 0,
                "magnitude_consistency": (
                    round(self.magnitude_consistency, 3) if self.magnitude_consistency is not None else None
                ),
                "distance_weighted_support": round(self.distance_weighted_support, 3),
                "evidence_strength": round(self.regional_event_evidence_strength, 3),
            },
            "isolated_sensor_evidence": {
                "neighbor_disagreement_count": self.neighbor_disagreement_count,
                "neighbor_disagreement_ratio": round(self.neighbor_disagreement_ratio, 3),
                "directional_disagreement": self.neighbor_disagreement_count > 0,
                "distance_weighted_contradiction": round(self.distance_weighted_contradiction, 3),
                "evidence_strength": round(self.isolated_sensor_evidence_strength, 3),
            },
        }


def compute_channel_attribution_evidence(
    channel: str,
    target_value: float,
    target_flagged: bool,
    target_robust_z: float,
    regional_median: float,
    regional_mad: float,
    neighbor_estimates: Sequence[float],
    neighbor_weights: Sequence[float],
    min_std: float,
    spatial_k_neighbors: int,
) -> ChannelAttributionEvidence:
    """
    Builds one channel's S3 evidence from ALREADY-COMPUTED S1/S2 results.

    `target_flagged` is the "is there anything to attribute at all" gate.
    It is computed by the caller as `abs(robust_z) > spatial_z_threshold`
    -- the SAME existing spatial_z_threshold value, but applied to the
    ROBUST z-score rather than the existing IDW-based `flagged`. This is
    deliberate: idw_z's plain standard deviation can itself be inflated by
    the very outlier/minority-cluster population S3 needs to reason about,
    which can suppress idw_z below threshold precisely in the scenario S3
    cares most about (several neighbors sharing the target's deviation).
    robust_z is exactly the statistic S2 built to resist that distortion.
    `neighbor_estimates`/`neighbor_weights` are the SAME DataQuality-filtered,
    elevation-lapse-adjusted lists S2's IDW/robust computation already used
    (index-aligned) -- nothing is recomputed or re-filtered here.
    """
    usable = len(neighbor_estimates)

    if not target_flagged:
        return ChannelAttributionEvidence(
            channel=channel, applicable=False, target_value=target_value,
            target_robust_z=target_robust_z, target_direction=0,
            usable_neighbors=usable, spatial_coverage=0.0,
            neighbor_support_count=0, neighbor_disagreement_count=0, neighbor_neutral_count=usable,
            neighbor_support_ratio=0.0, neighbor_disagreement_ratio=0.0,
            distance_weighted_support=0.0, distance_weighted_contradiction=0.0, magnitude_consistency=None,
            regional_event_evidence_strength=0.0, isolated_sensor_evidence_strength=0.0,
        )

    target_direction = _direction(target_robust_z)
    target_abs_z = abs(target_robust_z)

    # spatial_coverage: reuses the EXISTING spatial_k_neighbors config value
    # as the "full coverage" denominator -- not a new constant. At the
    # system's own configured minimum (min_neighbors_required), this is
    # already a small fraction, naturally damping confidence for
    # minimum-neighbor cases (task's CASE 3) without a separate rule.
    spatial_coverage = min(1.0, usable / spatial_k_neighbors) if spatial_k_neighbors > 0 else 0.0

    total_weight = sum(neighbor_weights) or 1.0  # neighbor_weights are always > 0 by construction (IDW weights)
    support_count = 0
    disagree_count = 0
    support_weight = 0.0
    disagree_weight = 0.0  # S6 addition: symmetric accumulator, same loop, zero extra passes
    supporting_abs_zs: List[float] = []

    for val, w in zip(neighbor_estimates, neighbor_weights):
        n_z, _ = compute_robust_z(val, regional_median, regional_mad, min_scale=min_std)
        n_dir = _direction(n_z)
        n_abs_z = abs(n_z)
        if n_abs_z < MIN_MEANINGFUL_NEIGHBOR_Z:
            continue  # neutral: too close to the regional baseline to count either way
        if n_dir == target_direction:
            support_count += 1
            support_weight += w
            supporting_abs_zs.append(n_abs_z)
        elif n_dir == -target_direction:
            disagree_count += 1
            disagree_weight += w

    neutral_count = usable - support_count - disagree_count
    support_ratio = support_count / usable if usable else 0.0
    disagreement_ratio = disagree_count / usable if usable else 0.0
    distance_weighted_support = support_weight / total_weight
    distance_weighted_contradiction = disagree_weight / total_weight

    magnitude_consistency: Optional[float]
    if supporting_abs_zs:
        lo = target_abs_z * MAGNITUDE_CONSISTENCY_LOW_RATIO
        hi = target_abs_z * MAGNITUDE_CONSISTENCY_HIGH_RATIO
        consistent = sum(1 for z in supporting_abs_zs if lo <= z <= hi)
        magnitude_consistency = consistent / len(supporting_abs_zs)
    else:
        magnitude_consistency = None  # no supporting neighbors -- nothing to compare magnitude against

    magnitude_consistency_effective = magnitude_consistency if magnitude_consistency is not None else 0.0

    # Regional-event evidence: an AND-like product of three INDEPENDENT
    # necessary conditions (enough neighbors overall, a distance-weighted
    # majority of them supporting, and consistent magnitude) -- conservative
    # by design: any one missing condition collapses the score toward 0
    # rather than letting a strong factor compensate for an absent one.
    # neighbor_support_ratio/neighbor_support_count are reported separately
    # for explainability but deliberately NOT multiplied in again here,
    # since distance_weighted_support already captures the same underlying
    # "how much support" signal (plus distance), avoiding double-counting.
    regional_strength = spatial_coverage * distance_weighted_support * magnitude_consistency_effective

    # Isolated-sensor evidence: high when coverage is adequate AND the
    # neighbor population does NOT support the target's direction --
    # "not supporting" includes both active disagreement and neutral
    # (quiet/normal) neighbors, which is exactly the textbook isolated-
    # fault signature (task CASE 1: target extreme, neighbors normal).
    isolated_strength = spatial_coverage * (1.0 - support_ratio)

    return ChannelAttributionEvidence(
        channel=channel, applicable=True, target_value=target_value,
        target_robust_z=target_robust_z, target_direction=target_direction,
        usable_neighbors=usable, spatial_coverage=spatial_coverage,
        neighbor_support_count=support_count, neighbor_disagreement_count=disagree_count,
        neighbor_neutral_count=neutral_count,
        neighbor_support_ratio=support_ratio, neighbor_disagreement_ratio=disagreement_ratio,
        distance_weighted_support=distance_weighted_support,
        distance_weighted_contradiction=distance_weighted_contradiction,
        magnitude_consistency=magnitude_consistency,
        regional_event_evidence_strength=regional_strength,
        isolated_sensor_evidence_strength=isolated_strength,
    )


@dataclass(frozen=True)
class RegionalAttribution:
    classification: str  # "REGIONAL_EVENT" | "ISOLATED_SENSOR_ANOMALY" | "UNCERTAIN"
    confidence: float
    applicable_channels: Tuple[str, ...]
    regional_event_evidence_strength: float
    isolated_sensor_evidence_strength: float
    explanation: str

    def to_dict(self, channel_evidence: Dict[str, ChannelAttributionEvidence]) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            # `confidence` is an EVIDENCE-STRENGTH score in [0,1], derived
            # deterministically from spatial coverage / neighbor agreement /
            # magnitude consistency -- it is NOT a calibrated statistical
            # probability and must not be presented as one.
            "confidence": round(self.confidence, 3),
            "confidence_note": "Evidence-strength score in [0,1], not a calibrated probability.",
            "applicable_channels": list(self.applicable_channels),
            "regional_event_evidence_strength": round(self.regional_event_evidence_strength, 3),
            "isolated_sensor_evidence_strength": round(self.isolated_sensor_evidence_strength, 3),
            "explanation": self.explanation,
            "channel_evidence": {
                ch: channel_evidence[ch].to_dict() for ch in CHANNEL_ORDER if ch in channel_evidence
            },
            "method": (
                "Deterministic evidence combination over S1 (deterministic KNN) "
                "+ S2 (IDW / median / MAD / robust_z) outputs. No clustering, "
                "no ML model, no counterfactual reasoning (deferred to S4-S6)."
            ),
        }


def _lean(evidence: ChannelAttributionEvidence) -> Optional[str]:
    """Which hypothesis a single channel's evidence favors, or None if tied
    (extremely rare with continuous floats) or not applicable."""
    if not evidence.applicable:
        return None
    if evidence.regional_event_evidence_strength > evidence.isolated_sensor_evidence_strength:
        return "REGIONAL_EVENT"
    if evidence.isolated_sensor_evidence_strength > evidence.regional_event_evidence_strength:
        return "ISOLATED_SENSOR_ANOMALY"
    return None


def aggregate_regional_attribution(
    channel_evidence: Dict[str, ChannelAttributionEvidence],
    *,
    min_neighbors_required: int,
    spatial_k_neighbors: int,
) -> RegionalAttribution:
    """
    Combines per-channel evidence into one overall classification.

    Rules (in order):
      1. No applicable channel (nothing deviated anywhere) -> UNCERTAIN,
         confidence 0.0. There is nothing to attribute.
      2. Applicable channels point in OPPOSITE directions (at least one
         leans REGIONAL_EVENT and at least one leans ISOLATED_SENSOR_ANOMALY)
         -> UNCERTAIN. The system must not force a decision when channels
         genuinely disagree (task's explicit requirement).
      3. Otherwise, average each hypothesis's evidence_strength across
         applicable channels. If the stronger of the two averages does not
         clear MIN_EVIDENCE_STRENGTH (derived from this system's OWN
         configured minimum-neighbor bar with perfect agreement --
         min_neighbors_required / spatial_k_neighbors -- not an invented
         number) -> UNCERTAIN. Otherwise, classify as whichever hypothesis's
         average is larger, with that average as confidence.
    """
    applicable = [ch for ch in CHANNEL_ORDER if ch in channel_evidence and channel_evidence[ch].applicable]

    if not applicable:
        return RegionalAttribution(
            classification="UNCERTAIN", confidence=0.0, applicable_channels=(),
            regional_event_evidence_strength=0.0, isolated_sensor_evidence_strength=0.0,
            explanation="No channel shows a meaningful deviation from its robust regional baseline; nothing to attribute.",
        )

    leans = {ch: _lean(channel_evidence[ch]) for ch in applicable}
    leaning_regional = [ch for ch in applicable if leans[ch] == "REGIONAL_EVENT"]
    leaning_isolated = [ch for ch in applicable if leans[ch] == "ISOLATED_SENSOR_ANOMALY"]

    regional_strengths = [channel_evidence[ch].regional_event_evidence_strength for ch in applicable]
    isolated_strengths = [channel_evidence[ch].isolated_sensor_evidence_strength for ch in applicable]
    mean_regional = sum(regional_strengths) / len(regional_strengths)
    mean_isolated = sum(isolated_strengths) / len(isolated_strengths)

    if leaning_regional and leaning_isolated:
        reg_labels = ", ".join(CHANNEL_LABELS[c] for c in leaning_regional)
        iso_labels = ", ".join(CHANNEL_LABELS[c] for c in leaning_isolated)
        return RegionalAttribution(
            classification="UNCERTAIN",
            confidence=min(mean_regional, mean_isolated),
            applicable_channels=tuple(applicable),
            regional_event_evidence_strength=mean_regional,
            isolated_sensor_evidence_strength=mean_isolated,
            explanation=(
                f"Channels disagree: {reg_labels} lean(s) toward a regional event while "
                f"{iso_labels} lean(s) toward an isolated sensor anomaly -- evidence is "
                f"contradictory, so no single classification is forced."
            ),
        )

    # Derived, not invented: the evidence_strength attainable at this
    # system's own configured minimum-neighbor bar with perfect agreement.
    # The comparison below is "<=" (not "<") deliberately: evidence that
    # only just REACHES the bare-minimum-coverage ceiling is exactly the
    # "weak/insufficient neighborhood" case (task CASE 3) and should stay
    # UNCERTAIN -- a classification should require STRICTLY more evidence
    # than the system's own floor, not merely tie it.
    min_evidence_strength = (
        min_neighbors_required / spatial_k_neighbors if spatial_k_neighbors > 0 else 1.0
    )

    strongest = max(mean_regional, mean_isolated)
    if strongest <= min_evidence_strength:
        return RegionalAttribution(
            classification="UNCERTAIN",
            confidence=strongest,
            applicable_channels=tuple(applicable),
            regional_event_evidence_strength=mean_regional,
            isolated_sensor_evidence_strength=mean_isolated,
            explanation=(
                f"Evidence strength ({strongest:.2f}) does not clear the minimum-coverage bar "
                f"({min_evidence_strength:.2f}) derived from this system's own configured "
                f"minimum neighbor count -- too little spatial evidence to prefer either hypothesis."
            ),
        )

    ch_labels = ", ".join(CHANNEL_LABELS[c] for c in applicable)
    if mean_regional > mean_isolated:
        return RegionalAttribution(
            classification="REGIONAL_EVENT", confidence=mean_regional,
            applicable_channels=tuple(applicable),
            regional_event_evidence_strength=mean_regional, isolated_sensor_evidence_strength=mean_isolated,
            explanation=(
                f"{ch_labels} show coherent, distance-weighted, magnitude-consistent deviation "
                f"across multiple neighbors -- consistent with a regional weather event."
            ),
        )
    else:
        return RegionalAttribution(
            classification="ISOLATED_SENSOR_ANOMALY", confidence=mean_isolated,
            applicable_channels=tuple(applicable),
            regional_event_evidence_strength=mean_regional, isolated_sensor_evidence_strength=mean_isolated,
            explanation=(
                f"{ch_labels} deviate(s) from the regional baseline while nearby stations remain "
                f"near-normal -- consistent with an isolated sensor anomaly."
            ),
        )
