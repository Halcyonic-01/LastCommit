"""P7: hindcast output is real, self-consistent, and the nightly refactor didn't drift.

The heavy lifting (does the model score correctly) is already covered by
test_p7_xgb_integration.py; this checks the hindcast-specific plumbing: shapes,
key naming the frontend depends on, and that run_one_day still produces a valid,
schema-passing forecast after being pulled out of main().
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

FORECAST_HC = ROOT / "forecast" / "hindcast"


@pytest.mark.skipif(not (FORECAST_HC / "2024.json").exists(),
                    reason="run scripts/hindcast.py first")
def test_scrubber_payload_shape_matches_what_replay_jsx_reads():
    d = json.loads((FORECAST_HC / "2024.json").read_text())
    assert d["level"] == "district"
    assert len(d["areas"]) == 30, "one entry per district"

    one = next(iter(d["areas"].values()))
    a_date = next(iter(one.values()))
    # Replay.jsx indexes day[f"{event}_w1"] -- if the key shape ever changes there,
    # this is the test that should fail, not a silently-blank scrubber in the browser.
    for event in ("onset", "false_onset", "dry7", "dry14", "heavy"):
        for lead in ("w1", "w2", "w3", "w4"):
            key = f"{event}_{lead}"
            assert key in a_date, f"missing {key}"
            assert 0.0 <= a_date[key]["pred"] <= 1.0
            assert a_date[key]["actual"] in (0.0, 1.0) or 0.0 <= a_date[key]["actual"] <= 1.0


@pytest.mark.skipif(not (FORECAST_HC / "spotlight.json").exists(),
                    reason="run scripts/hindcast.py first")
def test_spotlight_story_is_internally_consistent():
    s = json.loads((FORECAST_HC / "spotlight.json").read_text())
    # the narrative claims onset + false_onset both actually happened -- the numbers
    # backing that claim must actually say so, not just the prose
    assert s["forecast"]["onset"]["actual"] == 1.0
    assert s["forecast"]["false_onset"]["actual"] == 1.0
    assert s["forecast"]["false_onset"]["pred"] > 0.5, "the model must have actually flagged it"
    # the six real dry days the narrative names must be zero in the same rain series
    dry_days = ["2024-08-22", "2024-08-23", "2024-08-24", "2024-08-25", "2024-08-26", "2024-08-27"]
    for d in dry_days:
        assert s["rain_mm"][d] == 0.0, f"{d} should be dry per the narrative"
    assert s["rain_mm"]["2024-08-20"] > 40, "the heavy-rain day the story opens on"


def test_aggregate_to_areas_clip_is_backward_compatible():
    from varshadrishti.pipeline import aggregate as A

    w = pd.read_parquet(ROOT / "data" / "processed" / "weights_imd_districts.parquet")
    one_area = w["area_id"].iloc[0]
    cells = w[w["area_id"] == one_area]["cell_id"].tolist()

    # every cell at 1.5 -> the weighted mean is unambiguously 1.5 too, regardless of
    # the (unknown here) per-cell weights, so this actually exercises the clip boundary
    probs = pd.DataFrame({"p": 1.5}, index=cells)
    default = A.to_areas(probs, "district")
    assert default.loc[one_area, "p"] == 1.0, "default clip must bound to a probability's [0,1]"

    wide = A.to_areas(probs, "district", clip=(-8.0, 12.0))
    assert wide.loc[one_area, "p"] == pytest.approx(1.5), "unclipped by the wider range"

    raw = A.to_areas(probs, "district", clip=None)
    assert raw.loc[one_area, "p"] == pytest.approx(1.5), "clip=None must skip clipping entirely"


def test_run_one_day_survives_the_extraction_from_main():
    import nightly

    assert callable(nightly.run_one_day)
    sizes, diag = nightly.run_one_day("2026-09-19", offline=True,
                                      out=Path("/tmp/vd_test_run_one_day"),
                                      model_version="1.0.0-test")
    assert sizes["latest.json"] > 0
    assert diag["n_cells"] > 0
    meta = json.loads((Path("/tmp/vd_test_run_one_day") / "latest.json").read_text())["meta"]
    assert meta["model_version"] == "1.0.0-test"
    assert meta["is_mock"] is False
