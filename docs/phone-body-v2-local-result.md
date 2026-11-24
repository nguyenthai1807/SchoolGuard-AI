# Local `phone-body-v2` retraining result (2026-10-22)

The original collaborator-trained `phone-body-v2/weights/best.pt` was not present in the GitHub commit, releases, Actions artifacts, or this checkout. This is a **new local candidate**, not a recovered copy of that checkpoint.

- Input: first `.avi` clip from each of 13 ShanghaiTech training scenes at `C:\Users\PCX\Downloads\splits\splits\shanghaitech\training\videos`; copied to ignored `runtime/phone-training/videos` without modifying the originals.
- Training set: 114 frames; validation: 9 frames; held-out test: 9 frames from separate scenes. Test person labels received full-frame visual review (`docs/phone-body-local-test-review.json`). Most train/validation labels remain teacher-model proposals.
- Starting weights: `models/yolo11s.pt`; CPU; 6 epochs; image size 512; batch 4; seed 42. Local result and exact parameters are in ignored `runtime/phone-training/report.json` and `runtime/training-runs/phone-body-v2/provenance.json`.
- Candidate: ignored `runtime/training-runs/phone-body-v2/weights/best.pt` (19,200,666 bytes, SHA-256 `7ddbd4a63147d53a808b5db05bdb5257955d1d9efc2242ec3e56b48b258c330b`).

On the held-out frames at the same inference settings (`conf=0.3`, `iou=0.6`, `imgsz=960`), baseline F1 was **0.905**, precision **0.864**, recall **0.950**, count MAE **0.889**. Candidate F1 was **0.889**, precision **0.800**, recall **1.000**, count MAE **1.111**. Candidate latency was similar (354 vs 371 ms/frame). The candidate **failed the promotion gate** due lower precision, F1, and count accuracy. The production model remains `yolo11s.pt`.

This tiny outdoor, partly pseudo-labelled dataset does not establish phone-camera or indoor performance. Before using the candidate for customers, collect consented phone-camera footage across lighting, angle, distance, and occlusion conditions, hand-label an independent test set, and compare false alarms and missed people on that set. Do not publish source videos or candidate weights until dataset rights are checked.
