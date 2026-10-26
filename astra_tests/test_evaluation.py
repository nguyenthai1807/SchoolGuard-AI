import copy

from scripts.evaluate_training import compare, metrics, promotion
from scripts.score_spotcheck import iou


def test_iou_geometry():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1
    assert iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0
    assert iou([0, 0, 10, 10], [5, 0, 15, 10]) == 1 / 3


def test_one_ground_truth_cannot_match_two_detections():
    assert compare([[0, 0, 10, 10], [0, 0, 10, 10]], [0.9, 0.8], [[0, 0, 10, 10]]) == (1, 1, 0)
    assert compare([], [], [[0, 0, 10, 10]]) == (0, 0, 1)


def test_no_detections_is_not_perfect_precision():
    assert metrics(0, 0, 1)["precision"] == 0
    assert metrics(0, 0, 0)["f1"] == 0


def test_promotion_rejects_regression_or_missing_measurements():
    baseline = {
        "overall": metrics(80, 10, 20),
        "slices": {"shanghaitech": metrics(8, 1, 2)},
        "mean_latency_ms": 100,
    }
    candidate = {
        "overall": metrics(90, 5, 10),
        "slices": {"shanghaitech": metrics(9, 1, 1)},
        "mean_latency_ms": 60,
    }
    assert promotion(candidate, baseline)
    bad = copy.deepcopy(candidate)
    bad["slices"]["shanghaitech"] = metrics(7, 0, 3)
    assert not promotion(bad, baseline)
    bad = copy.deepcopy(candidate)
    bad["mean_latency_ms"] = float("nan")
    assert not promotion(bad, baseline)
    assert not promotion({}, baseline)


def test_training_endpoint_without_artifacts(client):
    result = client.get("/api/training").json()
    assert result["runs"] == [] and result["report"] is None
    assert result["candidate_available"] is False
