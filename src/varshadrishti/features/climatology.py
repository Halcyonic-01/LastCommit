"""Climatology computed from training years only, rebuilt for every LOYO fold.

The previous design stored one leave-one-year-out climatology per ROW: a 1995 row carried
climatology from every season but 1995. Under a fold holding out 2010 that row still saw
2010, so ~1/33 of the held-out year reached the training set through a feature.

Here the fold owns the climatology. For fold H every row - training and test alike - gets
climatology built from years != H, which is the ordinary "fit preprocessing on train, apply
to both" rule. Ingredients are tiny (34 x 122 x 323 floats), so a fold costs a subtraction
and an integer lookup rather than a recompute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import labels as L

CLIM_COLS = ["clim_rain_doy", "clim_dryday_doy", "clim_onset_doy",
             "clim_first_cand_doy", "clim_false_rate", "onset_doy_anom"]


class FoldClimatology:
    """Precomputed per-year ingredients; ask it for any fold's climatology."""

    def __init__(self, rain: pd.DataFrame, years: list[int], onset: pd.DataFrame,
                 rows: pd.DataFrame):
        self.years = list(years)
        self.cells = list(rain.columns)
        self.n_sday = 1 + max(
            (L._season_slice(rain, y).index[-1] - pd.Timestamp(y, *L.SEASON_START_MD)).days
            for y in years)

        # (year, sday, cell) cubes — 34 x 122 x 323 floats is 11 MB, so keep them all
        shape = (len(years), self.n_sday, len(self.cells))
        self.rain_cube = np.full(shape, np.nan, dtype=np.float32)
        self.dry_cube = np.full(shape, np.nan, dtype=np.float32)
        for i, y in enumerate(years):
            s = L._season_slice(rain, y)
            sd = (s.index - pd.Timestamp(y, *L.SEASON_START_MD)).days.to_numpy()
            self.rain_cube[i, sd, :] = s.to_numpy(dtype=np.float32)
            self.dry_cube[i, sd, :] = (s.to_numpy() < L.RAINY_DAY_MM).astype(np.float32)

        # per (year, cell) onset statistics
        cell_ix = {c: j for j, c in enumerate(self.cells)}
        year_ix = {y: i for i, y in enumerate(years)}
        self.onset_cube = np.full((len(years), len(self.cells), 3), np.nan, dtype=np.float32)
        for r in onset.itertuples(index=False):
            i, j = year_ix.get(r.year), cell_ix.get(r.cell_id)
            if i is None or j is None:
                continue
            self.onset_cube[i, j] = (r.onset_doy, r.first_cand_doy, float(r.first_cand_failed))

        # row -> (sday, cell) integer positions, resolved once
        self.row_sday = rows["sday"].to_numpy(np.int32)
        self.row_cell = pd.Index(self.cells).get_indexer(rows["cell_id"]).astype(np.int32)
        self.row_doy = rows["doy"].to_numpy(np.float32)
        if (self.row_cell < 0).any():
            raise KeyError("feature rows reference a cell absent from the rainfall frame")

    def _mean_excluding(self, cube: np.ndarray, hold: int) -> np.ndarray:
        """Mean over the year axis with one year dropped, NaN-safe."""
        keep = np.ones(len(self.years), bool)
        keep[self.years.index(hold)] = False
        sub = cube[keep]
        with np.errstate(invalid="ignore"):
            return np.nanmean(sub, axis=0)

    def for_inference(self) -> pd.DataFrame:
        """Climatology over ALL years — what the shipped model must be trained on.

        At inference there is no held-out year, so the nightly job computes climatology
        from the whole record. Training the final model on fold climatology instead would
        leave live features systematically offset from the ones it learned.
        """
        return self._assemble(np.nanmean(self.rain_cube, axis=0),
                              np.nanmean(self.dry_cube, axis=0),
                              np.nanmean(self.onset_cube, axis=0))

    def _assemble(self, rain_m, dry_m, onset_m) -> pd.DataFrame:
        sd, ce = self.row_sday, self.row_cell
        first_cand = onset_m[ce, 1]
        return pd.DataFrame({
            "clim_rain_doy": rain_m[sd, ce],
            "clim_dryday_doy": dry_m[sd, ce],
            "clim_onset_doy": onset_m[ce, 0],
            "clim_first_cand_doy": first_cand,
            "clim_false_rate": onset_m[ce, 2],
            "onset_doy_anom": self.row_doy - first_cand,
        })

    def for_fold(self, hold: int) -> pd.DataFrame:
        """Climatology columns for every row, built from years != hold."""
        return self._assemble(self._mean_excluding(self.rain_cube, hold),
                              self._mean_excluding(self.dry_cube, hold),
                              self._mean_excluding(self.onset_cube, hold))


def reference_from_fold(df: pd.DataFrame, target: str, hold: int, years: list[int],
                        window: int = 7) -> np.ndarray:
    """Climatological base rate of `target` per (cell, sday), from years != hold only.

    Used as the BSS reference. The bar we clear must not have seen the year it grades.
    """
    tr = df[df.year != hold]
    tab = tr.groupby(["cell_id", "sday"])[target].agg(["sum", "count"])
    w = 2 * window + 1
    num = tab["sum"].unstack("cell_id").rolling(w, center=True, min_periods=1).sum()
    den = tab["count"].unstack("cell_id").rolling(w, center=True, min_periods=1).sum()
    rate = num / den.replace(0, np.nan)
    vals = rate.to_numpy()[
        rate.index.get_indexer(df["sday"]), rate.columns.get_indexer(df["cell_id"])
    ]
    return np.where(np.isnan(vals), tr[target].mean(), vals)
