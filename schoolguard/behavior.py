"""Opt-in temporal screening rules, not clinical or violence classifiers."""

import math
from collections import deque
from dataclasses import dataclass
from itertools import combinations

from .rules import ZoneEngine
from .schemas import inside

TITLES = {
    "suspected_fall": "Nghi té ngã — cần kiểm tra",
    "prolonged_lying": "Nằm lâu — cần kiểm tra",
    "vigorous_interaction": "Chuyển động mạnh gần nhau — nghi xung đột",
    "crowding": "Vượt ngưỡng số người",
    "unexpected_person": "Số người vượt mức thường trú — cần kiểm tra",
    "loitering": "Lưu trú lâu trong vùng",
    "fire": "Nghi có lửa — kiểm tra ngay",
    "smoke": "Nghi có khói — kiểm tra ngay",
}


@dataclass
class Episode:
    start: float
    last: float
    observations: int = 1
    emitted: bool = False


def point(detection, index, aspect):
    pose = detection.get("keypoints", [])
    if len(pose) != 17 or len(pose[index]) != 3:
        return None
    x, y, confidence = pose[index]
    if not all(math.isfinite(v) for v in (x, y, confidence)):
        return None
    if confidence < 0.5 or not (0 < x < 1 and 0 < y < 1):
        return None
    return x * aspect, y


def posture(detection, aspect):
    anchors = [point(detection, i, aspect) for i in (5, 6, 11, 12)]
    if any(p is None for p in anchors):
        return None
    shoulder = tuple((anchors[0][i] + anchors[1][i]) / 2 for i in (0, 1))
    hip = tuple((anchors[2][i] + anchors[3][i]) / 2 for i in (0, 1))
    dx, dy = abs(shoulder[0] - hip[0]), abs(shoulder[1] - hip[1])
    length = math.hypot(dx, dy)
    if length < 0.035:  # Abstain on tiny/degenerate poses.
        return None
    x1, y1, x2, y2 = detection["bbox"]
    ratio = (x2 - x1) * aspect / max(y2 - y1, 1e-6)
    return {
        "horizontal": dx > 1.2 * dy and ratio > 1.1,
        "upright": dy > 1.5 * dx and ratio < 0.95,
        "center": ((shoulder[0] + hip[0]) / 2, (shoulder[1] + hip[1]) / 2),
        "length": length,
    }


