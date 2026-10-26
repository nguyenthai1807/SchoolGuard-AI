import copy

import numpy as np
import pytest
from pydantic import ValidationError

from schoolguard.behavior import BehaviorEngine, posture
from schoolguard.schemas import JobRequest
from schoolguard.worker import draw


def person(horizontal=False, track=1):
    pose = [[0.0, 0.0, 0.0] for _ in range(17)]
    if horizontal:
        pose[5], pose[6], pose[11], pose[12] = (
            [0.2, 0.65, 0.9],
            [0.2, 0.7, 0.9],
            [0.6, 0.65, 0.9],
            [0.6, 0.7, 0.9],
        )
        box = [0.1, 0.6, 0.85, 0.8]
    else:
        pose[5], pose[6], pose[11], pose[12] = (
            [0.3, 0.25, 0.9],
            [0.5, 0.25, 0.9],
            [0.3, 0.55, 0.9],
            [0.5, 0.55, 0.9],
        )
        box = [0.25, 0.1, 0.55, 0.9]
    return {"track_id": track, "confidence": 0.9, "bbox": box, "keypoints": pose}


def engine(**kwargs):
    return BehaviorEngine(JobRequest(source_id="test", model="yolo11n-pose", **kwargs), 1, 0.5)


def test_no_redaction_by_default_and_pixels_preserved():
    assert JobRequest(source_id="test").redact is False
    image = np.random.default_rng(3).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    d = {"track_id": 1, "confidence": 0.9, "bbox": [0.1, 0.1, 0.9, 0.9]}
    output = draw(image, [d], [], set(), False)
    assert np.array_equal(output[40:70, 50:100], image[40:70, 50:100])


def test_action_requires_pose_model():
    with pytest.raises(ValidationError):
        JobRequest(source_id="x", detect_falls=True)


def test_upright_not_fall():
    e = engine(detect_falls=True)
    assert not [a for n in range(50) for a in e.update([person()], n / 10)]


def test_fall_requires_transition_and_persistence():
    e = engine(detect_falls=True)
    assert not e.update([person()], 0)
    alerts = [a for n in range(1, 30) for a in e.update([person(True)], n / 10)]
    assert [a["event_type"] for a in alerts] == ["suspected_fall"]
    assert alerts[0]["details"]["experimental"] is True


def test_lying_not_diagnosed_as_fall_or_fainting():
    e = engine(detect_falls=True, lying_seconds=2)
    alerts = [a for n in range(40) for a in e.update([person(True)], n / 10)]
    assert [a["event_type"] for a in alerts] == ["prolonged_lying"]


def test_missing_pose_abstains_and_resets():
    e = engine(detect_falls=True, lying_seconds=2)
    d = person(True)
    for n in range(15):
        assert not e.update([d], n / 10)
    missing = copy.deepcopy(d)
    missing["keypoints"][5][2] = 0.1
    assert not e.update([missing], 1.5)
    assert not e.update([d], 1.6)
    assert not e.update([d], 1.9)


def test_tracking_gap_no_false_transition():
    e = engine(detect_falls=True)
    e.update([person()], 0)
    alerts = [a for n in range(10, 25) for a in e.update([person(True)], n / 10)]
    assert not alerts


def test_aspect_ratio_in_posture():
    d = person(True)
    # Same physical geometry expressed in normalized coordinates of wider image.
    wider = copy.deepcopy(d)
    wider["bbox"][0] /= 2
    wider["bbox"][2] /= 2
    for p in wider["keypoints"]:
        p[0] /= 2
    assert posture(d, 1) == posture(wider, 2)


def test_crowd_debounce_and_reset():
    e = engine(crowd_threshold=2, crowd_seconds=1)
    detections = [person(), person(track=2)]
    alerts = [a for n in range(20) for a in e.update(detections, n / 10)]
    assert len(alerts) == 1 and alerts[0]["event_type"] == "crowding"
    assert alerts[0]["track_id"] == -1
    e.update([], 2)
    alerts = [a for n in range(21, 40) for a in e.update(detections, n / 10)]
    assert len(alerts) == 1


def test_interaction_needs_moving_visible_wrists():
    e = engine(detect_interactions=True)
    assert not [a for n in range(30) for a in e.update([person(), person(track=2)], n / 10)]


