"""Build simplified GeoJSON and the grid-cell -> polygon area-weight matrices."""

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
warnings.filterwarnings("ignore")

from varshadrishti.geo import boundaries as B  # noqa: E402
from varshadrishti.geo import weights as W  # noqa: E402

WEIGHT_DIR = B.ROOT / "data" / "processed"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    B.GEO_OUT.mkdir(parents=True, exist_ok=True)

    districts = B.attach_kannada_names(B.load_districts())
    districts["lgd_code"] = None
    taluks = B.attach_kannada_names(B.attach_lgd_codes(B.load_taluks()))
    hoblis = B.load_hoblis(taluks)
    hoblis["lgd_code"] = None  # LGD has no hobli tier — it is a Karnataka revenue unit
    log(f"loaded {len(districts)} districts, {len(taluks)} taluks, {len(hoblis)} hoblis")
    for nm, g in (("districts", districts), ("taluks", taluks)):
        kn = (g["name_kn"].astype(str).str.len() > 0).sum()
        log(f"  Kannada names: {nm} {kn}/{len(g)}")

    matched = taluks["lgd_code"].notna().sum()
    log(f"LGD crosswalk: {matched}/{len(taluks)} taluks matched ({matched / len(taluks):.0%})")

    for name, g, tol in (
        ("districts", districts, B.SIMPLIFY_DISTRICT),
        ("blocks", taluks, B.SIMPLIFY_TALUK),
        ("hoblis", hoblis, B.SIMPLIFY_HOBLI),
    ):
        path = B.GEO_OUT / f"{name}.geojson"
        size = B.to_geojson(g, path, tol)
        flag = "OK" if size < 1_000_000 else "OVER 1 MB"
        log(f"{name:8s} -> {size / 1024:7.0f} KB  [{flag}]")

    for grid in ("imd", "chirps"):
        for name, g in (("districts", districts), ("blocks", taluks), ("hoblis", hoblis)):
            t = time.time()
            w = W.area_weights(g, grid)
            path = WEIGHT_DIR / f"weights_{grid}_{name}.parquet"
            size = W.save(w, path)
            per = W.cells_per_area(w)
            log(
                f"weights {grid:6s} {name:7s} {len(w):7,d} rows, {size / 1024:6.0f} KB, "
                f"cells/area min={per.min()} median={int(per.median())} max={per.max()} "
                f"({time.time() - t:.0f}s)"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
