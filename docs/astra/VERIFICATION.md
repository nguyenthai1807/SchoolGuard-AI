# Verification / handoff — 2026-10-16

Workspace: `D:\UIT\Computer Vision in Security Systems\SchoolGuard-6Astra-Test`. Original SchoolGuard-AI code was not changed. Its GitHub visibility was confirmed public.

Local service: http://127.0.0.1:8766, started from the D: checkout. Chrome login, configuration, queue, real YOLO inference and completed video flow exercised. MXterm preview connector returns `missing bearer token`; automatic MXterm integration is not verified.

73 automated tests passed (10.83s), including auth/permissions, source bounds, queue/cancel, video encoding, polygon/dwell, pose temporal rules, tiled fire coordinates/NMS/persistence, and Windows preview lock regression. Ruff lint/format and JavaScript syntax checks passed. Tests use controlled fixtures and do NOT establish AI field accuracy. One upstream Starlette/httpx deprecation warning remains.

## Delivered functions

- Unblurred output by default; privacy blur remains opt-in. Old rendered videos must be reprocessed.
- Person detection/tracking, configurable restricted zones, evidence, review, CSV, audit and local accounts.
- Optional YOLO11n-pose skeletons, suspected rapid collapse/fall, prolonged lying and vigorous close interaction screening. Crowd threshold and long zone dwell.
- Separate pinned ONNX fire/smoke model with checksum, 320px letterbox, overlapping tiles for distant objects, class-aware suppression and spatial/temporal confirmation. Not a certified fire alarm.
- Event type, severity, reasons and per-type counts; no medical diagnosis or conclusion of violence.

## Real data and measured limitations

Person training completed 12 CPU epochs, 312 train / 46 validation / 50 development-test images from ShanghaiTech, COCO128, Penn-Fudan. Candidate F1 0.8018 vs baseline YOLO11s 0.8319; candidate NOT promoted. `models/training-report.json` records detailed metrics. Only three ShanghaiTech test frames; COCO128 overlaps pretraining; no campus accuracy guarantee.

Prepared 18 research clips and 54 selected RGB frames: 12 AIRTLab (6 staged violent, 6 nonviolent), 5 UR Fall Detection (3 fall, 2 daily activity), one author wildfire example. One additional ADL download timed out. `runtime/event-data/manifest.json` records hashes, labels, groups, splits and restrictions. URFD author previews contain depth+RGB side-by-side; RGB-only H264 derivatives preserve originals. Fire frames require bounding-box annotation before supervised training. Action models have NOT been trained on these 18 clips.

Real initial pose jobs completed at roughly 6–10 processed FPS on this CPU, not guaranteed 30 FPS realtime. Initial conservative action rules missed the fall/interaction examples; saved detections were used for development error analysis and updated rapid-collapse / burst-window rules. Small distant smoke was missed at full-image 320px resolution; overlapping tiles added. These are development samples, NOT an independent accuracy benchmark. Final demo jobs must be read by status, not assumed successful.

Windows preview FileResponse caused a file-replacement lock in one demo. Fixed by returning in-memory JPEG bytes, synchronizing preview access and making a failed preview replacement nonfatal. Added deterministic regression test.

### Final real-video results

- AIRTLab violent-001: full 145 frames, one vigorous-interaction alert at 2.2s; 8.36 processing FPS, no blur. Chrome H264 playback confirmed, 1920×1080, readyState 4.
- Author wildfire example: full 131 frames / 65.5s, one smoke alert with tiled inference; 2.10 processing FPS, 62.52s runtime. This validates a smoke example, not the flame class or field detection accuracy.
- URFD fall-01: full clip completes but event missed; do not claim reliable fall detection. Development replay catches fall-02 at 2.33s; fall-03 also missed. ADL-02 replay has no alert.
- Saved run IDs: `0d98a6ce43a641198c6156099e6a866f` (interaction), `6de6805f37cd471ba8337bd5ea03cad2` (smoke). Outputs live in runtime/jobs, not Git.
- Final end-to-end URFD fall-02 run `4c9fb824c76b467789620930aa7092fc`: one suspected-fall alert, 11.42 processing FPS. AIRTLab non-violent-006 run `4040cc0ec91543b9947b4bb80b022882` with pose/interaction/fire enabled: zero alerts, 7.83 processing FPS. One negative clip is insufficient to establish a false-alarm rate.

## Deferred / remaining

Camera connection explicitly deferred by user. No RTSP/ONVIF/webcam connection claim. Need independent campus clips, human-reviewed action labels, false-alerts/hour measurement, better fire data, and multi-camera load tests before deployment. Camera motion, quick sitting, sport/play, occlusion and track-ID changes can cause errors. No-alert is not proof of safety.

Source references and terms: [AIRTLab](https://github.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos), [URFD](https://fenix.ur.edu.pl/~mkepski/ds/uf.html), [fire example](https://github.com/pedbrgs/Fire-Detection), [experimental ONNX model](https://huggingface.co/fiacecson20/cctv-ai-fire-smoke). No private images/videos, credentials, database or weights are committed.
