import json

from schoolguard.config import ROOT, Settings


def iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union else 0


def main():
    root = Settings().runtime / "evaluation"
    labels = json.loads((ROOT / "docs/spotcheck-labels.json").read_text())
    predictions = json.loads((root / "benchmark.json").read_text())
    report = []
    for model in predictions:
        tp = fp = fn = 0
        details = []
        for sample in labels["samples"]:
            prediction = next(p for p in model["results"] if p["scene"] == sample["scene"])
            found = sorted(zip(prediction["boxes"], prediction["confidence"]), key=lambda x: -x[1])
            matched = set()
            scene_tp = scene_fp = 0
            for box, confidence in found:
                if box[3] - box[1] < labels["min_height"] or box[2] - box[0] < labels["min_width"]:
                    continue
                pairs = [
                    (iou(box, gt), i) for i, gt in enumerate(sample["boxes"]) if i not in matched
                ]
                best = max(pairs, default=(0, -1))
                if best[0] >= labels["iou_threshold"]:
                    matched.add(best[1])
                    scene_tp += 1
                else:
                    scene_fp += 1
            scene_fn = len(sample["boxes"]) - len(matched)
            tp += scene_tp
            fp += scene_fp
            fn += scene_fn
            details.append(
                {"scene": sample["scene"], "tp": scene_tp, "fp": scene_fp, "fn": scene_fn}
            )
        result = {
            "model": model["model"],
            "size": model["size"],
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "mean_latency_ms_13_scenes": model["mean_ms"],
            "details": details,
        }
        report.append(result)
        print(json.dumps(result))
    (root / "spotcheck.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
