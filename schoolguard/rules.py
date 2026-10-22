from dataclasses import dataclass

from .schemas import inside


@dataclass
class Visit:
    start: float
    last: float
    observations: int = 1
    alerted: bool = False


class ZoneEngine:
    """One alert per confirmed visit. Observed exit resets immediately."""

    def __init__(self, zones, dwell, max_gap, min_observations=3):
        self.zones = zones
        self.dwell = dwell
        self.max_gap = max_gap
        self.min_observations = min_observations
        self.visits = {}
        self.last_time = -1.0

    def update(self, detections, timestamp):
        if timestamp <= self.last_time:
            raise ValueError("Frame time must increase")
        self.last_time = timestamp
        self.visits = {
            k: v for k, v in self.visits.items() if timestamp - v.last <= self.max_gap + 1e-9
        }
        alerts = []
        active = set()
        for d in detections:
            track = d["track_id"]
            if track is None:
                continue
            x1, _, x2, y2 = d["bbox"]
            foot = ((x1 + x2) / 2, y2)
            for z, zone in enumerate(self.zones):
                key = (z, track)
                if not inside(foot, zone.points):
                    self.visits.pop(key, None)
                    continue
                visit = self.visits.get(key)
                if visit is None:
                    visit = Visit(timestamp, timestamp)
                    self.visits[key] = visit
                else:
                    visit.observations += 1
                    visit.last = timestamp
                if (
                    not visit.alerted
                    and visit.observations >= self.min_observations
                    and timestamp - visit.start + 1e-9 >= self.dwell
                ):
                    visit.alerted = True
                    alerts.append(
                        {**d, "zone": zone.name, "zone_index": z, "dwell": timestamp - visit.start}
                    )
                if visit.alerted:
                    active.add(track)
        return alerts, active
