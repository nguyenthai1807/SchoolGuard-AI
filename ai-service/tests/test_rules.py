"""Deterministic boundary, dwell, dropout, duplicate suppression and config tests."""

from dataclasses import replace

import pytest

from schoolguard_ai.models import Config, Detection, Zone
from schoolguard_ai.rules import ZoneMonitor, contains

ZONE = Zone("ZONE-01", "Restricted", ((0.5, 0), (1, 0), (1, 1), (0.5, 1)))
INSIDE = Detection(1, 0.9, (0.6, 0.2, 0.8, 0.8))
OUTSIDE = Detection(1, 0.9, (0.1, 0.2, 0.3, 0.8))


def cfg(**kwargs):
    return Config("CAM-01", (ZONE,), **kwargs)


def test_no_people_or_outside_no_alert():
    monitor = ZoneMonitor(cfg(dwell_seconds=0))
    assert monitor.update(0, []).intrusions == []
    assert monitor.update(1, [OUTSIDE]).intrusions == []


def test_dwell_once_then_reentry():
    monitor = ZoneMonitor(cfg())
    for t in (0, 0.5, 1, 1.5):
        assert not monitor.update(t, [INSIDE]).intrusions
    assert len(monitor.update(2, [INSIDE]).intrusions) == 1
    assert not monitor.update(2.2, [INSIDE]).intrusions
    monitor.update(2.3, [OUTSIDE])
    assert not monitor.update(2.4, [INSIDE]).intrusions
    assert len(monitor.update(4.4, [INSIDE]).intrusions) == 1


def test_short_missing_gap_tolerated_long_gap_resets():
    monitor = ZoneMonitor(cfg(dwell_seconds=1, missing_grace_seconds=0.5))
    monitor.update(0, [INSIDE])
    monitor.update(0.3, [INSIDE])
    monitor.update(0.4, [])
    monitor.update(0.6, [INSIDE])
    assert len(monitor.update(1, [INSIDE]).intrusions) == 1
    monitor.update(1.2, [])
    monitor.update(1.6, [])
    assert monitor.states == {}
    assert not monitor.update(1.7, [INSIDE]).intrusions
    assert len(monitor.update(2.7, [INSIDE]).intrusions) == 1


def test_zero_grace_keeps_contiguous_observations():
    monitor = ZoneMonitor(cfg(dwell_seconds=1, missing_grace_seconds=0))
    monitor.update(0, [INSIDE])
    assert len(monitor.update(1, [INSIDE]).intrusions) == 1
    monitor.update(1.1, [])
    assert not monitor.update(1.2, [INSIDE]).intrusions


def test_missing_on_return_beyond_grace_resets():
    monitor = ZoneMonitor(cfg(dwell_seconds=1))
    monitor.update(0, [INSIDE])
    monitor.update(0.1, [])
    assert not monitor.update(2, [INSIDE]).intrusions


def test_untracked_people_count_without_event():
    monitor = ZoneMonitor(cfg(dwell_seconds=0))
    result = monitor.update(0, [replace(INSIDE, track_id=None), replace(INSIDE, track_id=None)])
    assert result.zone_members == {"ZONE-01": [0, 1]}
    assert not result.intrusions


def test_each_person_each_zone_independent():
    config = replace(cfg(dwell_seconds=0), zones=(ZONE, replace(ZONE, zone_id="ZONE-02")))
    result = ZoneMonitor(config).update(0, [INSIDE, replace(INSIDE, track_id=2)])
    assert len(result.intrusions) == 4
    assert result.zone_members == {"ZONE-01": [0, 1], "ZONE-02": [0, 1]}


def test_nonperson_and_low_confidence_ignored():
    result = ZoneMonitor(cfg(dwell_seconds=0)).update(
        0, [replace(INSIDE, label="car"), replace(INSIDE, confidence=0.1)]
    )
    assert not result.intrusions
    assert result.zone_members == {"ZONE-01": []}


def test_center_bottom_boundary_concave():
    lower = Zone("lower", "Lower", ((0, 0.7), (1, 0.7), (1, 1), (0, 1)))
    config = Config("cam", (lower,), dwell_seconds=0)
    assert not ZoneMonitor(config).update(0, [INSIDE]).intrusions
    assert ZoneMonitor(replace(config, anchor="bottom")).update(0, [INSIDE]).intrusions
    assert contains(ZONE.polygon, (0.5, 0.5))
    concave = ((0, 0), (1, 0), (1, 0.4), (0.4, 0.4), (0.4, 1), (0, 1))
    assert contains(concave, (0.2, 0.8))
    assert not contains(concave, (0.8, 0.8))


@pytest.mark.parametrize(
    "change",
    [
        {"dwell_seconds": -1},
        {"missing_grace_seconds": float("nan")},
        {"frame_stride": 0},
        {"frame_stride": True},
        {"image_size": 0},
        {"confidence": float("inf")},
        {"confidence": 0},
        {"anchor": "feet"},
        {"redact_people": "false"},
        {"zones": ()},
        {"zones": (ZONE, ZONE)},
    ],
)
def test_invalid_settings(change):
    with pytest.raises(ValueError):
        replace(cfg(), **change)


@pytest.mark.parametrize(
    "polygon",
    [
        ((0, 0), (1, 1)),
        ((0, 0), (0.5, 0.5), (1, 1)),
        ((0, 0), (1, 0), (1, 1), (0, 0)),
        ((0, 0), (1, 0), (2, 1)),
        ((0, 0), (1, 0.8), (0, 1), (0.8, 0)),
    ],
)
def test_invalid_polygon(polygon):
    with pytest.raises(ValueError):
        Zone("z", "Zone", polygon)


def test_timestamp_and_duplicate_ids_rejected():
    monitor = ZoneMonitor(cfg())
    monitor.update(1, [])
    with pytest.raises(ValueError):
        monitor.update(0, [])
    with pytest.raises(ValueError):
        ZoneMonitor(cfg()).update(0, [INSIDE, INSIDE])
