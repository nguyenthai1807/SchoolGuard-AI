import numpy as np
import pytest

from schoolguard.fire import FireEngine, decode, overlap


def hazard(x=0.1, kind="fire"):
    return {"kind": kind, "bbox": [x, 0.1, x + 0.2, 0.4], "confidence": 0.8}


def test_fire_persistence_once():
    engine = FireEngine()
    alerts = [a for t in range(10) for a in engine.update([hazard()], t / 2)]
    assert len(alerts) == 1 and alerts[0]["event_type"] == "fire"
    assert alerts[0]["dwell"] == 2
    assert alerts[0]["severity"] == "urgent"


def test_spatial_jump_does_not_confirm_fire():
    engine = FireEngine()
    assert not [a for t in range(10) for a in engine.update([hazard(0.1 if t % 2 else 0.6)], t / 2)]


def test_missing_frame_resets_evidence():
    engine = FireEngine()
    engine.update([hazard()], 0)
    engine.update([hazard()], 0.5)
    engine.update([], 1)
    assert not engine.update([hazard()], 1.5)
    assert not engine.update([hazard()], 2)


def test_fire_and_smoke_independent():
    engine = FireEngine()
    alerts = [a for t in range(6) for a in engine.update([hazard(), hazard(kind="smoke")], t / 2)]
    assert {a["event_type"] for a in alerts} == {"fire", "smoke"}


def test_fire_short_dropout_does_not_duplicate_notifications():
    engine = FireEngine(dwell=0.5, cooldown=15)
    first = [a for t in (0, 0.25, 0.5) for a in engine.update([hazard()], t)]
    engine.update([], 1)
    second = [a for t in (1.5, 1.75, 2.0) for a in engine.update([hazard()], t)]
    assert len(first) == 1
    assert second == []


def test_decode_letterbox_class_nms():
    output = np.zeros((1, 6, 2100), dtype=np.float32)
    output[0, :, 0] = [160, 160, 160, 80, 0.9, 0.1]
    output[0, :, 1] = [161, 160, 160, 80, 0.85, 0.1]
    output[0, :, 2] = [160, 160, 160, 80, 0.1, 0.8]
    result = decode(output, (160, 320, 3), 1, 0, 80)
    assert len(result) == 2
    assert result[0]["bbox"] == [0.25, 0.25, 0.75, 0.75]


def test_bad_model_output_fails_closed():
    with pytest.raises(ValueError):
        decode(np.zeros((1, 84, 2100)), (100, 100, 3), 1, 0, 0)
    assert overlap([0, 0, 0, 0], [0, 0, 0, 0]) == 0


def test_api_refuses_missing_fire_model(client, request_data):
    response = client.post("/api/jobs", json={**request_data, "detect_fire": True})
    assert response.status_code == 409


def test_tiled_coordinates_are_mapped_to_full_frame():
    from schoolguard.fire import FireDetector

    detector = object.__new__(FireDetector)
    calls = []

    def infer(frame):
        calls.append(frame.shape)
        return [hazard()] if len(calls) == 5 else []

    detector.infer = infer
    result = detector(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert len(calls) == 5 and len(result) == 1
    assert result[0]["bbox"] == pytest.approx([0.46, 0.46, 0.58, 0.64])


def test_small_frame_uses_single_fire_pass():
    from schoolguard.fire import FireDetector

    detector = object.__new__(FireDetector)
    calls = []
    detector.infer = lambda frame: calls.append(frame.shape) or []
    assert detector(np.zeros((240, 320, 3), dtype=np.uint8)) == []
    assert len(calls) == 1


def test_hair_smoke_does_not_confirm_even_when_persistent():
    from schoolguard.fire import filter_hazards
    person = {"bbox": [.2, .1, .8, .9]}
    hair = {"kind": "smoke", "confidence": .98, "bbox": [.35, .1, .65, .28]}
    engine = FireEngine(smoke_dwell=4)
    for t in range(20):
        assert engine.update(filter_hazards([hair], [person]), t*.5) == []
        assert engine.confirmed == []


def test_smoke_outside_head_needs_four_seconds_and_resets_on_absence():
    from schoolguard.fire import filter_hazards
    smoke = hazard(kind="smoke")
    engine = FireEngine(smoke_dwell=4)
    for t in range(8):
        assert engine.update(filter_hazards([smoke], []), t*.5) == []
        assert engine.confirmed == []
    assert len(engine.update([smoke], 4)) == 1
    assert len(engine.confirmed) == 1
    engine.update([], 4.5)
    assert engine.confirmed == []


def test_fire_near_head_remains_eligible():
    from schoolguard.fire import filter_hazards
    smoke = hazard(kind="smoke")
    assert len(filter_hazards([smoke, hazard()], [{"bbox": [0, 0, 1, 1]}])) == 2
    assert filter_hazards([{**smoke, "confidence": .6}], []) == []
