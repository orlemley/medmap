from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = root / "runs" / stamp
    suffix = 1
    while run.exists():
        run = root / "runs" / f"{stamp}-{suffix}"
        suffix += 1
    run.mkdir(parents=True, exist_ok=False)
    return run


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def percentile_score(values: pd.Series) -> pd.Series:
    s = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    mask = s.notna()
    if not mask.any():
        return out.fillna(0.0)
    if s[mask].nunique(dropna=True) <= 1:
        out.loc[mask] = 0.5
    else:
        out.loc[mask] = s[mask].rank(method="average", pct=True)
    return out.fillna(0.0).clip(0, 1)


def weighted_mean(frame: pd.DataFrame, pairs: list[tuple[str, float]]) -> pd.Series:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        raise ValueError("Score weights must sum to a positive value")
    result = pd.Series(0.0, index=frame.index)
    for column, weight in pairs:
        result = result + numeric(frame, column, 0.0).clip(0, 1) * weight
    return (result / total_weight).clip(0, 1)
