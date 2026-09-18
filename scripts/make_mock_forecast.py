"""Generate schema-valid mock forecast files so the PWA can be built before the model exists.

Placeholders are honest: code_system='mock', is_mock=true, MOCK-* ids. P2 swaps in real LGD
codes and P6 swaps in real probabilities — neither should require a frontend change.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from varshadrishti import contract as c  # noqa: E402

# Pilot geography. Centroids are real; probabilities are invented.
BLOCKS = [
    ("Tumakuru", "ತುಮಕೂರು", "Tumakuru", [77.101, 13.342]),
    ("Tiptur", "ತಿಪಟೂರು", "Tumakuru", [76.477, 13.256]),
    ("Chitradurga", "ಚಿತ್ರದುರ್ಗ", "Chitradurga", [76.398, 14.230]),
    ("Hiriyur", "ಹಿರಿಯೂರು", "Chitradurga", [76.619, 13.945]),
    ("Chikkaballapur", "ಚಿಕ್ಕಬಳ್ಳಾಪುರ", "Chikkaballapur", [77.732, 13.435]),
    ("Davanagere", "ದಾವಣಗೆರೆ", "Davanagere", [75.921, 14.464]),
    ("Kolar", "ಕೋಲಾರ", "Kolar", [78.130, 13.137]),
]

# Two hoblis under Tumakuru block — proves the panchayat level round-trips.
HOBLIS = [
    ("Gubbi", "ಗುಬ್ಬಿ", "Tumakuru", "MOCK-BLK-Tumakuru", [76.940, 13.312]),
    ("Kora", "ಕೋರ", "Tumakuru", "MOCK-BLK-Tumakuru", [77.043, 13.443]),
]

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


def slug(name):
    return name.replace(" ", "_")


def mock_area(name_en, name_kn, district, centroid, level, parent_id, i):
    """Deterministic pseudo-values — no RNG, so the mock is reproducible across runs."""
    j = i / 10.0
    return c.Area(
        area_id=f"MOCK-{'BLK' if level == 'block' else 'HOB'}-{slug(name_en)}",
        name_en=name_en,
        name_kn=name_kn,
        level=level,
        district_en=district,
        parent_id=parent_id,
        centroid=centroid,
        n_cells=9 if level == "block" else 3,
        # September: monsoon withdrawing, so onset probability is low and dry-spell risk rises.
        p_onset=c.leadset(0.05 + j * 0.02, 0.04 + j * 0.02, 0.03, 0.02),
        p_false_onset=c.leadset(0.10 + j * 0.03, 0.08 + j * 0.02, 0.06, 0.05),
        p_dry7=c.leadset(0.32 + j * 0.05, 0.41 + j * 0.04, 0.48, 0.55),
        p_dry14=c.leadset(0.12 + j * 0.03, 0.19 + j * 0.03, 0.26, 0.31),
        p_heavy=c.leadset(0.18 - j * 0.01, 0.12, 0.09, 0.07),
        onset_delay_weeks=2.0 + j,
        onset_status="in_season",
        confidence="medium" if i < 4 else "low",
        advisories=[ADVISORY] if name_en == "Tumakuru" else [],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid-from", default=date.today().isoformat())
    ap.add_argument("--out", default=str(c.FORECAST_DIR))
    args = ap.parse_args()

    valid_from = date.fromisoformat(args.valid_from)
    meta = c.make_meta(valid_from)

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
    # Mock skill values, shaped like the real thing: skill decays with lead and can go negative.
    skill = {
        "bss": {"w1": 0.21, "w2": 0.12, "w3": 0.03, "w4": -0.01},
        "reference": "per-cell, per-date climatology 1991-2024",
        "roc_auc": 0.74,
        "advisory_horizon_weeks": 2,
    }

    areas = [
        mock_area(n, kn, d, ctr, "block", None, i) for i, (n, kn, d, ctr) in enumerate(BLOCKS)
    ] + [
        mock_area(n, kn, d, ctr, "panchayat", p, i + len(BLOCKS))
        for i, (n, kn, d, p, ctr) in enumerate(HOBLIS)
    ]

    sizes = c.emit_all(
        meta,
        provenance,
        skill,
        areas,
        out_dir=Path(args.out),
        provenance_summary=(
            "Based on 51 ECMWF ensemble members and 34 years of IMD rainfall for your hobli."
        ),
    )

    for name, size in sizes.items():
        flag = ""
        if name.startswith("area/"):
            flag = f"  (budget {c.AREA_FILE_MAX_BYTES} B)"
        print(f"  {name:38s} {size:7,d} B{flag}")
    area_sizes = [v for k, v in sizes.items() if k.startswith("area/")]
    print(f"\n{len(areas)} areas | largest farmer payload {max(area_sizes):,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
