"""Generate schema-valid mock forecast files so the PWA can be built before the model exists.

Uses REAL Karnataka geography from P2 (KGIS ids, names, centroids, cell counts) with invented
probabilities. P6 swaps the numbers for model output; nothing about the shape changes.

--fixture falls back to hard-coded MOCK-* areas so the contract tests run without geo data.
"""

import argparse
import sys
import warnings
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
warnings.filterwarnings("ignore")

from varshadrishti import contract as c  # noqa: E402

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


def pseudo(i):
    """Deterministic pseudo-values — no RNG, so output is byte-stable across runs."""
    j = (i % 10) / 10.0
    return dict(
        # September: monsoon withdrawing, so onset probability is low and dry-spell risk rises.
        p_onset=c.leadset(0.05 + j * 0.02, 0.04 + j * 0.02, 0.03, 0.02),
        p_false_onset=c.leadset(0.10 + j * 0.03, 0.08 + j * 0.02, 0.06, 0.05),
        p_dry7=c.leadset(0.32 + j * 0.05, 0.41 + j * 0.04, 0.48, 0.55),
        p_dry14=c.leadset(0.12 + j * 0.03, 0.19 + j * 0.03, 0.26, 0.31),
        p_heavy=c.leadset(max(0.0, 0.18 - j * 0.01), 0.12, 0.09, 0.07),
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
                    advisories=[ADVISORY] if str(row["name_en"]).upper() == "TUMAKURU" else [],
                    **pseudo(k + i),
                )
            )
    return out


def areas_from_fixture():
    return [
        c.Area(
            area_id=aid, name_en=en, name_kn=kn, level=lvl, parent_id=parent,
            centroid=ctr, n_cells=nc, onset_delay_weeks=2.0 + i / 10,
            onset_status="in_season", confidence="medium" if i < 2 else "low",
            advisories=[ADVISORY] if en == "Tumakuru" else [],
            **pseudo(i),
        )
        for i, (aid, en, kn, lvl, parent, ctr, nc) in enumerate(FIXTURE)
    ]


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
    # Mock skill, shaped like the real thing: decays with lead and can go negative.
    skill = {
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
