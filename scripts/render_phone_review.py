"""Render full-size numbered proposals for human review; never changes labels."""

from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime/phone-training"


def main() -> None:
    output = DATA / "review"
    output.mkdir(exist_ok=True)
    for image_path in sorted((DATA / "images/test").glob("*.jpg")):
        image = cv2.imread(str(image_path))
        if image is None:
            raise RuntimeError(f"Could not read {image_path}")
        height, width = image.shape[:2]
        rows = (DATA / "labels/test" / f"{image_path.stem}.txt").read_text().splitlines()
        for index, row in enumerate(rows):
            cls, x, y, box_width, box_height = map(float, row.split())
            x1 = round((x - box_width / 2) * width)
            y1 = round((y - box_height / 2) * height)
            x2 = round((x + box_width / 2) * width)
            y2 = round((y + box_height / 2) * height)
            color = (0, 255, 255) if cls == 0 else (255, 150, 0)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(image, f"{index}: {int(cls)}", (max(0, x1), max(20, y1 - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(image, f"{index}: {int(cls)}", (max(0, x1), max(20, y1 - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
        cv2.imwrite(str(output / image_path.name), image)
    print(f"Rendered {len(list(output.glob('*.jpg')))} test images to {output}")


if __name__ == "__main__":
    main()