class BehaviorEngine:
    def __init__(self, config, aspect, max_gap):
        self.config, self.aspect, self.max_gap = config, aspect, max_gap
        self.episodes = {}
        self.upright = {}
        self.previous = {}
        self.fall_sent = set()
        self.pair_history = {}
        self.pair_alert_time = {}
        self.last_time = -1.0
        self.loiter = ZoneEngine(config.zones, config.loiter_seconds, max_gap)

    def sustained(self, key, timestamp, seconds):
        episode = self.episodes.get(key)
        if episode is None or timestamp - episode.last > self.max_gap + 1e-9:
            episode = Episode(timestamp, timestamp)
            self.episodes[key] = episode
        else:
            episode.last = timestamp
            episode.observations += 1
        if (
            not episode.emitted
            and episode.observations >= 3
            and timestamp - episode.start + 1e-9 >= seconds
        ):
            episode.emitted = True
            return timestamp - episode.start
        return None

    @staticmethod
    def alert(kind, detection, dwell, details, zone=None):
        return {
            **detection,
            "event_type": kind,
            "severity": "urgent"
            if kind in {"suspected_fall", "prolonged_lying", "fire", "smoke"}
            else "warning",
            "zone": zone or TITLES[kind],
            "dwell": dwell,
            "details": {"rule_version": "lh25-home-v1", "experimental": True, **details},
        }

    def update(self, detections, timestamp):
        if timestamp <= self.last_time:
            raise ValueError("Frame time must increase")
        self.last_time = timestamp
        alerts, seen = [], set()
        people = {d["track_id"]: d for d in detections if d["track_id"] is not None}
        valid = {track: p for track, d in people.items() if (p := posture(d, self.aspect))}
        self.upright = {
            k: v for k, v in self.upright.items() if k in people and timestamp - v[0] < 5
        }
        self.fall_sent.intersection_update(people)

        def consider(kind, key, detection, seconds, details, zone=None):
            full = (kind, key)
            seen.add(full)
            duration = self.sustained(full, timestamp, seconds)
            if duration is not None:
                alerts.append(self.alert(kind, detection, duration, details, zone))
                if kind == "suspected_fall":
                    self.fall_sent.add(key)

        if self.config.detect_falls:
            for track, p in valid.items():
                d = people[track]
                prev = self.previous.get(track)
                if prev is None or timestamp - prev[0] > self.max_gap:
                    self.upright.pop(track, None)
                if p["upright"]:
                    self.upright[track] = (
                        timestamp,
                        p["center"][1],
                        p["length"],
                        d["bbox"][3] - d["bbox"][1],
                    )
                    self.fall_sent.discard(track)
                old = self.upright.get(track)
                elapsed = timestamp - old[0] if old else 0
                drop = (p["center"][1] - old[1]) / old[2] if old else 0
                rapid = (
                    old
                    and not p["upright"]
                    and 0 < elapsed <= 1.2
                    and drop > 0.8
                    and drop / elapsed > 1.2
                    and d["bbox"][3] - d["bbox"][1] < old[3] * 0.85
                )
                if rapid and track not in self.fall_sent:
                    consider(
                        "suspected_fall",
                        track,
                        d,
                        0.1,
                        {
                            "reason": "rapid_downward_torso_motion_and_body_height_collapse",
                            "track_ids": [track],
                            "possible_false_positive": "quick_sitting_or_camera_motion",
                        },
                    )
                if p["horizontal"]:
                    # Recent upright posture + downward displacement + sustained horizontal torso.
                    if (
                        not rapid
                        and track not in self.fall_sent
                        and old
                        and p["center"][1] - old[1] > old[2] * 0.35
                    ):
                        consider(
                            "suspected_fall",
                            track,
                            d,
                            0.8,
                            {
                                "reason": "upright_to_horizontal_with_downward_motion",
                                "track_ids": [track],
                            },
                        )
                    consider(
                        "prolonged_lying",
                        track,
                        d,
                        self.config.lying_seconds,
                        {"reason": "horizontal_torso_and_wide_box_sustained", "track_ids": [track]},
                    )

        if self.config.detect_interactions:
            pair_seen = set()
            for first, second in combinations(sorted(valid), 2):
                a, b = valid[first], valid[second]
                scale = max(a["length"], b["length"])
                if math.dist(a["center"], b["center"]) > 2.5 * scale:
                    continue
                pair = (first, second)
                pair_seen.add(pair)
                moving_toward = False
                for src, dest in ((first, second), (second, first)):
                    prior = self.previous.get(src)
                    if prior is None or not 0 < timestamp - prior[0] <= self.max_gap:
                        continue
                    for index in (9, 10):
                        wrist = point(people[src], index, self.aspect)
                        old = point(prior[1], index, self.aspect)
                        if wrist and old:
                            speed = math.dist(wrist, old) / (timestamp - prior[0]) / scale
                            if (
                                speed > 2.0
                                and math.dist(wrist, valid[dest]["center"]) < 1.3 * scale
                            ):
                                moving_toward = True
                history = self.pair_history.setdefault(pair, deque())
                if history and timestamp - history[-1][0] > self.max_gap:
                    history.clear()
                history.append((timestamp, moving_toward))
                while history and timestamp - history[0][0] > 1.5:
                    history.popleft()
                hits = sum(hit for _, hit in history)
                # Movements are bursts, not continuously fast for every video frame.
                # Confirm repeated evidence within a time window, with a per-pair cooldown.
                if (
                    moving_toward
                    and timestamp - history[0][0] >= 0.8
                    and hits >= 4
                    and hits / len(history) >= 0.3
                    and timestamp - self.pair_alert_time.get(pair, -100) >= 10
                ):
                    alerts.append(
                        self.alert(
                            "vigorous_interaction",
                            people[first],
                            timestamp - history[0][0],
                            {
                                "reason": "repeated_fast_wrists_near_another_person",
                                "track_ids": [first, second],
                                "positive_observations": hits,
                                "window_observations": len(history),
                                "not_a_violence_classification": True,
                            },
                        )
                    )
                    self.pair_alert_time[pair] = timestamp
            self.pair_history = {k: v for k, v in self.pair_history.items() if k in pair_seen}
            self.pair_alert_time = {
                k: v for k, v in self.pair_alert_time.items() if timestamp - v < 10
            }

        if self.config.crowd_threshold:
            areas = [(z.name, z.points) for z in self.config.zones] or [("Toàn khung hình", None)]
            for index, (name, polygon) in enumerate(areas):
                members = [
                    d
                    for d in detections
                    if polygon is None
                    or inside(((d["bbox"][0] + d["bbox"][2]) / 2, d["bbox"][3]), polygon)
                ]
                if len(members) >= self.config.crowd_threshold:
                    # Scene aggregate uses -1, not a fabricated identity.
                    aggregate = {
                        "track_id": -1,
                        "bbox": [0, 0, 1, 1],
                        "confidence": min(d["confidence"] for d in members),
                    }
                    consider(
                        "crowding",
                        index,
                        aggregate,
                        self.config.crowd_seconds,
                        {
                            "count": len(members),
                            "threshold": self.config.crowd_threshold,
                            "experimental": False,
                        },
                        name + " — vượt ngưỡng",
                    )

        expected = getattr(self.config, "expected_people", None)
        if expected is not None:
            count = len(detections)
            if count > expected:
                aggregate = {
                    "track_id": -1,
                    "bbox": [0, 0, 1, 1],
                    "confidence": min(d["confidence"] for d in detections),
                }
                consider(
                    "unexpected_person", "home", aggregate, self.config.crowd_seconds,
                    {
                        "count": count, "expected": expected, "excess": count - expected,
                        "anonymous_count_not_identity": True, "experimental": False,
                    },
                    TITLES["unexpected_person"],
                )

        if self.config.loiter_seconds:
            found, _ = self.loiter.update(detections, timestamp)
            for alert in found:
                alerts.append(
                    self.alert(
                        "loitering",
                        alert,
                        alert["dwell"],
                        {"reason": "zone_dwell", "experimental": False},
                        alert["zone"] + " — lưu trú lâu",
                    )
                )
        self.episodes = {k: v for k, v in self.episodes.items() if k in seen}
        self.previous = {k: (timestamp, d) for k, d in people.items() if k in valid}
        return alerts
