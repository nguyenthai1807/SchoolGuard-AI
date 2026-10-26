"""Print a read-only, PII-free local migration inventory as JSON."""

import argparse
import json
import sys
from pathlib import Path

from schoolguard.config import Settings
from schoolguard.migration_inventory import inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Settings().runtime,
                        help="LH25 runtime directory; output contains counts only")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(inventory(args.runtime), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
