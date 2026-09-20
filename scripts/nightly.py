"""The nightly job: observations + NWP -> blended probabilities -> advisories -> JSON.

  fetch NWP (cached) -> fetch observations (cached) -> live features -> P_stat
  -> P_nwp from ensemble member fractions -> blend -> area-weighted aggregation
  -> CRIDA rules per area -> write the contract files

`--offline` runs the whole thing from cache and touches no network, which is how the
acceptance test runs it. Every response is cached in the repo so a demo survives an
Open-Meteo outage, and so that a rerun is byte-reproducible.
"""

import argparse
import json
import sys
import time
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

from varshadrishti import contract as c  # noqa: E402
from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.features.climatology import CLIM_COLS, FoldClimatology  # noqa: E402
from varshadrishti.pipeline import aggregate as A  # noqa: E402
from varshadrishti.pipeline import blend as BL  # noqa: E402
from varshadrishti.pipeline import infer as I  # noqa: E402
from varshadrishti.pipeline import nwp as N  # noqa: E402
from varshadrishti.pipeline import observations as O  # noqa: E402
from varshadrishti.rules import engine as E  # noqa: E402

PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"
LEADS = ("w1", "w2", "w3", "w4")

# Skill is not uniform in time (P5b). A September dry-spell card must not carry the same
# authority as a July one, so the contract's `confidence` is set from the month.
STRONG_MONTHS = {7, 8}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def month_confidence(month: int, weak_target: bool) -> str:
    if month in STRONG_MONTHS:
        return "medium" if weak_target else "high"
    return "low" if weak_target else "medium"


def build_cell_probabilities(as_of: str, offline: bool):
    """-> (blended cell x slot frame, source map, diagnostics)."""
    w = pd.read_parquet(PROC / "weights_imd_hoblis.parquet")
    cells = sorted(set(w.cell_id))

    log("observations")
    cached_obs = O.CACHE / f"{as_of}.json"
    if offline and cached_obs.exists():
        # "offline from cache" means exactly that — the day's own cached observations,
        # so an acceptance run reproduces the live run rather than a different one.
        obs = O.fetch_recent(cells, as_of, use_cache=True, log=log)
        log("  from observation cache")
    elif offline:
        from varshadrishti.data.rainfall import load_imd
        pad = 0.3
        b = (w.lon.min() - pad, w.lat.min() - pad, w.lon.max() + pad, w.lat.max() + pad)
        yr = pd.Timestamp(as_of).year
        rain = load_imd(max(1991, yr - 1), min(2024, yr), bounds=b)
        obs = O.from_imd(rain[[x for x in cells if x in rain.columns]], as_of)
        log("  replay from the IMD archive (no cached observations for this date)")
    else:
        obs = O.fetch_recent(cells, as_of, log=log)
    log(f"  {obs.shape[0]} days x {obs.shape[1]} cells")

    # Climatology and the onset bar come from a frozen 280 KB table, not the 825 MB IMD
    # archive — a CI runner has the repo, not the archive. Regenerate with
    # scripts/export_inference_tables.py whenever the training data changes.
    tab = pd.read_parquet(PROC / "inference_tables.parquet")
    thresh = tab.groupby("cell_id")["onset_threshold_mm"].first()

    log("climatology (full record — inference has no held-out year)")
    sday = (pd.Timestamp(as_of) - pd.Timestamp(pd.Timestamp(as_of).year, *L.SEASON_START_MD)).days
    if sday not in set(tab["sday"]):
        near = int(tab["sday"].iloc[(tab["sday"] - sday).abs().argsort().iloc[0]])
        log(f"  {as_of} is outside Jun-Sep (season day {sday}); using day {near}")
        sday = near
    clim = (tab[tab.sday == sday].drop_duplicates("cell_id")
            .drop(columns=["sday", "onset_threshold_mm"]))

    log("statistical model")
    row = I.live_features(obs, as_of, thresh, clim)
    stat = I.statistical(row)

    # Today minus this area's climatological onset date, in weeks (schema's own
    # definition). Only meaningful before onset has actually happened -- deep in the
    # season this keeps growing and stops meaning "how late is onset running", so the
    # caller only publishes it while onset_status == "pre_monsoon".
    onset_delay = ((row.set_index("cell_id")["doy"] - row.set_index("cell_id")["clim_onset_doy"])
                  / 7.0).to_frame("onset_delay_weeks")

    log("NWP ensemble member fractions")
    parts = []
    for model in ("ec46", "gefs"):
        try:
            parts.append(N.probabilities(model, as_of, thresh))
        except FileNotFoundError as exc:
            log(f"  {model}: {exc}")
    nwp_p = (sum(parts) / len(parts)) if parts else pd.DataFrame(index=stat.index)
    if len(parts) == 2:
        log("  averaged EC46 and GEFS — two independent models")

    blended, sources = BL.blend(stat, nwp_p)
    diag = {
        "n_cells": int(len(blended)),
        "slots_without_a_model": I.missing_models(),
        "live_feature_coverage": I.feature_coverage(row),
        "blend_sources": sources,
        "nwp_models": ["ec46", "gefs"][: len(parts)],
    }
    return blended, diag, thresh, onset_delay


