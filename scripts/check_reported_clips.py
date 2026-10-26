"""Read-only source discovery and sampled real-model checks for the reported clips.

Outputs are isolated under runtime; counts are observations, not accuracy scores.
"""
import argparse
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from schoolguard.config import Settings
from schoolguard.detector import PersonDetector
from schoolguard.media import Reader
from schoolguard.schemas import JobRequest
from schoolguard.worker import draw
from schoolguard.weapons import WeaponDetector, WeaponEngine, draw_weapons

NAMES = ['violent-002', 'violent-003', 'violent-004', 'violent-005', 'violent-006',
         'non-violent-004', 'non-violent-005', 'wildfire', 'house6.mp4',
         '01_0014', '01_0015', '01_0016', '01_00540']


def sources(settings):
    with sqlite3.connect(f'file:{settings.runtime / "schoolguard.sqlite3"}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute('SELECT * FROM sources')
                if r['name'].removeprefix('[research] ') in NAMES]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', default='yolo11n-pose')
    parser.add_argument('--image-size', type=int, choices=(640, 960), default=640)
    parser.add_argument('--weapons', action='store_true')
    parser.add_argument('--names', nargs='*')
    parser.add_argument('--sample-period', type=float, default=0,
                        help='Seconds between samples; 0 selects first/middle/last.')
    args = parser.parse_args()
    settings = Settings(start_worker=False)
    output = settings.runtime / 'regression-20261023' / args.out
    output.mkdir(parents=True, exist_ok=False)
    cv2.setNumThreads(2)
    report = []
    for source in sources(settings):
        name = source['name'].removeprefix('[research] ').replace('.mp4', '')
        if args.names and name not in args.names:
            continue
        config = JobRequest(source_id=source['id'], model=args.model,
                            image_size=args.image_size)
        detector = PersonDetector(settings, config)
        weapon_detector = WeaponDetector(settings, config) if args.weapons else None
        weapon_engine = WeaponEngine(cooldown=0) if weapon_detector else None
        weapon_alerts = []
        rows, tiles = [], []
        with Reader(source['path'], source['kind']) as reader:
            selected = ({0, reader.count // 2, reader.count - 1}
                        if not args.sample_period else
                        set(range(0, reader.count,
                                  max(1, round(reader.fps * args.sample_period)))))
            for index in range(reader.count):
                frame = reader.read()
                if index not in selected:
                    continue
                # These are independent snapshots, not consecutive tracker frames.
                detector.reset_tracking()
                detections = detector(frame)
                weapons = weapon_detector(frame, detections) if weapon_detector else []
                if weapon_engine:
                    weapon_alerts.extend(weapon_engine.update(weapons, index / reader.fps))
                rows.append({'frame': index, 'time': index / reader.fps, 'count': len(detections),
                             'detections': detections, 'weapons': weapons})
                preview = cv2.resize(draw(frame, detections, [], set(), False), (640, 360))
                draw_weapons(preview, weapons)
                cv2.putText(preview, f'{source["name"]} {index/reader.fps:.2f}s count={len(detections)}',
                            (8, 25), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 2)
                tiles.append(preview)
        cv2.imwrite(str(output / f'{name}.jpg'), np.vstack(tiles))
        report.append({'name': name, 'model': args.model, 'image_size': args.image_size,
                       'samples': rows, 'weapon_alerts': weapon_alerts})
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(name, [r['count'] for r in rows], flush=True)


if __name__ == '__main__':
    main()
