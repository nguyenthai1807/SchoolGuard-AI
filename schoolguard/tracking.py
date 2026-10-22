"""Session-local display IDs with conservative recovery after tracker fragmentation."""


def overlap(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    return area / max(
        1e-9, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    )


class StableIds:
    def __init__(self, max_gap=2.5):
        self.max_gap = max_gap
        self.records = {}
        self.next_id = 1

    def update(self, detections, stamp):
        self.records = {
            k: v for k, v in self.records.items() if stamp - v["time"] <= self.max_gap
        }
        # Remove near-identical boxes of the same class before assigning IDs.
        unique = []
        for d in sorted(detections, key=lambda d: d["confidence"], reverse=True):
            if not any(
                d.get("class_id", 0) == u.get("class_id", 0)
                and overlap(d["bbox"], u["bbox"]) > 0.85
                for u in unique
            ):
                unique.append(dict(d))
        used, assigned = set(), {}
        # Reserve existing raw IDs first so a new track cannot steal an active ID.
        for i, d in enumerate(unique):
            raw = d.get("track_id")
            matches = [
                k
                for k, r in self.records.items()
                if k not in used
                and raw is not None
                and r["raw"] == raw
                and r["class"] == d.get("class_id", 0)
                and overlap(r["bbox"], d["bbox"]) > 0.1
            ]
            if matches:
                assigned[i] = matches[0]
                used.add(matches[0])
        pairs = sorted(
            (
                (overlap(d["bbox"], r["bbox"]), i, k)
                for i, d in enumerate(unique)
                if i not in assigned
                for k, r in self.records.items()
                if k not in used and r["class"] == d.get("class_id", 0)
            ),
            reverse=True,
        )
        for score, i, k in pairs:
            if score >= 0.45 and i not in assigned and k not in used:
                assigned[i] = k
                used.add(k)
        for i, d in enumerate(unique):
            ident = assigned.get(i)
            if ident is None:
                ident = self.next_id
                self.next_id += 1
            self.records[ident] = {
                "raw": d.get("track_id"),
                "bbox": d["bbox"],
                "class": d.get("class_id", 0),
                "time": stamp,
            }
            d["track_id"] = ident
        return unique
