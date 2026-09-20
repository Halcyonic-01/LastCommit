"""Grid-cell -> polygon area weights, precomputed once so the nightly job is a matrix multiply."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from .boundaries import EQUAL_AREA, WGS84

# Grid origins are the dataset's own, not arbitrary: cell centres sit on these lattices.
GRIDS = {
    "imd": {"step": 0.25, "lat0": 6.5, "lon0": 66.5},
    "chirps": {"step": 0.05, "lat0": -49.975, "lon0": -179.975},
}


def grid_cells(name: str, bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Cells of `name`'s lattice covering bounds (minx, miny, maxx, maxy), as polygons."""
    spec = GRIDS[name]
    step = spec["step"]
    minx, miny, maxx, maxy = bounds

    # snap outward to the lattice so no polygon edge falls outside the cell set
    i0 = np.floor((miny - spec["lat0"]) / step)
    i1 = np.ceil((maxy - spec["lat0"]) / step)
    j0 = np.floor((minx - spec["lon0"]) / step)
    j1 = np.ceil((maxx - spec["lon0"]) / step)

    rows = []
    for i in range(int(i0), int(i1) + 1):
        lat = spec["lat0"] + i * step
        for j in range(int(j0), int(j1) + 1):
            lon = spec["lon0"] + j * step
            rows.append(
                {
                    "cell_id": f"{name}:{round(lat, 4)}:{round(lon, 4)}",
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    # cell centred on (lat, lon) — matches how both datasets index
                    "geometry": box(lon - step / 2, lat - step / 2, lon + step / 2, lat + step / 2),
                }
            )
    return gpd.GeoDataFrame(rows, crs=WGS84)


def area_weights(areas: gpd.GeoDataFrame, grid: str) -> pd.DataFrame:
    """Long-form (area_id, cell_id, weight). Weights per area_id sum to 1."""
    cells = grid_cells(grid, tuple(areas.total_bounds))

    a = areas[["area_id", "geometry"]].to_crs(EQUAL_AREA)
    c = cells[["cell_id", "lat", "lon", "geometry"]].to_crs(EQUAL_AREA)

    inter = gpd.overlay(a, c, how="intersection", keep_geom_type=True)
    inter["overlap_m2"] = inter.geometry.area
    inter = inter[inter["overlap_m2"] > 0]

    total = inter.groupby("area_id")["overlap_m2"].transform("sum")
    inter["weight"] = inter["overlap_m2"] / total

    out = inter[["area_id", "cell_id", "lat", "lon", "weight"]].copy()
    return out.sort_values(["area_id", "weight"], ascending=[True, False]).reset_index(drop=True)


def cells_per_area(weights: pd.DataFrame) -> pd.Series:
    return weights.groupby("area_id")["cell_id"].count()


def coverage(weights: pd.DataFrame, no_data_cells) -> pd.DataFrame:
    """Per area: cells that actually carry data, and the weight lost with the rest.

    `cells_per_area` counts every cell the matrix names, including ones the source never
    fills. Publishing that as `n_cells` claims coverage the forecast does not have, so
    anything user-facing counts with this instead.
    """
    dead = frozenset(no_data_cells)
    live = weights[~weights["cell_id"].isin(dead)]
    out = pd.DataFrame({
        "n_cells": live.groupby("area_id")["cell_id"].count(),
        "weight_lost": weights[weights["cell_id"].isin(dead)].groupby("area_id")["weight"].sum(),
    }, index=pd.Index(weights["area_id"].unique(), name="area_id"))
    return out.fillna({"n_cells": 0, "weight_lost": 0.0}).astype({"n_cells": int})


def aggregate(values: pd.Series, weights: pd.DataFrame) -> pd.Series:
    """Area-weighted mean of a per-cell series, indexed by cell_id -> per area_id."""
    w = weights[weights["cell_id"].isin(values.index)].copy()
    w["v"] = w["cell_id"].map(values)
    # renormalise in case some cells are missing (sea, no data)
    w["w"] = w.groupby("area_id")["weight"].transform(lambda s: s / s.sum())
    return w.groupby("area_id").apply(lambda d: float((d["v"] * d["w"]).sum()))


def save(weights: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    weights.to_parquet(path, index=False, compression="zstd")
    return path.stat().st_size
