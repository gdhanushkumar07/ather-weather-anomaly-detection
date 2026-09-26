"""
Layer 3 ensemble decision — explicit, weight-free.

Each model independently flags an observation when its conformal p-value is
<= alpha (its calibrated false-alarm rate on normal data, see models.py):

    ECOD flag   IFOR flag   ->  status       confidence   layer3_anomaly
    ---------   ---------       ----------   ----------   --------------
       yes         yes          ANOMALY      HIGH         True
       yes         no           SUSPICIOUS   LOW          False
       no          yes          SUSPICIOUS   LOW          False
       no          no           NORMAL       NONE         False

The two models look at the feature space differently (per-dimension tails vs
joint isolation), so agreement is stronger evidence than either alone; no
weighted average is used, so there is no weight to justify. If only one model
is available (disabled or failed to fit) the most it can produce is
SUSPICIOUS — one model alone never reaches HIGH confidence.

LAYER SCORE — fusion (fusion/conformal_fusion.py) consumes a single [0, 1]
score per layer, and detector.py renders the Layer 3 card with fixed bands.
The mapping is chosen to land each tier in the matching existing band:

    ANOMALY     0.80 .. 1.00   card ANOMALY (>=0.75), fusion acute trigger (>=0.80)
    SUSPICIOUS  0.60 .. 0.74   card WARNING (>=0.50), fusion WARNING (peak >=0.60)
    NORMAL      0.00 .. 0.45   card PASS

Within a tier the position grows with how far the (weaker/stronger) p-value
is below alpha, on a log10 scale: one decade below alpha = half-way, two
decades = top of the tier.
"""
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

ANOMALY = "ANOMALY"
SUSPICIOUS = "SUSPICIOUS"
NORMAL = "NORMAL"


@dataclass
class Layer3Decision:
    ecod_anomaly: Optional[bool]
    isolation_forest_anomaly: Optional[bool]
    layer3_anomaly: bool
    status: str
    confidence: str
    layer_score: float

    def to_dict(self):
        return asdict(self)


def _decades_below(p: float, alpha: float) -> float:
    return float(np.clip((np.log10(alpha) - np.log10(max(p, 1e-12))) / 2.0, 0.0, 1.0))


def decide(ecod_p: Optional[float], if_p: Optional[float], alpha: float) -> Layer3Decision:
    ecod_flag = None if ecod_p is None else bool(ecod_p <= alpha)
    if_flag = None if if_p is None else bool(if_p <= alpha)
    flags = [f for f in (ecod_flag, if_flag) if f is not None]
    ps = [p for p in (ecod_p, if_p) if p is not None]

    if len(flags) == 2 and all(flags):
        status, conf = ANOMALY, "HIGH"
        score = 0.80 + 0.20 * _decades_below(max(ps), alpha)
    elif any(flags):
        status, conf = SUSPICIOUS, "LOW"
        score = 0.60 + 0.14 * _decades_below(min(ps), alpha)
    else:
        status, conf = NORMAL, "NONE"
        # 0 when p = 1, rising to 0.45 as the most extreme p approaches alpha.
        score = 0.0 if not ps else 0.45 * float(np.clip(np.log10(min(ps)) / np.log10(alpha), 0.0, 1.0))

    return Layer3Decision(
        ecod_anomaly=ecod_flag,
        isolation_forest_anomaly=if_flag,
        layer3_anomaly=(status == ANOMALY),
        status=status,
        confidence=conf,
        layer_score=round(float(score), 4),
    )


def decide_arrays(ecod_p: np.ndarray, if_p: np.ndarray, alpha: float):
    """Vectorised flags for evaluation: returns (ecod_flag, if_flag, anomaly, suspicious_or_anomaly)."""
    e = np.asarray(ecod_p) <= alpha
    i = np.asarray(if_p) <= alpha
    return e, i, e & i, e | i
