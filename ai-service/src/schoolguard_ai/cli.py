"""Command line entry point for BE-1; no database or user management owned here."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="SchoolGuard AI — phân tích xâm nhập vùng cấm")
    parser.add_argument("--video", required=True, type=Path, help="Video local (MP4/AVI/MOV)")
    parser.add_argument("--config", type=Path, default=Path("configs/demo.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--no-video", action="store_true", help="Chỉ xuất metadata và ảnh cảnh báo")
    args = parser.parse_args()
    try:
        config = Config.load(args.config)
        from .worker import process_video

        summary = process_video(args.video, config, args.output, save_video=not args.no_video)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as error:
        parser.exit(1, f"SchoolGuard AI: {error}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
