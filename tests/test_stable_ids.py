from schoolguard.tracking import StableIds


def detection(raw, box=(0.1, 0.1, 0.3, 0.8), cls=0):
    return {"track_id": raw, "bbox": list(box), "confidence": 0.9, "class_id": cls}


def test_recovers_fragmented_id_and_expires():
    tracker = StableIds()
    first = tracker.update([detection(7)], 0)[0]["track_id"]
    assert tracker.update([detection(12)], 1.1)[0]["track_id"] == first
    assert tracker.update([detection(12)], 5)[0]["track_id"] != first


def test_duplicate_boxes_removed_and_classes_kept_separate():
    tracker = StableIds()
    result = tracker.update([detection(1), detection(2), detection(1, cls=2)], 0)
    assert len(result) == 2
    assert len({d["track_id"] for d in result}) == 2


def test_existing_person_not_stolen_by_new_track():
    tracker = StableIds()
    tracker.update([detection(7)], 0)
    result = tracker.update([detection(8, (0.12, 0.1, 0.32, 0.8)), detection(7)], 1)
    assert len(result) == 2
    assert next(d for d in result if d["bbox"][0] == 0.1)["track_id"] == 1
    assert len({d["track_id"] for d in result}) == 2