def test_interaction_positive_and_once():
    e = engine(detect_interactions=True)
    alerts = []
    for n in range(30):
        first, second = person(), person(track=2)
        first["keypoints"][9] = [0.3 if n % 2 else 0.5, 0.4, 0.9]
        alerts.extend(e.update([first, second], n / 10))
    assert len(alerts) == 1
    assert alerts[0]["event_type"] == "vigorous_interaction"
    assert alerts[0]["details"]["track_ids"] == [1, 2]
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["details"]["not_a_violence_classification"] is True


def test_fast_motion_does_not_alert_when_interaction_screening_is_off():
    e = engine(detect_interactions=False)
    alerts = []
    for n in range(30):
        first, second = person(), person(track=2)
        first["keypoints"][9] = [0.3 if n % 2 else 0.5, 0.4, 0.9]
        alerts.extend(e.update([first, second], n / 10))
    assert alerts == []


def interaction_pair(wrist_x):
    first, second = person(), person(track=2)
    first["keypoints"][9] = [wrist_x, 0.4, 0.9]
    return [first, second]


@pytest.mark.parametrize("step", [0.1, 0.2])
def test_short_interaction_burst_confirms_with_three_motion_observations(step):
    e = engine(detect_interactions=True)
    assert not e.update(interaction_pair(0.3), 0)
    assert not e.update(interaction_pair(0.5), step)
    assert not e.update(interaction_pair(0.3), 2 * step)
    alerts = e.update(interaction_pair(0.5), 3 * step)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["event_type"] == "vigorous_interaction"
    assert alert["details"]["positive_observations"] == 3
    assert alert["details"]["onset_timestamp"] == pytest.approx(step)
    assert alert["details"]["confirmed_timestamp"] == pytest.approx(3 * step)
    assert alert["dwell"] == pytest.approx(2 * step)
    assert alert["details"]["not_a_violence_classification"] is True


def test_short_interaction_burst_at_end_of_clip_after_stationary_history():
    e = engine(detect_interactions=True)
    for n in range(40):
        assert not e.update(interaction_pair(0.3), n / 10)
    alerts = [
        a for n, x in enumerate((0.5, 0.3, 0.5), start=40)
        for a in e.update(interaction_pair(x), n / 10)
    ]
    assert len(alerts) == 1
    assert alerts[0]["details"]["onset_timestamp"] == 4.0
    assert alerts[0]["details"]["confirmed_timestamp"] == 4.2


def test_single_wrist_spike_and_return_do_not_confirm_interaction():
    e = engine(detect_interactions=True)
    xs = [0.3] * 10 + [0.5] + [0.3] * 15
    assert not [a for n, x in enumerate(xs) for a in e.update(interaction_pair(x), n / 10)]


def test_three_motion_samples_in_negligible_time_do_not_confirm():
    e = engine(detect_interactions=True)
    assert not [
        a for n in range(4)
        for a in e.update(interaction_pair(0.3 if n % 2 else 0.5), n / 100)
    ]


@pytest.mark.parametrize("camera_motion", ["pan", "zoom"])
def test_common_camera_motion_does_not_confirm_interaction(camera_motion):
    e = engine(detect_interactions=True)
    alerts = []
    for n in range(30):
        pair = interaction_pair(0.55)
        scale = (0.6 if n % 2 else 1.0) if camera_motion == "zoom" else 1.0
        shift = (0.15 if n % 2 else 0.0) if camera_motion == "pan" else 0.0
        for d in pair:
            d["bbox"] = [(v - 0.5) * scale + 0.5 + (shift if i % 2 == 0 else 0)
                         for i, v in enumerate(d["bbox"])]
            for p in d["keypoints"]:
                if p[2] > 0:
                    p[0], p[1] = (p[0] - 0.5) * scale + 0.5 + shift, (p[1] - 0.5) * scale + 0.5
        alerts.extend(e.update(pair, n / 10))
    assert alerts == []


@pytest.mark.parametrize("interruption", ["gap", "missing_pose", "absent"])
def test_interaction_evidence_does_not_bridge_interruption(interruption):
    e = engine(detect_interactions=True)
    for n in range(3):
        assert not e.update(interaction_pair(0.3 if n % 2 else 0.5), n / 10)
    if interruption != "gap":
        pair = interaction_pair(0.3) if interruption == "missing_pose" else []
        if pair:
            pair[0]["keypoints"][5][2] = 0.1
        assert not e.update(pair, 0.3)
    start = 1.0 if interruption == "gap" else 0.4
    for n in range(3):
        assert not e.update(interaction_pair(0.3 if n % 2 else 0.5), start + n / 10)


