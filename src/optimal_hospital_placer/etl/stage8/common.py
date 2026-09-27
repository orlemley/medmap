from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_dir(out_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = out_root / "runs" / f"{stamp}-{uuid.uuid4().hex[:8]}"
    run.mkdir(parents=True, exist_ok=False)
    return run


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[name], errors="coerce").fillna(default).astype(float)


def clip01(value) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.astype(float).clip(0.0, 1.0)
    return pd.Series(value, dtype="float64").clip(0.0, 1.0)


def percentile_score(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if not s.notna().any():
        return pd.Series(0.0, index=series.index)
    # pct=True returns 0..1-ish ranks; subtract half a bin so singleton data does not become 1.0.
    rank = s.rank(method="average", pct=True)
    return rank.fillna(0.0).clip(0.0, 1.0)


def sat(series: pd.Series, scale: float) -> pd.Series:
    """Simple saturating 0..1 transform: x/(x+scale)."""
    x = pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=0.0)
    if scale <= 0:
        return pd.Series(1.0, index=x.index)
    return (x / (x + float(scale))).clip(0.0, 1.0)
