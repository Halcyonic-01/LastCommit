"""Area-weighted cell -> hobli / taluk / district, using the P2 weight matrices."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROC = ROOT / "data" / "processed"

LAYERS = {"panchayat": "hoblis", "block": "blocks", "district": "districts"}


def load_weights(layer: str, grid: str = "imd") -> pd.DataFrame:
    return pd.read_parquet(PROC / f"weights_{grid}_{LAYERS[layer]}.parquet")


def to_areas(cell_probs: pd.DataFrame, layer: str, grid: str = "imd",
            clip: tuple[float, float] | None = (0.0, 1.0)) -> pd.DataFrame:
    """Area-weighted mean over the cells an area actually overlaps.

    Weights are RENORMALISED over the cells present. One Karnataka cell (14.75N 74.0E) is
    sea-masked in IMD and absent from the grid; without renormalising, the two hoblis that
    reference it would silently have their probabilities scaled down by its weight.

    `clip` defaults to a probability's own [0, 1] range; pass the quantity's real bounds
    (or None) for anything else aggregated through here, e.g. onset_delay_weeks.
    """
    w = load_weights(layer, grid)
    w = w[w.cell_id.isin(cell_probs.index)]
    if w.empty:
        raise ValueError(f"no weight rows match the {len(cell_probs)} cells supplied")

    tot = w.groupby("area_id")["weight"].transform("sum")
    w = w.assign(weight=w["weight"] / tot.replace(0, np.nan))

    vals = cell_probs.loc[w["cell_id"]].to_numpy()
    out = (pd.DataFrame(vals * w["weight"].to_numpy()[:, None], columns=cell_probs.columns)
           .assign(area_id=w["area_id"].to_numpy())
           .groupby("area_id").sum())
    return out.clip(*clip) if clip else out


def coverage(layer: str, cells: list[str], grid: str = "imd") -> pd.Series:
    """Fraction of each area's weight that the supplied cells actually cover."""
    w = load_weights(layer, grid)
    have = w[w.cell_id.isin(cells)].groupby("area_id")["weight"].sum()
    allw = w.groupby("area_id")["weight"].sum()
    return (have / allw).reindex(allw.index).fillna(0.0)
