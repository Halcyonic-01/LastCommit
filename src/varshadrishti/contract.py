"""The frozen forecast contract: builders and validators for every emitted JSON file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_VERSION = "1.1.0"  # 1.1: advisory.reason_en/_kn
LEADS = ("w1", "w2", "w3", "w4")

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schema"
FORECAST_DIR = ROOT / "forecast"

# Farmer payload budget: one fetch/day on 2G. Breaching this is a build failure.
AREA_FILE_MAX_BYTES = 4096


class ContractError(ValueError):
    """Raised when data does not match the frozen contract."""


# --- validation ------------------------------------------------------------


def _registry() -> Registry:
    reg = Registry()
    for p in SCHEMA_DIR.glob("*.schema.json"):
        doc = json.loads(p.read_text())
        # register under both $id and bare filename so relative $refs resolve
        reg = reg.with_resource(doc["$id"], Resource.from_contents(doc))
        reg = reg.with_resource(p.name, Resource.from_contents(doc))
    return reg


def validator_for(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text())
    return Draft202012Validator(schema, registry=_registry())


def validate(payload: dict, schema_name: str) -> None:
    """Raise ContractError listing every violation, not just the first."""
    errors = sorted(validator_for(schema_name).iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return
    lines = [f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:20]]
    if len(errors) > 20:
        lines.append(f"  ... and {len(errors) - 20} more")
    raise ContractError(f"{schema_name}: {len(errors)} violation(s)\n" + "\n".join(lines))


# --- builders --------------------------------------------------------------


def lead_dates(valid_from: date) -> dict[str, dict[str, str]]:
    """w1 = days 1-7 from valid_from, w2 = 8-14, and so on."""
    out = {}
    for i, lead in enumerate(LEADS):
        start = valid_from + timedelta(days=1 + 7 * i)
        out[lead] = {"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat()}
    return out


def make_meta(
    valid_from: date,
    state: str = "karnataka",
    code_system: str = "mock",
    model_version: str = "0.0.0-mock",
    is_mock: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": model_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "valid_from": valid_from.isoformat(),
        "state": state,
        "code_system": code_system,
        "is_mock": is_mock,
        "lead_dates": lead_dates(valid_from),
    }


def leadset(w1: float, w2: float, w3: float, w4: float) -> dict[str, float]:
    vals = (w1, w2, w3, w4)
    if any(not 0.0 <= v <= 1.0 for v in vals):
        raise ContractError(f"probabilities must be in [0,1], got {vals}")
    return dict(zip(LEADS, (round(v, 3) for v in vals)))


@dataclass
class Area:
    """One block or panchayat. Mirrors common.schema.json#/$defs/forecastBody."""

    area_id: str
    name_en: str
    level: str
    p_onset: dict[str, float]
    p_false_onset: dict[str, float]
    p_dry7: dict[str, float]
    p_dry14: dict[str, float]
    p_heavy: dict[str, float]
    onset_status: str
    confidence: str
    name_kn: str = ""
    lgd_code: str | None = None
    parent_id: str | None = None
    district_en: str = ""
    centroid: list[float] | None = None
    n_cells: int | None = None
    onset_delay_weeks: float | None = None
    advisories: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "area_id": self.area_id,
            "name_en": self.name_en,
            "level": self.level,
            "p_onset": self.p_onset,
            "p_false_onset": self.p_false_onset,
            "p_dry7": self.p_dry7,
            "p_dry14": self.p_dry14,
            "p_heavy": self.p_heavy,
            "onset_status": self.onset_status,
            "confidence": self.confidence,
            "lgd_code": self.lgd_code,
            "parent_id": self.parent_id,
        }
        for k in ("name_kn", "district_en"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        for k in ("centroid", "n_cells", "onset_delay_weeks"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.advisories:
            d["advisories"] = self.advisories
        return d


def build_forecast(meta: dict, provenance: dict, skill: dict, areas: Iterable[Area]) -> dict:
    payload = {
        "meta": meta,
        "provenance": provenance,
        "skill": skill,
        "areas": {a.area_id: a.to_dict() for a in areas},
    }
    validate(payload, "forecast.schema.json")
    return payload


def build_area_file(meta: dict, area: Area, skill: dict, provenance_summary: str = "") -> dict:
    payload = {"meta": meta, "forecast": area.to_dict(), "skill": skill}
    if provenance_summary:
        payload["provenance_summary"] = provenance_summary
    validate(payload, "area.schema.json")
    return payload


def build_index(meta: dict, areas: Iterable[Area]) -> dict:
    entries = {}
    for a in areas:
        e = {"name_en": a.name_en, "level": a.level, "parent_id": a.parent_id}
        for k in ("name_kn", "district_en"):
            if getattr(a, k):
                e[k] = getattr(a, k)
        if a.centroid is not None:
            e["centroid"] = a.centroid
        entries[a.area_id] = e
    payload = {"meta": meta, "areas": entries}
    validate(payload, "index.schema.json")
    return payload


# --- emit ------------------------------------------------------------------


def write_json(payload: dict, path: Path, max_bytes: int | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size = len(blob.encode("utf-8"))
    if max_bytes and size > max_bytes:
        raise ContractError(f"{path.name} is {size} B, over the {max_bytes} B budget")
    path.write_text(blob, encoding="utf-8")
    return size


def emit_all(
    meta: dict,
    provenance: dict,
    skill: dict,
    areas: list[Area],
    out_dir: Path = FORECAST_DIR,
    archive: bool = True,
    provenance_summary: str = "",
) -> dict[str, int]:
    """Write latest.json, index.json, one area file each, and the dated archive copy."""
    sizes = {}
    full = build_forecast(meta, provenance, skill, areas)
    sizes["latest.json"] = write_json(full, out_dir / "latest.json")
    if archive:
        stamp = meta["valid_from"]
        sizes[f"archive/{stamp}.json"] = write_json(full, out_dir / "archive" / f"{stamp}.json")
    sizes["index.json"] = write_json(build_index(meta, areas), out_dir / "index.json")
    for a in areas:
        p = out_dir / "area" / f"{a.area_id}.json"
        sizes[f"area/{a.area_id}.json"] = write_json(
            build_area_file(meta, a, skill, provenance_summary), p, AREA_FILE_MAX_BYTES
        )
    return sizes


def load_and_validate(path: Path, schema_name: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate(payload, schema_name)
    return payload
