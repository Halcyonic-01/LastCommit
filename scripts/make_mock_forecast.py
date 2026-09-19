"""Generate schema-valid mock forecast files so the PWA can be built before the model exists.

Uses REAL Karnataka geography from P2 (KGIS ids, names, centroids, cell counts) with invented
probabilities. P6 swaps the numbers for model output; nothing about the shape changes.

--fixture falls back to hard-coded MOCK-* areas so the contract tests run without geo data.
"""

import argparse
import json
import hashlib
import sys
import warnings
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
warnings.filterwarnings("ignore")

from varshadrishti import contract as c  # noqa: E402
from varshadrishti.rules import engine as E  # noqa: E402

PILOT_DISTRICTS = {"TUMAKURU", "CHITRADURGA", "CHIKKABALLAPURA",
                   "DAVANAGERE", "KOLARA"}

ADVISORY = {
    "rule_id": "tumakuru.groundnut.delayed_onset_4w",
    "crop": "groundnut",
    "stage": "pre_sowing",
    "severity": "warn",
    "action_en": "Switch from groundnut to horse gram or foxtail millet",
    "action_kn": "ಶೇಂಗಾ ಬದಲು ಹುರುಳಿ ಅಥವಾ ನವಣೆ ಬಿತ್ತನೆ ಮಾಡಿ",
    "confidence_word_en": "likely",
    "confidence_word_kn": "ಸಾಧ್ಯತೆ ಹೆಚ್ಚು",
    "source": {
        "doc": "ICAR-CRIDA district agriculture contingency plan",
        "table": "2.1.1",
        "district": "Tumakuru",
    },
}

FIXTURE = [
    ("MOCK-BLK-Tumakuru", "Tumakuru", "ತುಮಕೂರು", "block", None, [77.101, 13.342], 9),
    ("MOCK-BLK-Tiptur", "Tiptur", "ತಿಪಟೂರು", "block", None, [76.477, 13.256], 9),
    ("MOCK-HOB-Gubbi", "Gubbi", "ಗುಬ್ಬಿ", "panchayat", "MOCK-BLK-Tumakuru", [76.940, 13.312], 3),
]


def real_skill():
    """Measured leave-one-year-out skill from P5, if it has been run.

    The probabilities here stay invented, but the honesty numbers must not be: the
    advisory horizon is read off where BSS actually stops being positive rather than
    asserted as 2 weeks.
    """
    f = Path(__file__).resolve().parent.parent / "models" / "metrics.json"
    if not f.exists():
        return None
    m = json.loads(f.read_text())
    # One quantity across the four leads. Mixing dry-spell skill at w1/w2 with onset skill
    # at w3/w4 would publish a "skill by lead week" series that is not of anything.
    lead = {"w1": "y_dry7_7", "w2": "y_dry7_14", "w3": "y_dry7_21", "w4": "y_dry7_28"}
    if not all(k in m for k in lead.values()):
        return None
    bss = {w: round(float(m[t]["bss"]), 4) for w, t in lead.items()}
    # The horizon is where skill is DEMONSTRABLE, not where the point estimate is
    # positive. y_dry7_28 scores +0.0155 with a 95% interval of (-0.010, 0.038): that
    # is not skill, it is a number. Advise only while the interval clears zero.
    horizon = 0
    for w in ("w1", "w2", "w3", "w4"):
        lo = float(m[lead[w]].get("bss_ci95", [bss[w], bss[w]])[0])
        if lo <= 0:
            break
        horizon += 1
    return {
        "bss": bss,
        "reference": "per-cell, per-date climatology 1991-2024, leave-one-year-out",
        "roc_auc": round(float(m["y_dry7_7"]["roc_auc"]), 4),
        "advisory_horizon_weeks": max(1, horizon),
    }


def pseudo(key):
    """Deterministic pseudo-values keyed on the area id — byte-stable across runs, but
    varied like a real state rather than repeating every N areas. Spread 0.12-0.62, so
    areas land in different advisory bands as the dry belt and the coast really do."""
    h = int(hashlib.sha1(str(key).encode()).hexdigest()[:8], 16)
    j = (h % 1000) / 1000.0
    return dict(
        # September: monsoon withdrawing, so onset probability is low and dry-spell risk rises.
        p_onset=c.leadset(0.05 + j * 0.02, 0.04 + j * 0.02, 0.03, 0.02),
        p_false_onset=c.leadset(0.10 + j * 0.03, 0.08 + j * 0.02, 0.06, 0.05),
        p_dry7=c.leadset(0.12 + j * 0.50, min(1.0, 0.20 + j * 0.52), min(1.0, 0.28 + j * 0.50), min(1.0, 0.34 + j * 0.48)),
        p_dry14=c.leadset(0.12 + j * 0.03, 0.19 + j * 0.03, 0.26, 0.31),
        p_heavy=c.leadset(max(0.0, 0.40 - j * 0.46), 0.12, 0.09, 0.07),
    )


