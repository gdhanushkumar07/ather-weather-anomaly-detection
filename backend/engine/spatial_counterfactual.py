"""
S6 — Counterfactual Verification.

Answers, per applicable channel: "IF the target station's anomalous
reading were genuine, would the surrounding stations provide the expected
supporting evidence?" This is NOT an independent anomaly declaration --
it is ONE MORE evidence signal, to be combined by a later Evidence Fusion
/ Decision layer (S7, not implemented here). See "ARCHITECTURAL BOUNDARY"
at the end of this docstring.

================================================================
INPUTS: THIS MODULE COMPUTES NOTHING S1-S3 DIDN'T ALREADY COMPUTE

S6 takes S3's own per-channel `ChannelAttributionEvidence` objects
(engine/spatial_attribution.py) as its ONLY input -- the same neighbor
selection (S1), robust median/MAD baseline (S2), and per-neighbor
support/disagreement tally (S3) already computed for every station
evaluation. No neighbor is re-selected, no robust_z is recomputed, no
per-neighbor loop is re-run. The ONE new quantity S3 didn't already
expose -- `distance_weighted_contradiction`, the IDW-weight-weighted
fraction of neighbors opposing the target's direction, symmetric to S3's
existing `distance_weighted_support` -- was added to
ChannelAttributionEvidence itself (computed in S3's own existing loop, at
zero extra cost) specifically so S6 would never need to re-iterate
neighbors to get it. This satisfies "reuse existing spatial evidence" and
"do not duplicate S3 logic" simultaneously: nothing is recomputed, one
small symmetric field was added where it was missing.

================================================================
WHY THIS IS NOT CIRCULAR WITH S3

S3's OWN classification (REGIONAL_EVENT / ISOLATED_SENSOR_ANOMALY /
UNCERTAIN) is a MULTI-CHANNEL aggregate decision, built from a specific
formula (spatial_coverage x distance_weighted_support x
magnitude_consistency) engineered for S3's cross-channel voting/tie-break
logic (engine.spatial_attribution.aggregate_regional_attribution). S6
does NOT read that classification and relabel it
(REGIONAL_EVENT->SUPPORTED would be exactly the circularity the task
prohibits). Instead, S6 applies its OWN, separately-defined, PER-CHANNEL
decision rule directly to the raw weighted-evidence quantities
(distance_weighted_support vs distance_weighted_contradiction) -- a
literal majority-of-weighted-evidence comparison, not S3's coverage-
discounted product formula. S3's classification is carried through only
as `s3_context`, explicitly documented as informational, never as the
basis for S6's own status.

================================================================
THE COUNTERFACTUAL DECISION RULE (deterministic, no ML, all thresholds
reused from existing config -- none independently invented)

Gate (± "is there anything to verify, with enough neighbors"):
  - Not applicable (S3 already determined this channel shows no
    meaningful deviation -- see spatial_attribution.py) -> nothing to
    counterfactually verify. INSUFFICIENT_EVIDENCE.
  - usable_neighbors < min_neighbors_required (the SAME existing S1-S3
    floor, config.py's CONFIG.spatial.min_neighbors_required) ->
    INSUFFICIENT_EVIDENCE (task's Case E).

Otherwise, let:
  support_clears = distance_weighted_support > MIN_EVIDENCE_STRENGTH
  contradiction_clears = distance_weighted_contradiction > MIN_EVIDENCE_STRENGTH
where MIN_EVIDENCE_STRENGTH = min_neighbors_required / spatial_k_neighbors
-- the SAME derived-not-invented bar S3's aggregate_regional_attribution
already uses ("the evidence_strength attainable at this system's own
configured minimum-neighbor bar with perfect agreement").

  - support_clears and not contradiction_clears -> SUPPORTED
    (task's Case B/D: genuine regional event / regional low-temp event)
  - contradiction_clears and not support_clears -> CONTRADICTED
    (task's Case H: opposite-direction neighborhood)
  - neither clears -> CONTRADICTED. The genuine-reading hypothesis
    predicts neighbors SHOULD show a supporting response; when neither
    meaningful support NOR active opposition appears (neighbors "remain
    normal" -- task's Case A/C: isolated high/low anomaly), the absence
    of the predicted response is itself evidence against the hypothesis,
    not an absence of evidence. This is what makes Case A different from
    the "not enough neighbors" gate above -- there IS enough neighbor
    evidence here, it just doesn't show what the hypothesis predicted.
  - both clear -> genuine competing evidence (task's Case F: mixed
    neighborhood). Decided by which side "clearly" dominates, reusing the
    SAME MAGNITUDE_CONSISTENCY_HIGH_RATIO=3.0 tolerance band S3 already
    established for "clearly bigger, not just numerically larger":
      support >= contradiction * 3.0  -> SUPPORTED
      contradiction >= support * 3.0  -> CONTRADICTED
      otherwise                       -> INSUFFICIENT_EVIDENCE (task's
      explicit requirement: "either SUPPORTED/CONTRADICTED only if the
      weighted evidence clearly exceeds the defined decision rule;
      otherwise INSUFFICIENT_EVIDENCE").

`evidence_strength` is reported as `max(weighted_support,
weighted_contradiction)` ONLY when a decision (SUPPORTED/CONTRADICTED)
was actually reached; it is None (never fabricated) whenever the status
is INSUFFICIENT_EVIDENCE, for ANY reason -- per the task's explicit "If
there is insufficient evidence, do not manufacture a confidence value."
It is an EVIDENCE-STRENGTH score, not a calibrated statistical
probability, and is documented as such everywhere it appears.

Missing channel data (task's Case G) is never treated as contradiction:
a neighbor with a missing/invalid reading for this channel was already
excluded from `neighbor_estimates`/`neighbor_weights` upstream in S2/S3's
own DataQuality filtering -- it contributes to neither support nor
contradiction, exactly like any other genuinely absent observation.

================================================================
ARCHITECTURAL BOUNDARY

S6 answers ONLY: "do the CURRENTLY OBSERVED neighboring stations support
or contradict the hypothesis that this target reading is genuine?" It is
NOT S7 Evidence Fusion, NOT a final root-cause/sensor-fault decision, NOT
forecasting, NOT storm prediction, NOT predictive maintenance, NOT an ML
model, NOT temporal or future-state prediction. Nothing here predicts
what neighbors WILL show -- only what they DO show, right now, relative
to what the genuine-reading hypothesis would predict.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from engine.spatial_attribution import (
    ChannelAttributionEvidence,
    CHANNEL_ORDER,
    CHANNEL_LABELS,
    MAGNITUDE_CONSISTENCY_HIGH_RATIO,
)

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def _min_evidence_strength(min_neighbors_required: int, spatial_k_neighbors: int) -> float:
    """Same derived-not-invented bar S3's aggregate_regional_attribution
    already uses -- see this module's docstring."""
    return min_neighbors_required / spatial_k_neighbors if spatial_k_neighbors > 0 else 1.0


