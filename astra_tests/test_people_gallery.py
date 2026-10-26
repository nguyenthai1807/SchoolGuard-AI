"""People-track snapshots must not be presented as face identities."""

import json

import numpy as np

from schoolguard.people import PeopleGallery


def test_back_of_head_gets_anonymous_track_snapshot(tmp_path):
    image = np.full((240, 320, 3), 127, dtype=np.uint8)
    gallery = PeopleGallery(tmp_path)
    detections = [
        {"track_id": index, "bbox": [index * 0.2, 0.1, index * 0.2 + 0.15, 0.9]}
        for index in range(4)
    ]
    gallery.update(image, detections, 0.0)
    gallery.update(image, detections, 0.5)
    result = gallery.finish()
    assert result["count"] == 4
    assert [row["seen_count"] for row in result["items"]] == [2] * 4
    assert all((tmp_path / row["image"]).is_file() for row in result["items"])
    assert json.loads((tmp_path / "people.json").read_text())["count"] == 4
    assert result["count_is_tracks_not_unique_identities"] is True


def test_invalid_or_missing_tracks_do_not_create_identity(tmp_path):
    gallery = PeopleGallery(tmp_path)
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    gallery.update(image, [{"track_id": None, "bbox": [0, 0, 1, 1]},
                           {"track_id": -1, "bbox": [0, 0, 1, 1]}], 0)
    assert gallery.finish()["count"] == 0
