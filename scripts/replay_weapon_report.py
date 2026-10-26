"""Replay cached weapon observations through the current temporal engine."""

import argparse
import json
from pathlib import Path

from schoolguard.weapons import WeaponEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    for path in map(Path, args.reports):
        for clip in json.loads(path.read_text(encoding="utf-8")):
            engine, alerts = WeaponEngine(cooldown=0), []
            for sample in clip["samples"]:
                alerts.extend(engine.update(sample.get("weapons", []), sample["time"]))
            print(f"{clip['name']}: {len(alerts)} confirmed")
            for alert in alerts:
                print(f"  {alert['details']['confirmed_timestamp']:.2f}s "
                      f"peak={alert['confidence']:.3f} label={alert['details']['label']}")


if __name__ == "__main__":
    main()
