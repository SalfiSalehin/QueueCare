"""Reference distributions for drift monitoring: what the training data looked like.

    python -m ml.monitoring.reference lgbm-quantile-s42-4dbad111

New training runs write `reference.json` automatically. For a model trained before this existed, this
command rebuilds it by regenerating the (deterministic, synthetic) training data from the seed recorded
in the bundle and REFUSES to write anything unless the regenerated data hashes to the SHA-256 recorded at
training time, so the reference provably describes the data the model was trained on.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from ml.data_generation.generate_dataset import to_csv_bytes
from ml.data_generation.simulator import generate
from ml.monitoring.drift import build_feature_reference
from ml.preprocessing.features import FEATURE_COLUMNS

TRAIN_FRACTION = 0.70      # must match ml.training.data.temporal_split
DEFAULT_DAYS, DEFAULT_DOCTORS = 200, 12


def build_reference(columns: dict[str, Sequence[float]], *, version: str, dataset_sha256: str) -> dict:
    n = len(next(iter(columns.values())))
    return {"version": version, "synthetic": True, "dataset_sha256": dataset_sha256, "n_rows": n,
            "features": {name: build_feature_reference(columns[name]) for name in FEATURE_COLUMNS}}


def write_reference(directory: Path, reference: dict) -> Path:
    path = Path(directory) / "reference.json"
    path.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n")
    return path


def rebuild_from_bundle(directory: Path) -> dict:
    bundle = json.loads((Path(directory) / "bundle.json").read_text())
    dataset = bundle.get("dataset", {})
    seed = int(dataset.get("seed", bundle["seed"]))
    days, doctors = int(dataset.get("days", DEFAULT_DAYS)), int(dataset.get("doctors", DEFAULT_DOCTORS))
    rows = generate(seed=seed, n_doctors=doctors, n_days=days)
    digest = hashlib.sha256(to_csv_bytes(rows)).hexdigest()
    if digest != bundle["dataset_sha256"]:
        raise SystemExit("regenerated data does not match the training data hash; not writing a reference")
    day_ids = sorted({int(r["day_index"]) for r in rows})
    train_days = set(day_ids[: int(len(day_ids) * TRAIN_FRACTION)])
    train = [r for r in rows if int(r["day_index"]) in train_days]
    columns = {name: [float(r[name]) for r in train] for name in FEATURE_COLUMNS}
    return build_reference(columns, version=bundle["version"], dataset_sha256=digest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path("ml/models"))
    args = parser.parse_args()
    directory = args.root / args.version
    path = write_reference(directory, rebuild_from_bundle(directory))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