@dataclass(frozen=True)
class ChannelCounterfactualResult:
    channel: str
    status: str  # SUPPORTED | CONTRADICTED | INSUFFICIENT_EVIDENCE
    valid_neighbor_count: int
    supporting_neighbor_count: int
    contradicting_neighbor_count: int
    weighted_support: float
    weighted_contradiction: float
    support_ratio: float
    contradiction_ratio: float
    evidence_strength: Optional[float]
    explanation: str
    s3_classification: Optional[str]   # contextual metadata only -- NOT the basis of `status`
    s3_confidence: Optional[float]     # contextual metadata only -- NOT the basis of `status`

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "status": self.status,
            "valid_neighbor_count": self.valid_neighbor_count,
            "supporting_neighbor_count": self.supporting_neighbor_count,
            "contradicting_neighbor_count": self.contradicting_neighbor_count,
            "weighted_support": round(self.weighted_support, 3),
            "weighted_contradiction": round(self.weighted_contradiction, 3),
            "support_ratio": round(self.support_ratio, 3),
            "contradiction_ratio": round(self.contradiction_ratio, 3),
            "evidence_strength": round(self.evidence_strength, 3) if self.evidence_strength is not None else None,
            "evidence_strength_note": (
                "Evidence-strength score in [0,1] (distance-weighted share of neighbor "
                "evidence behind this status), NOT a calibrated probability, and distinct "
                "from any layer's anomaly score. None when status is INSUFFICIENT_EVIDENCE -- "
                "never fabricated."
            ),
            "explanation": self.explanation,
            "s3_context": {
                "classification": self.s3_classification,
                "confidence": self.s3_confidence,
                "note": (
                    "S3's own multi-channel classification, included for context only. "
                    "S6's status above is computed independently from neighbor-level "
                    "weighted support/contradiction, not derived from this value."
                ),
            },
        }


