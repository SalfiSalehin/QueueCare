"""Choose which trained version the API serves.

    python -m ml.training.promote lgbm-quantile-s42-1a2b3c4d

Writes `ml/models/ACTIVE`. Promotion is a deliberate step: training never changes what is served.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def promote(version: str, root: Path = Path("ml/models")) -> Path:
    bundle = root / version / "bundle.json"
    if not bundle.is_file():
        raise SystemExit(f"no trained model at {bundle.parent}")
    data = json.loads(bundle.read_text())
    if data.get("version") != version:
        raise SystemExit("bundle version does not match its directory")
    pointer = root / "ACTIVE"
    pointer.write_text(version + "\n")
    return pointer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path("ml/models"))
    args = parser.parse_args()
    print(f"active model is now {args.version} ({promote(args.version, args.root)})")


if __name__ == "__main__":
    main()
