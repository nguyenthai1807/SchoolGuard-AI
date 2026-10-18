"""Restricted-zone state machine, independent of OpenCV and model dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Config, Detection, Intrusion, Point, RuleResult, nonnegative, on_segment


def contains(polygon: tuple[Point, ...], point: Point) -> bool:
    """Ray casting, inclusive boundary, accepts simple concave polygons."""
    x, y = point
    within = False
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        if on_segment(a, b, point):
            return True
        if (a[1] > y) != (b[1] > y):
            crossing_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < crossing_x:
                within = not within
    return within


@dataclass
class TrackState:
    entered: float
    last_seen: float
    alerted: bool = False
    missing: bool = False


class ZoneMonitor:
    """One event per tracked person's visit to each zone; observed exit resets immediately.

    Missing detections are tolerated for a configurable interval; a longer gap starts
    a new visit. Elapsed time includes short missing gaps, as an explicit heuristic.
    Tracker IDs are anonymous, run-local identities, not student identities.
    """

    def __init__(self, config: Config):
        self.config = config
        self.states: dict[tuple[str, int], TrackState] = {}
        self.previous_ts: float | None = None

    def update(self, ts: float, detections: list[Detection]) -> RuleResult:
        nonnegative(ts, "video timestamp")
        if self.previous_ts is not None and ts <= self.previous_ts:
            raise ValueError("timestamps must strictly increase within a run")
        self.previous_ts = ts
        result = RuleResult(zone_members={z.zone_id: [] for z in self.config.zones})
        # Prune stale IDs even when no person is seen: memory does not grow forever.
        self.states = {
            key: st
            for key, st in self.states.items()
            if not st.missing or ts - st.last_seen <= self.config.missing_grace_seconds + 1e-9
        }
        observed_inside = set()
        seen_ids = set()
        for index, detection in enumerate(detections):
            if detection.label != "person" or detection.confidence < self.config.confidence:
                continue
            tid = detection.track_id
            if tid is not None:
                if tid in seen_ids:
                    raise ValueError("duplicate person track_id within frame")
                seen_ids.add(tid)
            x1, y1, x2, y2 = detection.bbox
            point = ((x1 + x2) / 2, y2 if self.config.anchor == "bottom" else (y1 + y2) / 2)
            for zone in self.config.zones:
                key = (zone.zone_id, tid)
                if not contains(zone.polygon, point):
                    self.states.pop(key, None)
                    continue
                result.zone_members[zone.zone_id].append(index)
                if tid is None:
                    continue  # Draw/count it, but do not merge unknown people into a single track.
                observed_inside.add(key)
                state = self.states.setdefault(key, TrackState(ts, ts))
                state.last_seen = ts
                state.missing = False
                dwell = ts - state.entered
                if not state.alerted and dwell + 1e-9 >= self.config.dwell_seconds:
                    state.alerted = True
                    result.intrusions.append(Intrusion(zone.zone_id, detection, ts, dwell))
                if state.alerted:
                    result.alerting_tracks.add(key)
        for key in list(self.states):
            if key not in observed_inside:
                state = self.states[key]
                state.missing = True
                if ts - state.last_seen > self.config.missing_grace_seconds + 1e-9:
                    del self.states[key]
        return result
