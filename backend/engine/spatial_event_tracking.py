"""
S5 — Event Evolution.

Answers: "How does a previously detected spatial event (S4) change OVER
TIME?" -- one level above S4, which only answers "what spatial anomaly
clusters exist NOW, from this one snapshot?"

THIS IS DESCRIPTIVE TEMPORAL TRACKING, NOT FORECASTING. This module never
predicts a future centroid, future intensity, future growth, or future
station membership. It only compares the CURRENT S4 result against the
PREVIOUS tracked state and reports what changed BETWEEN two already-
observed snapshots. See "NO FORECASTING" in the S5 final report for the
exact language discipline this is held to.

================================================================
WHY CLUSTER_ID ALONE CANNOT BE EVENT IDENTITY

S4's cluster_id ("CLUSTER_000", ...) is canonical only WITHIN one
clustering call -- it is assigned by sorting that call's OWN clusters by
centroid position. Two unrelated clustering calls can each produce a
"CLUSTER_000" for completely different real-world station groups, purely
because each is the first cluster in ITS OWN sorted order. Treating equal
cluster_id strings across two calls as "the same event" would be a
category error. This module therefore performs EVENT ASSOCIATION --
matching a previous event to a current cluster using observable
characteristics (station membership overlap, centroid distance, channel
overlap, elapsed time) -- and assigns its OWN, separate, tracker-scoped
`event_id` ("EVENT_0001", ...) that persists across calls for as long as
association evidence supports continuity.

================================================================
EVENT ASSOCIATION ALGORITHM (deterministic, no ML, no forecasting)

For a previous ACTIVE event to be considered a CANDIDATE match for a
current cluster, BOTH must hold:
  1. TIME CONTINUITY: elapsed minutes since the event's last_seen must be
     <= max_observation_gap_minutes (see "GAP POLICY" below). If exceeded,
     the event is not even eligible for matching this round -- it is
     evaluated for DISAPPEARANCE instead (see below), never silently
     "reached across" a large gap.
  2. STATION OVERLAP > 0: the current cluster's member_station_ids must
     share AT LEAST ONE station with the previous event's own members.
     This is a deliberate HARD gate, not just weighted evidence: a
     current cluster and a previous event with ZERO shared stations are
     two different station footprints, however close their centroids
     happen to be -- centroid proximity alone is never sufficient to
     claim continuity (this directly implements the task's "a cluster
     should not suddenly jump from a small local event to a completely
     unrelated region and still automatically receive the same event ID"
     requirement, and "UNCERTAIN event association is preferable to false
     continuity"). Because MOVEMENT is expected to happen gradually
     (overlapping membership with a shifted centroid, not a teleporting
     footprint), this gate does not prevent legitimate MOVING detection --
     see TEST 5 in the test suite.

Channel overlap is NOT a hard gate (a genuinely evolving event's dominant
affected channel can legitimately shift, e.g. a temperature anomaly that
later also shows humidity involvement) -- it is reported as evidence only.

CONFIRMED ONE-TO-ONE MATCH: a (previous_event, current_cluster) pair with
nonzero overlap is only treated as a confirmed match if it is MUTUALLY
the ONLY candidate on both sides (the previous event candidate-matches
exactly that one current cluster, AND that current cluster candidate-
matches exactly that one previous event). This is a simple, deterministic,
symmetric definition of "unambiguous" -- not a weighted-score optimizer.

MERGE / SPLIT (ambiguity, not silently resolved):
  - SPLIT: a previous event candidate-matches >= 2 current clusters (its
    members are now spread across multiple current clusters). None of
    those current clusters inherits the previous event_id -- each gets a
    NEW event_id, with an explanatory note referencing the ambiguous
    prior event. The previous event is marked SPLIT_AMBIGUOUS this round
    (not immediately DISAPPEARED -- it may still resolve on a later call).
  - MERGE: a current cluster candidate-matches >= 2 previous events (it
    appears to combine multiple prior events' members). It gets a NEW
    event_id, not either parent's, with an explanatory note. The
    involved previous events are marked MERGE_AMBIGUOUS this round.
  - This is a deliberately SIMPLE ambiguity detector (count-based, not a
    many-to-many optimal-assignment algorithm) -- sufficient to avoid
    false continuity claims without turning S5 into a research project,
    per the task's explicit scope.

GAP POLICY (reused, not invented): "excessive gap" uses
CONFIG.lstm_temporal.max_gap_minutes (15.0 minutes) -- the SAME threshold
already established elsewhere in this codebase for "a reading arriving
after a bigger gap than this cannot be treated as part of a contiguous
sequence at ATHER's assumed native ~10-minute AWS cadence" (see
config.py's LSTMTemporalConfig and TemporalThresholds.rolling_window_samples's
own "12 hours of 10-minute readings" comment, and
app/simulation/scenarios.py's Scenario.interval_minutes default of 10.0 --
all independently corroborating the same assumed native cadence). Reusing
it here means S5's "how long can a gap be before we stop trusting
continuity" policy is IDENTICAL in spirit to the one already governing
Temporal's own history-buffer continuity, not a second, differently-tuned
number.

MOVEMENT / MAGNITUDE-CHANGE SIGNIFICANCE (reused, not invented):
  - MOVING is flagged when centroid_distance_km exceeds
    engine.spatial_clustering.default_eps_km() (125km) -- the cluster's
    OWN coherence radius from S4. "Moved farther than the radius that
    defines spatial coherence in the first place" is a meaningful,
    already-derived-from-config bar; no new number.
  - INTENSIFYING/WEAKENING is flagged when the magnitude change (see
    below) has absolute value >=
    engine.spatial_attribution.MIN_MEANINGFUL_NEIGHBOR_Z (1.0) -- the
    SAME "one channel-appropriate noise-floor unit" bar S3 already uses
    to decide whether a single neighbor's own deviation is real rather
    than noise, reused here for "is this magnitude CHANGE real rather
    than noise" (both quantities are already expressed in the same
    robust-z units).
  - GROWING/SHRINKING use NO threshold at all: station counts are exact
    integers (not noisy statistics), so ANY change is real -- per the
    task's explicit "Growth should be based on actual membership change."

MAGNITUDE QUANTITY: reuses the cluster fingerprint's OWN
magnitude_summary["median"] (built in S4 from each member's |robust_z| --
already-existing S2/S3 robust evidence). No new anomaly score is
introduced.

================================================================
STATE MANAGEMENT: SpatialEventTracker is an explicit, caller-owned object
-- NOT a module-level singleton or hidden global. Each instance owns its
own private event dict and event-numbering counter, so multiple
independent station streams (e.g. separate simulation runs, separate
tests, a future multi-region deployment) can each use their own tracker
with zero cross-contamination. reset() clears all state for reuse in
tests. See app/anomaly/detector.py::AnomalyDetector for how ONE tracker
instance is owned per detector instance (matching the existing pattern
where each AnomalyDetector already owns its own isolated state).

================================================================
ARCHITECTURE: like S4, this operates on REGIONAL SNAPSHOTS (the whole S4
result at one point in time), never once per individual station. See
app/anomaly/detector.py::AnomalyDetector.update_spatial_event_tracking()
for the integration boundary.

This module explicitly does NOT implement: predicted centroid, future
location, forecasted intensity, next-observation prediction, storm-track
prediction, counterfactual verification (S6), or any ML model. It
describes what has ALREADY happened between two observed snapshots.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import CONFIG
from engine.spatial_neighbors import haversine_distance_km
from engine.spatial_clustering import default_eps_km
from engine.spatial_attribution import MIN_MEANINGFUL_NEIGHBOR_Z

EVENT_ID_PREFIX = "EVENT_"

# Reused, not invented -- see module docstring's "GAP POLICY" section.
DEFAULT_MAX_OBSERVATION_GAP_MINUTES = CONFIG.lstm_temporal.max_gap_minutes

# Reused, not invented -- see module docstring's "MOVEMENT / MAGNITUDE-
# CHANGE SIGNIFICANCE" section. Computed via the function (not a frozen
# literal) so a runtime CONFIG.spatial change is honored.
def _movement_significance_km() -> float:
    return default_eps_km()


MIN_MEANINGFUL_MAGNITUDE_CHANGE = MIN_MEANINGFUL_NEIGHBOR_Z


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _station_overlap_ratio(a: Sequence[str], b: Sequence[str]) -> float:
    """Jaccard overlap: |intersection| / |union|. 0.0 when either set is empty."""
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def _channel_overlap_ratio(a: Sequence[str], b: Sequence[str]) -> float:
    return _station_overlap_ratio(a, b)  # same Jaccard definition, different input sets


@dataclass
class SpatialEventState:
    """
    Mutable, tracker-owned record of ONE tracked event's lifecycle across
    successive SpatialEventTracker.update() calls. Not exposed directly
    outside this module's dict output -- see to_dict().
    """
    event_id: str
    status: str  # "ACTIVE" | "DISAPPEARED"
    first_seen: str
    last_seen: str          # last timestamp this event was actually MATCHED (observed)
    last_updated: str       # last timestamp update() was called, matched or not

    current_cluster_id: Optional[str] = None
    member_station_ids: Tuple[str, ...] = ()
    previous_member_station_ids: Tuple[str, ...] = ()

    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    previous_centroid_lat: Optional[float] = None
    previous_centroid_lon: Optional[float] = None

    affected_channels: Tuple[str, ...] = ()
    previous_affected_channels: Tuple[str, ...] = ()

    magnitude: Optional[float] = None
    previous_magnitude: Optional[float] = None

    spatial_extent_km: Optional[float] = None
    previous_spatial_extent_km: Optional[float] = None

    coherence: Optional[float] = None

    evolution_flags: Tuple[str, ...] = ("NEW",)
    notes: Tuple[str, ...] = ()

    def _evidence(self) -> Dict[str, Any]:
        # Explicit "unavailable" handling: a cluster always has >= 2
        # members by construction, so an EMPTY previous_member_station_ids
        # can only mean "no previous snapshot exists yet" (this event is
        # NEW) -- never "the previous cluster had 0 members". None (not 0)
        # is reported in that case, so "unknown" is never confused with
        # "no change" (task's explicit requirement).
        member_count_change = (
            len(self.member_station_ids) - len(self.previous_member_station_ids)
            if self.previous_member_station_ids else None
        )

        centroid_distance_km = None
        if (self.centroid_lat is not None and self.centroid_lon is not None
                and self.previous_centroid_lat is not None and self.previous_centroid_lon is not None):
            centroid_distance_km = haversine_distance_km(
                self.previous_centroid_lat, self.previous_centroid_lon,
                self.centroid_lat, self.centroid_lon,
            )

        magnitude_change = None
        if self.magnitude is not None and self.previous_magnitude is not None:
            magnitude_change = self.magnitude - self.previous_magnitude

        extent_change_km = None
        if self.spatial_extent_km is not None and self.previous_spatial_extent_km is not None:
            extent_change_km = self.spatial_extent_km - self.previous_spatial_extent_km

        station_overlap = (
            _station_overlap_ratio(self.member_station_ids, self.previous_member_station_ids)
            if self.previous_member_station_ids else None
        )
        channel_overlap = (
            _channel_overlap_ratio(self.affected_channels, self.previous_affected_channels)
            if self.previous_affected_channels else None
        )

        duration_seconds = (_parse_iso(self.last_updated) - _parse_iso(self.first_seen)).total_seconds()

        return {
            "member_count_change": member_count_change,
            "member_count_change_ratio": (
                round(member_count_change / len(self.previous_member_station_ids), 3)
                if member_count_change is not None and self.previous_member_station_ids else None
            ),
            "centroid_distance_km": round(centroid_distance_km, 2) if centroid_distance_km is not None else None,
            "magnitude_change": round(magnitude_change, 3) if magnitude_change is not None else None,
            "magnitude_change_ratio": (
                round(magnitude_change / self.previous_magnitude, 3)
                if magnitude_change is not None and self.previous_magnitude not in (None, 0) else None
            ),
            "spatial_extent_change_km": round(extent_change_km, 1) if extent_change_km is not None else None,
            "channel_overlap_ratio": round(channel_overlap, 3) if channel_overlap is not None else None,
            "station_overlap_ratio": round(station_overlap, 3) if station_overlap is not None else None,
            "duration_seconds": round(duration_seconds, 1),
            "duration_minutes": round(duration_seconds / 60.0, 2),
        }

    def to_dict(self) -> Dict[str, Any]:
        evidence = self._evidence()
        return {
            "event_id": self.event_id,
            "status": self.status,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_updated": self.last_updated,
            "current_cluster_id": self.current_cluster_id,
            "member_count": len(self.member_station_ids),
            "member_station_ids": list(self.member_station_ids),
            "centroid": (
                {"lat": round(self.centroid_lat, 4), "lon": round(self.centroid_lon, 4)}
                if self.centroid_lat is not None else None
            ),
            "affected_channels": list(self.affected_channels),
            "magnitude": round(self.magnitude, 3) if self.magnitude is not None else None,
            "spatial_extent_km": self.spatial_extent_km,
            "coherence": self.coherence,
            "evolution_flags": list(self.evolution_flags),
            "evidence": evidence,
            "notes": list(self.notes),
            "confidence_note": (
                "Evolution flags/evidence describe OBSERVED change between two already-"
                "recorded snapshots, derived deterministically (no ML, no forecasting). "
                "They are NOT predictions of future movement, growth, or intensity, and "
                "NOT a confirmation of true physical storm movement or a calibrated "
                "meteorological event identity -- see explanation."
            ),
            "explanation": self._explanation(evidence),
        }

    def _explanation(self, evidence: Dict[str, Any]) -> str:
        if "NEW" in self.evolution_flags:
            return (
                f"{self.event_id}: newly detected spatial anomaly cluster with "
                f"{len(self.member_station_ids)} member station(s)."
            )
        if self.status == "DISAPPEARED":
            return (
                f"{self.event_id}: no matching cluster observed within the "
                f"{DEFAULT_MAX_OBSERVATION_GAP_MINUTES:.0f}-minute observation-gap policy -- "
                f"marked DISAPPEARED as of {self.last_updated}."
            )
        parts = [f"{self.event_id} is {'/'.join(f for f in self.evolution_flags if f != 'PERSISTING') or 'PERSISTING'}"]
        if evidence["member_count_change"]:
            parts.append(f"membership changed by {evidence['member_count_change']:+d} station(s)")
        if evidence["centroid_distance_km"] is not None:
            parts.append(f"cluster centroid shifted {evidence['centroid_distance_km']:.1f}km")
        if evidence["magnitude_change"] is not None:
            parts.append(f"anomaly magnitude changed by {evidence['magnitude_change']:+.2f} (robust-z units)")
        return "; ".join(parts) + "."


class SpatialEventTracker:
    """
    S5 event tracker. See module docstring for the full association/
    matching/ambiguity/gap-policy algorithm. Explicit, caller-owned state
    -- construct one per independent station stream; never shared as a
    module-level global.
    """

    def __init__(self, max_observation_gap_minutes: Optional[float] = None):
        self._events: Dict[str, SpatialEventState] = {}
        self._next_event_number = 1
        self.max_observation_gap_minutes = (
            max_observation_gap_minutes
            if max_observation_gap_minutes is not None
            else DEFAULT_MAX_OBSERVATION_GAP_MINUTES
        )

    def reset(self) -> None:
        """Clears all tracked event state. Use between independent test
        runs or independent station streams sharing one tracker instance."""
        self._events.clear()
        self._next_event_number = 1

    def _new_event_id(self) -> str:
        eid = f"{EVENT_ID_PREFIX}{self._next_event_number:04d}"
        self._next_event_number += 1
        return eid

    def update(self, spatial_events_result: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        """
        Feeds ONE S4 compute_spatial_events() result (the dict form) at
        ONE point in time into the tracker. Returns the S5
        `spatial_event_evolution` output. Does NOT call S1-S4 itself --
        the caller (AnomalyDetector.update_spatial_event_tracking) is
        responsible for producing spatial_events_result first.
        """
        ts_iso = _iso(timestamp)
        current_clusters = spatial_events_result.get("clusters", [])

        # ── Gap policy: events too old to trust continuity for are
        # removed from matching consideration BEFORE any overlap is
        # computed, and evaluated for disappearance separately. ────────
        previously_active = [e for e in self._events.values() if e.status == "ACTIVE"]
        eligible_events: List[SpatialEventState] = []
        gap_expired_events: List[SpatialEventState] = []
        for ev in previously_active:
            elapsed_min = (timestamp - _parse_iso(ev.last_seen)).total_seconds() / 60.0
            if elapsed_min > self.max_observation_gap_minutes:
                gap_expired_events.append(ev)
            else:
                eligible_events.append(ev)

        # ── Candidate matches: nonzero station overlap, both directions ──
        event_candidates: Dict[str, List[int]] = {ev.event_id: [] for ev in eligible_events}
        cluster_candidates: Dict[int, List[str]] = {i: [] for i in range(len(current_clusters))}
        for ev in eligible_events:
            for i, cl in enumerate(current_clusters):
                overlap = _station_overlap_ratio(ev.member_station_ids, cl["member_station_ids"])
                if overlap > 0:
                    event_candidates[ev.event_id].append(i)
                    cluster_candidates[i].append(ev.event_id)

        confirmed: Dict[str, int] = {}       # event_id -> cluster index
        split_ambiguous: List[str] = []      # event_ids matched to >=2 clusters
        merge_ambiguous_clusters: List[int] = []  # cluster indices matched to >=2 events

        for ev in eligible_events:
            matches = event_candidates[ev.event_id]
            if len(matches) == 1:
                ci = matches[0]
                if len(cluster_candidates[ci]) == 1:
                    confirmed[ev.event_id] = ci
                else:
                    merge_ambiguous_clusters.append(ci)
            elif len(matches) >= 2:
                split_ambiguous.append(ev.event_id)

        merge_ambiguous_clusters = sorted(set(merge_ambiguous_clusters))
        matched_cluster_indices = set(confirmed.values())

        associations: List[Dict[str, Any]] = []
        updated_events: List[Dict[str, Any]] = []
        events_by_id = {ev.event_id: ev for ev in self._events.values()}

        # ── Apply confirmed matches ──────────────────────────────────
        for event_id, ci in sorted(confirmed.items()):
            ev = events_by_id[event_id]
            cl = current_clusters[ci]
            overlap = _station_overlap_ratio(ev.member_station_ids, cl["member_station_ids"])
            ev.previous_member_station_ids = ev.member_station_ids
            ev.previous_centroid_lat, ev.previous_centroid_lon = ev.centroid_lat, ev.centroid_lon
            ev.previous_affected_channels = ev.affected_channels
            ev.previous_magnitude = ev.magnitude
            ev.previous_spatial_extent_km = ev.spatial_extent_km

            ev.current_cluster_id = cl["cluster_id"]
            ev.member_station_ids = tuple(cl["member_station_ids"])
            ev.centroid_lat, ev.centroid_lon = cl["centroid"]["lat"], cl["centroid"]["lon"]
            ev.affected_channels = tuple(cl["affected_channels"])
            ev.magnitude = cl["magnitude_summary"]["median"]
            ev.spatial_extent_km = cl["spatial_extent_km"]
            ev.coherence = cl["coherence"]
            ev.last_seen = ts_iso
            ev.last_updated = ts_iso
            ev.notes = ()

            flags = ["PERSISTING"]
            member_change = len(ev.member_station_ids) - len(ev.previous_member_station_ids)
            if member_change > 0:
                flags.append("GROWING")
            elif member_change < 0:
                flags.append("SHRINKING")
            centroid_dist = None
            if ev.previous_centroid_lat is not None:
                centroid_dist = haversine_distance_km(
                    ev.previous_centroid_lat, ev.previous_centroid_lon, ev.centroid_lat, ev.centroid_lon
                )
                if centroid_dist > _movement_significance_km():
                    flags.append("MOVING")
            mag_change = None
            if ev.previous_magnitude is not None:
                mag_change = ev.magnitude - ev.previous_magnitude
                if mag_change >= MIN_MEANINGFUL_MAGNITUDE_CHANGE:
                    flags.append("INTENSIFYING")
                elif mag_change <= -MIN_MEANINGFUL_MAGNITUDE_CHANGE:
                    flags.append("WEAKENING")
            ev.evolution_flags = tuple(flags)

            associations.append({
                "event_id": event_id, "cluster_id": cl["cluster_id"],
                "station_overlap_ratio": round(overlap, 3), "match_type": "CONFIRMED",
            })
            updated_events.append(ev.to_dict())

        # ── Unmatched-but-still-eligible events: stay ACTIVE, no evolution computed ──
        unmatched_active_ids = {ev.event_id for ev in eligible_events} - set(confirmed.keys())
        for event_id in sorted(unmatched_active_ids):
            ev = events_by_id[event_id]
            ev.last_updated = ts_iso
            if event_id in split_ambiguous:
                ev.notes = (f"Possible SPLIT: overlapped with {len(event_candidates[event_id])} "
                            f"current clusters this update -- no single confident continuation.",)
                ev.evolution_flags = ("SPLIT_AMBIGUOUS",)
                for ci in event_candidates[event_id]:
                    associations.append({
                        "event_id": event_id, "cluster_id": current_clusters[ci]["cluster_id"],
                        "station_overlap_ratio": round(
                            _station_overlap_ratio(ev.previous_member_station_ids or ev.member_station_ids,
                                                    current_clusters[ci]["member_station_ids"]), 3),
                        "match_type": "AMBIGUOUS_SPLIT_CANDIDATE",
                    })
            # else: simply no candidate cluster this round -- stays ACTIVE, unmatched, PERSISTING assumed implicit.

        # ── Gap-expired events -> DISAPPEARED ────────────────────────
        disappeared_events: List[Dict[str, Any]] = []
        for ev in gap_expired_events:
            ev.status = "DISAPPEARED"
            ev.current_cluster_id = None
            ev.last_updated = ts_iso
            ev.evolution_flags = ("DISAPPEARED",)
            ev.notes = (f"No matching cluster within {self.max_observation_gap_minutes:.0f} "
                        f"minute(s) of last_seen ({ev.last_seen}).",)
            disappeared_events.append(ev.to_dict())

        # ── New events: unmatched current clusters, or merge targets.
        # `current_clusters` is already in S4's own canonical (centroid-
        # sorted) order, so iterating it directly here (rather than
        # re-sorting) is itself deterministic. ─────────────────────────
        newly_detected: List[Dict[str, Any]] = []
        for i, cl in enumerate(current_clusters):
            if i in matched_cluster_indices:
                continue
            eid = self._new_event_id()
            notes: Tuple[str, ...] = ()
            if i in merge_ambiguous_clusters:
                parents = sorted(cluster_candidates[i])
                notes = (f"Possible MERGE of previous events {', '.join(parents)} -- "
                         f"assigned a NEW event id rather than inheriting either parent's identity.",)
                for pid in parents:
                    events_by_id[pid].status = "ACTIVE"  # still active, just unresolved this round
                    events_by_id[pid].evolution_flags = ("MERGE_AMBIGUOUS",)
                    events_by_id[pid].last_updated = ts_iso
                    events_by_id[pid].notes = (f"Possible MERGE into new event {eid}.",)
                    associations.append({
                        "event_id": pid, "cluster_id": cl["cluster_id"],
                        "station_overlap_ratio": round(
                            _station_overlap_ratio(events_by_id[pid].member_station_ids, cl["member_station_ids"]), 3),
                        "match_type": "AMBIGUOUS_MERGE_CANDIDATE",
                    })
            new_state = SpatialEventState(
                event_id=eid, status="ACTIVE", first_seen=ts_iso, last_seen=ts_iso, last_updated=ts_iso,
                current_cluster_id=cl["cluster_id"], member_station_ids=tuple(cl["member_station_ids"]),
                centroid_lat=cl["centroid"]["lat"], centroid_lon=cl["centroid"]["lon"],
                affected_channels=tuple(cl["affected_channels"]),
                magnitude=cl["magnitude_summary"]["median"], spatial_extent_km=cl["spatial_extent_km"],
                coherence=cl["coherence"], evolution_flags=("NEW",), notes=notes,
            )
            self._events[eid] = new_state
            newly_detected.append(new_state.to_dict())

        active_events = [ev.to_dict() for ev in self._events.values() if ev.status == "ACTIVE"]
        active_events.sort(key=lambda e: e["event_id"])

        return {
            "active_events": active_events,
            "newly_detected_events": newly_detected,
            "updated_events": updated_events,
            "disappeared_events": disappeared_events,
            "associations": associations,
            "summary": {
                "active_count": len(active_events),
                "new_count": len(newly_detected),
                "updated_count": len(updated_events),
                "disappeared_count": len(disappeared_events),
                "ambiguous_count": len(split_ambiguous) + len(merge_ambiguous_clusters),
            },
            "timestamp": ts_iso,
            "max_observation_gap_minutes": self.max_observation_gap_minutes,
            "method": (
                "Deterministic event association over S4 cluster fingerprints: station-"
                "overlap-gated, time-gap-bounded matching (no ML, no forecasting). "
                "Describes OBSERVED change between two already-recorded snapshots only."
            ),
        }