def run_one_day(as_of: str, offline: bool, out: Path, pilot_only: bool = False,
                model_version: str = "1.0.0-live") -> tuple[dict, dict]:
    """One day, start to finish: fetch/replay -> model -> areas -> contract files.

    Shared by the live nightly job and scripts/hindcast.py, so a hindcast run goes
    through the exact same code a real night does -- no separate, unverified path.
    Returns (file sizes, diagnostics) so a caller can log or aggregate across days.
    """
    t0 = time.time()
    log(f"nightly run for {as_of} (offline={offline})")
    cells_df, diag, thresh, onset_delay = build_cell_probabilities(as_of, offline)

    log("area-weighted aggregation")
    per_area, delay_by_area = {}, {}
    for layer in ("district", "block", "panchayat"):
        per_area[layer] = A.to_areas(cells_df, layer)
        # Schema's own bounds, not a probability's [0, 1] -- see aggregate.to_areas.
        delay_by_area[layer] = A.to_areas(onset_delay, layer, clip=(-8.0, 12.0))
        log(f"  {layer}: {len(per_area[layer])}")

    sys.path.insert(0, str(ROOT / "scripts"))
    from make_mock_forecast import areas_from_geo, real_skill  # noqa: PLC0415

    log("assembling areas + CRIDA advisories")
    packs = E.load_rules()
    month = pd.Timestamp(as_of).month
    areas = []
    for area in areas_from_geo(pilot_only):
        tab = per_area.get(area.level)
        if tab is None or area.area_id not in tab.index:
            continue
        r = tab.loc[area.area_id]

        def ls(ev):
            return c.leadset(*(float(r.get(f"{ev}_{w}", np.nan)) if pd.notna(r.get(f"{ev}_{w}", np.nan))
                               else 0.0 for w in LEADS))

        area.p_onset = ls("p_onset")
        area.p_false_onset = ls("p_false_onset")
        area.p_dry7 = ls("p_dry7")
        area.p_dry14 = ls("p_dry14")
        area.p_heavy = ls("p_heavy")
        area.onset_status = "in_season" if 6 <= month <= 9 else "pre_monsoon"
        # Real, area-weighted, clipped to the schema's own [-8, 12] week bounds -- the
        # same definition the schema documents, not gated on onset_status, which is a
        # coarse Jun-Sep calendar bucket rather than a per-area onset-happened flag.
        dtab = delay_by_area.get(area.level)
        area.onset_delay_weeks = (
            float(dtab.loc[area.area_id, "onset_delay_weeks"])
            if dtab is not None and area.area_id in dtab.index else None
        )
        # dry spell is the weak target (negative in 10/34 seasons); say so in the contract
        area.confidence = month_confidence(month, weak_target=area.p_dry7["w1"] >= 0.25)
        area.advisories = E.evaluate({
            "district_en": area.district_en, "p_onset": area.p_onset,
            "p_false_onset": area.p_false_onset, "p_dry7": area.p_dry7,
            "p_dry14": area.p_dry14, "p_heavy": area.p_heavy,
            "onset_delay_weeks": area.onset_delay_weeks or 0.0,
        }, packs=packs)
        areas.append(area)
    log(f"  {len(areas)} areas with advisories")

    meta = c.make_meta(valid_from=date.fromisoformat(as_of), model_version=model_version,
                       state="karnataka", code_system="kgis", is_mock=False)
    # The weight caveat travels with every file. `skill` and `provenance` are both closed
    # to extra keys by the frozen schema, but provenance.nwp allows them — which is the
    # right home anyway, since it is a statement about the NWP contribution.
    provenance = {
        "nwp": {
            "source": "ECMWF EC46 + NOAA GEFS via Open-Meteo",
            "members": 81,
            "run_date": as_of,
            "weight_provenance": BL.WEIGHT_PROVENANCE,
        },
        "statistical": {
            "source": "XGBoost on IMD 0.25deg 1991-2024", "seasons": 34,
            "validation": "chronological split — train 1991-2015, val 2016-2019, test 2020-2024",
            "excluded_features": sorted(__import__("varshadrishti.model.train",
                                                   fromlist=["EXCLUDED"]).EXCLUDED),
            "live_feature_coverage": diag["live_feature_coverage"],
        },
        "blend_weights": c.leadset(*(BL.NWP_WEIGHT[w] for w in LEADS)),
        "calibration": ("none on the statistical model — the XGBoost boosters emit raw "
                        "binary:logistic probabilities with a validation-tuned decision "
                        "threshold, not an out-of-fold isotonic map; the linear pool is "
                        "NOT recalibrated either — see blend.beta_transform"),
    }
    # PS 26086 asks for global boundary conditions paired with regional data. All three
    # indices are ingested; each acts where it measurably works — MJO in the model,
    # ENSO as seasonal context, IOD reported with its own null result.
    from varshadrishti.pipeline import teleconnection as TC  # noqa: PLC0415
    tele = TC.current(as_of)
    if tele:
        provenance["teleconnection"] = tele
        log(f"  ENSO {tele['enso_phase']} (ONI {tele['oni']}) — "
            f"model reliability {tele['model_reliability']}")
    skill = real_skill() or {}

    # the same builder split_forecast.py uses, so a web build cannot overwrite these
    # files with differently-worded ones
    summary = c.provenance_summary({"provenance": provenance})
    sizes = c.emit_all(meta, provenance, skill, areas, out_dir=out,
                       provenance_summary=summary)
    diag["seconds"] = round(time.time() - t0, 1)
    log(f"wrote {len(sizes)} files in {time.time() - t0:.0f}s | "
        f"largest area file {max(v for k, v in sizes.items() if k.startswith('area/'))} B")
    return sizes, diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--offline", action="store_true", help="cache only, no network")
    ap.add_argument("--out", default=str(ROOT / "forecast"))
    ap.add_argument("--pilot-only", action="store_true")
    a = ap.parse_args()

    sizes, diag = run_one_day(a.as_of, a.offline, Path(a.out), a.pilot_only)
    (MODELS / "last_run.json").write_text(json.dumps(
        {"as_of": a.as_of, "generated_at": datetime.now(timezone.utc).isoformat(), **diag},
        indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
