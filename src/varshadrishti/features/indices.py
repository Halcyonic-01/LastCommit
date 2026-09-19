"""Global climate indices as daily features: ENSO (ONI, Nino 3.4), IOD (DMI), MJO (RMM).

Every value is lagged to what a forecaster could actually have known that morning.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "indices"

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# NOAA publishes a month's ONI/DMI only after that month ends, and ONI is a 3-month
# running mean centred on it. Using month M inside month M is hindsight, not a forecast.
MONTHLY_LAG_DAYS = 32

MISSING = (-9999.0, -999.0, 999.0, 1e36)


def _monthly_table(path: Path) -> pd.Series:
    """NOAA PSL layout: a `first last` header, then `YEAR jan..dec`, then free-text trailer."""
    rows = []
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) != 13:
            continue  # trailer prose, or a short final row
        try:
            year, vals = int(parts[0]), [float(v) for v in parts[1:]]
        except ValueError:
            continue
        for m, v in enumerate(vals, start=1):
            rows.append((pd.Timestamp(year=year, month=m, day=1), v))
    s = pd.Series(dict(rows)).sort_index()
    return s.mask(s.isin(MISSING))


def _daily_from_monthly(s: pd.Series, name: str) -> pd.Series:
    """Hold each month's value flat, then shift by the publication lag."""
    daily = s.resample("D").ffill()
    daily.index = daily.index + pd.Timedelta(days=MONTHLY_LAG_DAYS)
    return daily.resample("D").ffill().rename(name)


def load_mjo() -> pd.DataFrame:
    """BoM RMM: daily RMM1, RMM2, phase 1-8, amplitude. Two header lines, then fixed columns."""
    rows = []
    for line in (RAW / "rmm_mjo.txt").read_text().splitlines()[2:]:
        p = line.split()
        if len(p) < 7:
            continue
        try:
            y, m, d = int(p[0]), int(p[1]), int(p[2])
            rmm1, rmm2, phase, amp = float(p[3]), float(p[4]), int(p[5]), float(p[6])
        except ValueError:
            continue
        rows.append((pd.Timestamp(y, m, d), rmm1, rmm2, phase, amp))

    df = pd.DataFrame(rows, columns=["date", "rmm1", "rmm2", "mjo_phase", "mjo_amp"]).set_index("date")
    df = df.mask(df.isin(MISSING))
    # amplitude < 1 means no coherent MJO — the phase number is then noise, not a signal
    df.loc[df["mjo_amp"] < 1.0, "mjo_phase"] = np.nan
    return df.sort_index()


def load_indices() -> pd.DataFrame:
    """One daily frame, union of all index dates. Gaps stay NaN — LightGBM splits on them."""
    parts = [
        _daily_from_monthly(_monthly_table(RAW / "oni.txt"), "oni"),
        _daily_from_monthly(_monthly_table(RAW / "dmi.txt"), "dmi"),
        _daily_from_monthly(_monthly_table(RAW / "nino34.txt"), "nino34"),
    ]
    out = pd.concat(parts, axis=1, sort=True).join(load_mjo(), how="outer")
    # Nino 3.4 ships as absolute SST; the anomaly is what carries the ENSO signal.
    out["nino34_anom"] = out["nino34"] - out.groupby(out.index.month)["nino34"].transform("mean")
    return out.sort_index()


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per column: first date, last date, and how much of the span is present."""
    return pd.DataFrame({
        "first": df.apply(lambda c: c.first_valid_index()),
        "last": df.apply(lambda c: c.last_valid_index()),
        "n": df.notna().sum(),
    })