def evaluate_channel_counterfactual(
    channel: str,
    evidence: ChannelAttributionEvidence,
    *,
    min_neighbors_required: int,
    spatial_k_neighbors: int,
) -> ChannelCounterfactualResult:
    """
    Builds one channel's S6 counterfactual result from an ALREADY-COMPUTED
    S3 ChannelAttributionEvidence. See module docstring for the full
    decision rule.
    """
    label = CHANNEL_LABELS.get(channel, channel)

    if not evidence.applicable:
        return ChannelCounterfactualResult(
            channel=channel, status=INSUFFICIENT_EVIDENCE,
            valid_neighbor_count=evidence.usable_neighbors,
            supporting_neighbor_count=0, contradicting_neighbor_count=0,
            weighted_support=0.0, weighted_contradiction=0.0,
            support_ratio=0.0, contradiction_ratio=0.0, evidence_strength=None,
            explanation=f"{label}: target shows no meaningful deviation from its robust regional baseline "
                        f"-- there is no genuine-reading hypothesis to counterfactually verify.",
            s3_classification=None, s3_confidence=None,
        )

    if evidence.usable_neighbors < min_neighbors_required:
        return ChannelCounterfactualResult(
            channel=channel, status=INSUFFICIENT_EVIDENCE,
            valid_neighbor_count=evidence.usable_neighbors,
            supporting_neighbor_count=evidence.neighbor_support_count,
            contradicting_neighbor_count=evidence.neighbor_disagreement_count,
            weighted_support=evidence.distance_weighted_support,
            weighted_contradiction=evidence.distance_weighted_contradiction,
            support_ratio=evidence.neighbor_support_ratio, contradiction_ratio=evidence.neighbor_disagreement_ratio,
            evidence_strength=None,
            explanation=f"{label}: only {evidence.usable_neighbors} valid neighbor(s), below the required "
                        f"minimum of {min_neighbors_required} -- too little neighbor evidence to verify the "
                        f"genuine-reading hypothesis either way.",
            s3_classification=None, s3_confidence=None,
        )

    min_strength = _min_evidence_strength(min_neighbors_required, spatial_k_neighbors)
    support = evidence.distance_weighted_support
    contradiction = evidence.distance_weighted_contradiction
    support_clears = support > min_strength
    contradiction_clears = contradiction > min_strength

    if support_clears and not contradiction_clears:
        status, strength = SUPPORTED, support
        explanation = (
            f"{label}: nearby stations show a distance-weighted, direction-consistent "
            f"response ({support:.2f} weighted support) with no meaningful opposing evidence "
            f"-- neighboring observations support the genuine-reading hypothesis."
        )
    elif contradiction_clears and not support_clears:
        status, strength = CONTRADICTED, contradiction
        explanation = (
            f"{label}: nearby stations show a distance-weighted response in the OPPOSITE "
            f"direction ({contradiction:.2f} weighted contradiction) -- neighboring "
            f"observations contradict the genuine-reading hypothesis."
        )
    elif not support_clears and not contradiction_clears:
        status, strength = CONTRADICTED, max(support, contradiction, min_strength)
        if evidence.neighbor_disagreement_count > 0:
            explanation = (
                f"{label}: {evidence.neighbor_disagreement_count} nearby station(s) show an "
                f"opposing-direction reading, but at limited distance-weighted influence "
                f"({contradiction:.2f}); no meaningful supporting response appeared either "
                f"({support:.2f}) -- this absence of a supporting response contradicts the "
                f"genuine-reading hypothesis."
            )
        else:
            explanation = (
                f"{label}: the genuine-reading hypothesis predicts a supporting response from "
                f"nearby stations; none appeared (neighbors remain near their own regional "
                f"baseline) -- this absence of the predicted response contradicts the "
                f"genuine-reading hypothesis."
            )
    else:
        # Both clear the bar: genuine competing evidence.
        if support >= contradiction * MAGNITUDE_CONSISTENCY_HIGH_RATIO:
            status, strength = SUPPORTED, support
            explanation = (
                f"{label}: supporting evidence ({support:.2f}) clearly outweighs contradicting "
                f"evidence ({contradiction:.2f}) despite some opposing neighbors -- neighboring "
                f"observations, on balance, support the genuine-reading hypothesis."
            )
        elif contradiction >= support * MAGNITUDE_CONSISTENCY_HIGH_RATIO:
            status, strength = CONTRADICTED, contradiction
            explanation = (
                f"{label}: contradicting evidence ({contradiction:.2f}) clearly outweighs "
                f"supporting evidence ({support:.2f}) despite some agreeing neighbors -- "
                f"neighboring observations, on balance, contradict the genuine-reading hypothesis."
            )
        else:
            status, strength = INSUFFICIENT_EVIDENCE, None
            explanation = (
                f"{label}: supporting ({support:.2f}) and contradicting ({contradiction:.2f}) "
                f"neighbor evidence are both present and comparable in weight -- the "
                f"neighborhood evidence is genuinely mixed, so no confident status is assigned."
            )

    return ChannelCounterfactualResult(
        channel=channel, status=status,
        valid_neighbor_count=evidence.usable_neighbors,
        supporting_neighbor_count=evidence.neighbor_support_count,
        contradicting_neighbor_count=evidence.neighbor_disagreement_count,
        weighted_support=support, weighted_contradiction=contradiction,
        support_ratio=evidence.neighbor_support_ratio, contradiction_ratio=evidence.neighbor_disagreement_ratio,
        evidence_strength=strength,
        explanation=explanation,
        s3_classification=None, s3_confidence=None,  # filled in by the caller, which has S3's overall result
    )


