"""Loading the synthetic dataset and splitting it chronologically."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.preprocessing.features import FEATURE_COLUMNS, TARGET


@dataclass(frozen=True)
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame

    @property
    def summary(self) -> dict[str, dict[str, int]]:
        def part(df: pd.DataFrame) -> dict[str, int]:
            return {"rows": int(len(df)), "first_day": int(df["day_index"].min()), "last_day": int(df["day_index"].max())}
        return {"train": part(self.train), "val": part(self.val), "test": part(self.test)}


def load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip")
    missing = [c for c in (*FEATURE_COLUMNS, TARGET, "day_index", "doctor_id") if c not in df.columns]
    if missing:
        raise ValueError(f"dataset is missing columns: {missing}")
    if not bool(df["is_synthetic"].all()):
        raise ValueError("refusing to train on rows not marked is_synthetic")
    if df[list(FEATURE_COLUMNS) + [TARGET]].isna().any().any():
        raise ValueError("dataset contains missing values")
    return df


def temporal_split(df: pd.DataFrame, train_frac: float = 0.70, val_frac: float = 0.15) -> Split:
    """Split by WORKING DAY, oldest to newest: train, then validation, then test.

    Visits on the same day share the same queue, so a random row-level split would put near-copies of
    the same situation in both train and test (leakage). Splitting on whole days, in time order, mirrors
    how the model is used: trained on the past, asked about the future.
    """
    days = sorted(df["day_index"].unique())
    if len(days) < 10:
        raise ValueError("need at least 10 days to split")
    i1, i2 = int(len(days) * train_frac), int(len(days) * (train_frac + val_frac))
    train_days, val_days, test_days = set(days[:i1]), set(days[i1:i2]), set(days[i2:])
    split = Split(
        train=df[df["day_index"].isin(train_days)].reset_index(drop=True),
        val=df[df["day_index"].isin(val_days)].reset_index(drop=True),
        test=df[df["day_index"].isin(test_days)].reset_index(drop=True),
    )
    assert split.train["day_index"].max() < split.val["day_index"].min() <= split.val["day_index"].max() \
        < split.test["day_index"].min(), "splits must be strictly chronological"
    return split