def areas_from_geo(pilot_only: bool):
    """Real KGIS areas: district -> taluk -> hobli, real centroids, real cell counts."""
    import pandas as pd

    from varshadrishti.geo import boundaries as B

    districts = B.attach_kannada_names(B.load_districts())
    districts["lgd_code"] = None
    taluks = B.attach_kannada_names(B.attach_lgd_codes(B.load_taluks()))
    hoblis = B.load_hoblis(taluks)
    hoblis["lgd_code"] = None

    if pilot_only:
        keep_d = {a for a, n in zip(districts["area_id"], districts["name_en"])
                  if str(n).upper().replace(" ", "") in PILOT_DISTRICTS}
        districts = districts[districts["area_id"].isin(keep_d)]
        taluks = taluks[taluks["parent_id"].isin(keep_d)]
        hoblis = hoblis[hoblis["parent_id"].isin(set(taluks["area_id"]))]

    n_cells = {}
    for level in ("districts", "blocks", "hoblis"):
        p = B.ROOT / "data" / "processed" / f"weights_imd_{level}.parquet"
        if p.exists():
            n_cells.update(pd.read_parquet(p).groupby("area_id")["cell_id"].count().to_dict())

    def clean(v):
        """pandas NaN would serialise as bare NaN — invalid JSON. Null means 'no match'."""
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    out = []
    for i, (g, level) in enumerate(
        ((districts, "district"), (taluks, "block"), (hoblis, "panchayat"))
    ):
        cents = B.centroids(g)
        for k, (_, row) in enumerate(g.iterrows()):
            aid = row["area_id"]
            out.append(
                c.Area(
                    area_id=aid,
                    name_en=str(row["name_en"]),
                    name_kn=str(row.get("name_kn") or ""),
                    level=level,
                    lgd_code=clean(row.get("lgd_code")),
                    parent_id=row["parent_id"],
                    district_en=str(row.get("district_en") or ""),
                    centroid=cents[k],
                    n_cells=int(n_cells.get(aid, 1)),
                    onset_delay_weeks=2.0 + (k % 10) / 10.0,
                    onset_status="in_season",
                    confidence="medium" if k % 3 else "low",
                    **pseudo(aid),
                )
            )
    # rules run over the finished probabilities, exactly as the nightly job will
    packs = E.load_rules()
    for a in out:
        a.advisories = E.evaluate(a.to_dict(), crop="ragi", stage="pre_sowing", packs=packs)
    return out


def areas_from_fixture():
    areas = [
        c.Area(
            area_id=aid, name_en=en, name_kn=kn, level=lvl, parent_id=parent,
            centroid=ctr, n_cells=nc, onset_delay_weeks=2.0 + i / 10,
            onset_status="in_season", confidence="medium" if i < 2 else "low",
            **pseudo(aid),
        )
        for i, (aid, en, kn, lvl, parent, ctr, nc) in enumerate(FIXTURE)
    ]
    packs = E.load_rules()
    for a in areas:
        a.advisories = E.evaluate(a.to_dict(), crop="ragi", stage="pre_sowing", packs=packs)
    return areas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid-from", default=date.today().isoformat())
    ap.add_argument("--out", default=str(c.FORECAST_DIR))
    ap.add_argument("--fixture", action="store_true", help="hard-coded areas, no geo data needed")
    ap.add_argument("--pilot-only", action="store_true", help="only the 5 pilot districts")
    args = ap.parse_args()

    valid_from = date.fromisoformat(args.valid_from)
    code_system = "mock" if args.fixture else "kgis"
    meta = c.make_meta(valid_from, code_system=code_system)

    provenance = {
        "nwp": {
            "source": "ECMWF EC46 via Open-Meteo Seasonal API",
            "members": 51,
            "run_date": valid_from.isoformat(),
        },
        "statistical": {"source": "LightGBM on IMD 0.25deg 1991-2024", "seasons": 34},
        "blend_weights": c.leadset(0.80, 0.60, 0.40, 0.25),
        "calibration": "isotonic, fitted on leave-one-year-out predictions",
    }
    skill = real_skill() or {
        # only until P5 has run — /verify shows a MOCK badge while this branch is taken
        "bss": {"w1": 0.21, "w2": 0.12, "w3": 0.03, "w4": -0.01},
        "reference": "per-cell, per-date climatology 1991-2024",
        "roc_auc": 0.74,
        "advisory_horizon_weeks": 2,
    }

    areas = areas_from_fixture() if args.fixture else areas_from_geo(args.pilot_only)

    sizes = c.emit_all(
        meta, provenance, skill, areas,
        out_dir=Path(args.out),
        provenance_summary=(
            "Based on 51 ECMWF ensemble members and 34 years of IMD rainfall for your hobli."
        ),
    )

    area_sizes = [v for k, v in sizes.items() if k.startswith("area/")]
    for name in ("latest.json", "index.json"):
        print(f"  {name:24s} {sizes[name]:9,d} B")
    print(f"  {'area/*.json':24s} {len(area_sizes):9,d} files, "
          f"largest {max(area_sizes):,} B (budget {c.AREA_FILE_MAX_BYTES:,})")
    print(f"\n{len(areas)} areas | code_system={code_system}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
