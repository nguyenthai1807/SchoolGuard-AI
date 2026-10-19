"""Extract local inspection frames; never modify or upload the original dataset."""

import json

import cv2
import numpy as np

from schoolguard.config import Settings

settings = Settings()
output = settings.runtime / "evaluation"
output.mkdir(parents=True, exist_ok=True)
tiles, records = [], []
for scene in range(1, 14):
    path = next(
        iter(sorted((settings.data_root / "training/videos").glob(f"{scene:02}_*.avi"))), None
    )
    if path is None:
        continue
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    index = int(2 * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        continue
    name = f"scene-{scene:02}.jpg"
    cv2.imwrite(str(output / name), frame)
    tile = cv2.resize(frame, (428, 240))
    cv2.putText(
        tile,
        f"SCENE {scene:02} | {path.name} | frame {index}",
        (8, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 0, 255),
        1,
    )
    tiles.append(tile)
    records.append(
        {
            "scene": scene,
            "source": str(path.relative_to(settings.data_root)),
            "frame": index,
            "fps": fps,
            "image": name,
            "width": frame.shape[1],
            "height": frame.shape[0],
        }
    )
while len(tiles) % 3:
    tiles.append(np.zeros_like(tiles[0]))
montage = np.vstack([np.hstack(tiles[i : i + 3]) for i in range(0, len(tiles), 3)])
cv2.imwrite(str(output / "contact.jpg"), montage)
(output / "samples.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
print(json.dumps(records, indent=2))
