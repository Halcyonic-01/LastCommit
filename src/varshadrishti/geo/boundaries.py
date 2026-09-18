"""Load KGIS boundaries, build the district->taluk->hobli hierarchy, emit simplified GeoJSON."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "boundaries"
LGD_CSV = ROOT / "data" / "raw" / "lgd" / "subdistricts.csv"
OSM_KN = ROOT / "data" / "raw" / "osm" / "karnataka_names_kn.json"
GEO_OUT = ROOT / "geo"

WGS84 = "EPSG:4326"
EQUAL_AREA = "EPSG:6933"  # World Cylindrical Equal Area — areas in m^2, valid beyond Karnataka

SIMPLIFY_DISTRICT = 0.0020
SIMPLIFY_TALUK = 0.0015  # 838 KB
SIMPLIFY_HOBLI = 0.0050  # 871 KB, under the 1 MB budget


def norm_name(s: str) -> str:
    return re.sub(r"[^A-Z]", "", str(s).upper())


def _dissolve(g: gpd.GeoDataFrame, cols: list[str]) -> gpd.GeoDataFrame:
    """KGIS ships multipart areas as separate rows — merge them into one multipolygon each."""
    out = g.dissolve(by="area_id", as_index=False, aggfunc="first")
    return out[cols + ["geometry"]]


COLS = ["area_id", "kgis_code", "name_en", "name_kn", "level", "parent_id", "district_en"]


def load_districts() -> gpd.GeoDataFrame:
    g = gpd.read_file(RAW / "District_Boundaries.gpkg").to_crs(WGS84)
    g = g.rename(columns={"BhuCodeDis": "kgis_code", "KGISDist_1": "name_en"})
    g["kgis_code"] = g["kgis_code"].astype(str).str.zfill(2)
    g["area_id"] = "KGIS-D-" + g["kgis_code"]
    g["level"] = "district"
    g["parent_id"] = None
    g["district_en"] = g["name_en"]
    g["name_kn"] = ""
    return _dissolve(g, COLS)


def _district_lookup() -> dict:
    """KGISDistri in the taluk table is a ROW id into the district table, not a district code.

    The taluk-code prefix looks like a district code but disagrees for 17 taluks carved into
    newer districts — including Chikkaballapura, a pilot district. Always use the row id.
    """
    d = gpd.read_file(RAW / "District_Boundaries.gpkg")
    return {
        int(r["KGISDistri"]): (str(r["BhuCodeDis"]).zfill(2), r["KGISDist_1"])
        for _, r in d.iterrows()
    }


def load_taluks() -> gpd.GeoDataFrame:
    g = gpd.read_file(RAW / "Taluk_Boundaries.gpkg").to_crs(WGS84)
    g = g.rename(columns={"KGISTalukC": "kgis_code", "KGISTalukN": "name_en"})
    g["kgis_code"] = g["kgis_code"].astype(str).str.zfill(4)
    g["area_id"] = "KGIS-T-" + g["kgis_code"]
    g["level"] = "block"

    lookup = _district_lookup()
    g["district_en"] = g["KGISDistri"].map(lambda i: lookup.get(int(i), ("", ""))[1])
    g["parent_id"] = g["KGISDistri"].map(
        lambda i: "KGIS-D-" + lookup[int(i)][0] if int(i) in lookup else None
    )
    g["name_en"] = g["name_en"].astype(str).str.title()
    g["name_kn"] = ""
    return _dissolve(g, COLS)


def load_hoblis(taluks: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    g = gpd.read_file(RAW / "Hobli_Boundaries.gpkg").to_crs(WGS84)
    g = g.rename(columns={"KGISHobliC": "kgis_code", "KGISHobliN": "name_en"})
    g["kgis_code"] = g["kgis_code"].astype(str).str.zfill(6)
    g["area_id"] = "KGIS-H-" + g["kgis_code"]
    g["level"] = "panchayat"
    # hobli code is <taluk code><hobli seq>, so the first 4 chars identify the parent taluk
    g["parent_id"] = "KGIS-T-" + g["kgis_code"].str[:4]
    g["name_en"] = g["name_en"].astype(str).str.title()
    g["name_kn"] = ""

    taluks = load_taluks() if taluks is None else taluks
    dist = dict(zip(taluks["area_id"], taluks["district_en"]))
    g["district_en"] = g["parent_id"].map(dist).fillna("")
    return _dissolve(g, COLS)


def attach_kannada_names(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """OSM name:kn, matched on normalised English name. Absent is fine — the UI falls back."""
    if not OSM_KN.exists():
        return g
    raw = json.loads(OSM_KN.read_text(encoding="utf-8"))
    lookup = {}
    for en, v in raw.items():
        # OSM appends the word for "district"/"taluk"; strip it for a clean label
        kn = re.sub(r"\s*(ಜಿಲ್ಲೆ|ತಾಲ್ಲೂಕು|ತಾಲೂಕು)\s*$", "", v["kn"]).strip()
        lookup[norm_name(re.sub(r"\s+(District|Taluk|Taluku)$", "", en, flags=re.I))] = kn

    keys = list(lookup)
    out = []
    for name in g["name_en"]:
        n = norm_name(name)
        if n in lookup:
            out.append(lookup[n])
            continue
        near = difflib.get_close_matches(n, keys, n=1, cutoff=0.90)
        out.append(lookup[near[0]] if near else "")
    g = g.copy()
    g["name_kn"] = out
    return g


def attach_lgd_codes(taluks: gpd.GeoDataFrame, cutoff: float = 0.92) -> gpd.GeoDataFrame:
    """Best-effort LGD crosswalk. Unmatched stays None — never guess a primary key."""
    taluks = taluks.copy()
    taluks["lgd_code"] = None
    if not LGD_CSV.exists():
        return taluks

    lgd = pd.read_csv(LGD_CSV)
    ka = lgd[lgd["State Name (In English)"].str.strip().str.upper() == "KARNATAKA"]
    lookup = {norm_name(r["Sub-District Name"]): str(r["Sub-District Code"])
              for _, r in ka.iterrows()}
    keys = list(lookup)

    codes = []
    for name in taluks["name_en"]:
        n = norm_name(name)
        if n in lookup:
            codes.append(lookup[n])
            continue
        near = difflib.get_close_matches(n, keys, n=1, cutoff=cutoff)
        codes.append(lookup[near[0]] if near else None)
    taluks["lgd_code"] = codes
    return taluks


def centroids(g: gpd.GeoDataFrame) -> list[list[float]]:
    """[lon, lat] per row, computed in an equal-area CRS to avoid lat-distortion."""
    c = g.to_crs(EQUAL_AREA).geometry.centroid.to_crs(WGS84)
    return [[round(p.x, 4), round(p.y, 4)] for p in c]


def to_geojson(g: gpd.GeoDataFrame, path: Path, tolerance: float) -> int:
    out = g.copy()
    out["geometry"] = out.geometry.simplify(tolerance, preserve_topology=True)
    # simplify can still emit self-intersections; repair rather than loosen the tolerance
    bad = ~out.geometry.is_valid
    if bad.any():
        out.loc[bad, "geometry"] = out.loc[bad, "geometry"].make_valid()
    keep = [c for c in ("area_id", "name_en", "name_kn", "level", "parent_id",
                        "district_en", "lgd_code") if c in out.columns]
    out = out[keep + ["geometry"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=4)
    return path.stat().st_size
