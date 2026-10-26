# LH25 browser AI: experimental migration

Decision: inference should run on the visitor's device without an installer.
The existing Python application and public Store remain unchanged.

## Implemented, not yet published

- Isolated browser-client page: local video or permission-based webcam.
- YOLO26n exported at 320 px, FP32 ONNX, opset 17. Output [1,84,2100].
- ONNX Runtime Web 1.30.0, WASM single-thread inside a dedicated worker.
- Letterbox preprocessing, COCO person filtering, NMS, frame count and latency.
- No uploads, persistent face storage, analytics, Telegram secrets, or payments.
- Counts are per sampled frame, never unique identities or exhaustive video totals.

## Local preview

Run `python scripts/build_browser_lab.py` using the project's virtual environment.
Serve only `runtime/browser-lab`, never the repository root:

```powershell
.\.venv\Scripts\python.exe -m http.server 8773 --bind 127.0.0.1 --directory runtime/browser-lab
```

Open http://127.0.0.1:8773. Download AI, choose video or allow webcam, then analyze.
Loopback is a secure context; external deployment must use HTTPS.
Development dependencies are tracked separately under tools/browser-runtime.
Model export requires onnx/onnxruntime/onnxscript in the build environment.

## Release gates still open

Browser smoke check passed: actual WASM model load and inference on a generated
black MP4 returned zero persons; first observed frame was 121 ms on this machine.
This is not a detector accuracy or representative speed benchmark. Four Node
decoder/NMS tests passed. No user camera permission was requested during tests.

Real-video accuracy and mobile performance, long-running camera tests,
video seek/pause/restart tests, detector comparison with Python, model/runtime
license compliance and source availability before public distribution.
Google login still requires a configured web client and browser integration.
Payment verification, entitlements, admin data and Telegram dispatch remain
trusted backend responsibilities. Never trust client counts for billing or
store bot/payment credentials in browser assets.

Model downloads consume hosting bandwidth: client-side inference does not
guarantee the entire service is free at unlimited traffic. A downloadable model
cannot be kept secret or securely gated by frontend JavaScript alone.
Browser IP/RTSP cameras and background/screen-off monitoring are not supported.
Fall, fire, weapons, tracking and face features have not been ported or validated.
