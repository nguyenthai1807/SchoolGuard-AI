import pytest
from pydantic import ValidationError

from schoolguard.rules import ZoneEngine
from schoolguard.schemas import JobRequest, Zone, inside

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def detection(track=1, foot=0.6):
    return {"track_id": track, "confidence": 0.9, "bbox": [0.3, 0.1, 0.5, foot]}


def engine(dwell=0.3):
    return ZoneEngine([Zone(points=SQUARE)], dwell, 0.5)


@pytest.mark.parametrize(
    "point,expected",
    [
        ((0.5, 0.5), True),
        ((0.2, 0.5), True),
        ((0.2, 0.2), True),
        ((0.1, 0.5), False),
        ((0.9, 0.9), False),
    ],
)
def test_polygon_boundary(point, expected):
    assert inside(point, SQUARE) is expected


def test_concave_polygon():
    polygon = [(0, 0), (1, 0), (1, 0.3), (0.3, 0.3), (0.3, 1), (0, 1)]
    assert inside((0.2, 0.8), polygon)
    assert not inside((0.8, 0.8), polygon)


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (1, 1), (0, 1), (1, 0)],
        [(0, 0), (0.5, 0.5), (1, 1)],
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        [(-1, 0), (1, 0), (1, 1)],
        [(0, 0), (float("nan"), 0), (1, 1)],
    ],
)
def test_reject_invalid_polygon(points):
    with pytest.raises(ValidationError):
        Zone(points=points)


def test_dwell_dedup_and_reentry():
    e = engine()
    assert not e.update([detection()], 0)[0]
    assert not e.update([detection()], 0.2)[0]
    assert len(e.update([detection()], 0.4)[0]) == 1
    assert not e.update([detection()], 0.5)[0]
    e.update([detection(foot=0.9)], 0.6)
    e.update([detection()], 0.7)
    e.update([detection()], 0.9)
    assert len(e.update([detection()], 1.1)[0]) == 1


def test_foot_anchor_not_box_center():
    e = engine(0)
    for n in range(4):
        assert not e.update([detection(foot=0.9)], n / 10)[0]


def test_short_gap_keeps_visit_long_gap_resets():
    e = engine()
    e.update([detection()], 0)
    e.update([], 0.1)
    e.update([detection()], 0.2)
    assert len(e.update([detection()], 0.4)[0]) == 1
    e.update([], 1.0)
    assert not e.update([detection()], 1.1)[0]


def test_requires_three_observations_even_zero_dwell():
    e = engine(0)
    assert not e.update([detection()], 0)[0]
    assert not e.update([detection()], 0.1)[0]
    assert len(e.update([detection()], 0.2)[0]) == 1


def test_untracked_and_separate_ids():
    e = engine(0)
    for i in range(3):
        alerts, _ = e.update([detection(None), detection(1), detection(2)], i * 0.1)
    assert len(alerts) == 2
    assert {a["track_id"] for a in alerts} == {1, 2}


def test_timestamps_must_increase():
    e = engine()
    e.update([], 0)
    with pytest.raises(ValueError):
        e.update([], 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stride", True),
        ("stride", 0),
        ("confidence", 0),
        ("confidence", 1.1),
        ("dwell_seconds", -1),
        ("max_seconds", float("inf")),
        ("model", "../../secret"),
        ("image_size", 10000),
    ],
)
def test_job_validation(field, value):
    with pytest.raises(ValidationError):
        JobRequest(source_id="s", **{field: value})