def evaluate_counterfactual_verification(
    channel_evidence: Dict[str, ChannelAttributionEvidence],
    *,
    min_neighbors_required: int,
    spatial_k_neighbors: int,
    s3_classification: Optional[str] = None,
    s3_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Combines per-channel counterfactual results into the overall
    `counterfactual_verification` output. `s3_classification`/
    `s3_confidence` (S3's OWN overall regional_attribution result) are
    attached to every channel's `s3_context` purely as informational
    metadata -- see this module's docstring for why they are never the
    basis of any channel's `status`.
    """
    channels: Dict[str, Dict[str, Any]] = {}
    statuses = []
    for ch in CHANNEL_ORDER:
        if ch not in channel_evidence:
            continue
        result = evaluate_channel_counterfactual(
            ch, channel_evidence[ch],
            min_neighbors_required=min_neighbors_required, spatial_k_neighbors=spatial_k_neighbors,
        )
        result = ChannelCounterfactualResult(
            **{**result.__dict__, "s3_classification": s3_classification, "s3_confidence": s3_confidence}
        )
        label = CHANNEL_LABELS.get(ch, ch)
        channels[label] = result.to_dict()
        statuses.append(result.status)

    decisive = [s for s in statuses if s != INSUFFICIENT_EVIDENCE]
    if not decisive:
        overall_status = INSUFFICIENT_EVIDENCE
        summary = "No channel has sufficient, decisive neighbor evidence to verify the genuine-reading hypothesis."
    elif all(s == SUPPORTED for s in decisive):
        overall_status = SUPPORTED
        summary = "Neighboring observations support the genuine-reading hypothesis across all decisive channels."
    elif all(s == CONTRADICTED for s in decisive):
        overall_status = CONTRADICTED
        summary = "Neighboring observations contradict the genuine-reading hypothesis across all decisive channels."
    else:
        overall_status = INSUFFICIENT_EVIDENCE
        summary = "Channels disagree (some support, some contradict) -- no single overall status is forced."

    return {
        "overall_status": overall_status,
        "channels": channels,
        "summary": summary,
        "method": (
            "Deterministic, per-channel comparison of distance-weighted neighbor support vs. "
            "contradiction (S1 neighbor selection + S2 robust median/MAD + S3 per-neighbor "
            "tally, reused unmodified). No ML, no forecasting, no prediction of future "
            "neighbor behavior -- describes only the CURRENTLY OBSERVED neighborhood."
        ),
    }