def test_behavior_episode_details_use_latest_onset_after_absence():
    e = engine(crowd_threshold=2, crowd_seconds=1)
    assert not e.update(interaction_pair(0.3), 0)
    assert not e.update([], 0.1)
    assert not e.update(interaction_pair(0.3), 0.2)
    assert not e.update(interaction_pair(0.3), 0.7)
    alert, = e.update(interaction_pair(0.3), 1.2)
    assert alert["track_id"] == -1
    assert alert["details"]["onset_timestamp"] == 0.2
    assert alert["details"]["confirmed_timestamp"] == 1.2


def test_loiter_zone_only():
    e = engine(
        loiter_seconds=1, zones=[{"name": "gate", "points": [(0, 0), (1, 0), (1, 1), (0, 1)]}]
    )
    alerts = [a for n in range(20) for a in e.update([person()], n / 10)]
    assert len(alerts) == 1 and alerts[0]["event_type"] == "loitering"
    assert alerts[0]["details"]["onset_timestamp"] == 0
    assert alerts[0]["details"]["confirmed_timestamp"] == 1


def test_db_migration_idempotent(client, app):
    from schoolguard.db import Database

    Database(app.state.db.path)
    assert app.state.db.one("PRAGMA user_version")["user_version"] == 5
    assert app.state.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='faces'")


def test_rapid_body_collapse_requires_multiple_observations():
    e = engine(detect_falls=True)
    e.update([person()], 0)
    down = person(True)
    down["bbox"][3] = 0.98
    assert not e.update([down], 0.1)
    assert not e.update([down], 0.2)
    alerts = e.update([down], 0.3)
    assert len(alerts) == 1 and alerts[0]["event_type"] == "suspected_fall"
    assert "rapid_downward" in alerts[0]["details"]["reason"]
    assert not e.update([down], 0.4)


def test_short_rapid_collapse_emits_before_track_is_lost():
    e = engine(detect_falls=True)
    upright = person()
    down = copy.deepcopy(upright)
    down["bbox"] = [0.25, 0.45, 0.6, 0.9]
    down["keypoints"][5] = [0.25, 0.6, 0.9]
    down["keypoints"][6] = [0.45, 0.6, 0.9]
    down["keypoints"][11] = [0.55, 0.8, 0.9]
    down["keypoints"][12] = [0.75, 0.8, 0.9]
    assert not e.update([upright], 0)
    assert not e.update([down], 0.05)
    assert not e.update([down], 0.1)
    alerts = e.update([down], 0.15)
    assert [a["event_type"] for a in alerts] == ["suspected_fall"]
    assert not e.update([], 0.2)


def test_descent_keeps_stable_standing_reference_through_brief_pose_loss():
    e = engine(detect_falls=True)
    alerts = []
    for n in range(31):
        stamp = n / 30
        d = person()
        progress = max(0.0, min(1.0, (stamp - 0.25) / 0.55))
        d["bbox"] = [0.25, 0.1 + 0.5 * progress, 0.55, 0.99]
        for k in (5, 6, 11, 12):
            d["keypoints"][k][1] += 0.42 * progress
        if n == 24:
            d["keypoints"][5][2] = 0.1
        if n >= 25:
            d["keypoints"][5][0] = 0.15
            d["keypoints"][6][0] = 0.3
            d["keypoints"][11][0] = 0.55
            d["keypoints"][12][0] = 0.7
        alerts.extend(e.update([d], stamp))
    assert [a["event_type"] for a in alerts] == ["suspected_fall"]
    assert alerts[0]["severity"] == "urgent"


def test_sitting_above_floor_does_not_raise_red_fall_alert():
    e = engine(detect_falls=True)
    alerts = []
    for n in range(31):
        stamp = n / 30
        d = person()
        progress = max(0.0, min(1.0, (stamp - 0.25) / 0.55))
        d["bbox"] = [0.25, 0.2 + 0.33 * progress, 0.55, 0.84]
        for k in (5, 6, 11, 12):
            d["keypoints"][k][1] += 0.25 * progress
        if n >= 25:
            d["keypoints"][5][0] = 0.15
            d["keypoints"][6][0] = 0.3
            d["keypoints"][11][0] = 0.55
            d["keypoints"][12][0] = 0.7
        alerts.extend(e.update([d], stamp))
    assert not [a for a in alerts if a["event_type"] == "suspected_fall"]
