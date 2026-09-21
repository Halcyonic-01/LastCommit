"""CRIDA advisory rules. Finite YAML, no LLM anywhere in the decision path."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = ROOT / "rules"

MAX_ADVISORIES = 3  # the contract's cap: a farmer gets one decision, not a list
SEVERITY_ORDER = {"critical": 0, "warn": 1, "watch": 2, "info": 3}

# How sure the *event a rule fires on* is, not how good the model is (see skillWord in
# the frontend for that, a different question). Tiered on the matched probability itself.
CONFIDENCE_WORDS = [
    (0.70, "very likely", "ಬಹುತೇಕ ಖಚಿತ"),
    (0.45, "likely", "ಸಾಧ್ಯತೆ ಇದೆ"),
    (0.0, "possible", "ಸ್ವಲ್ಪ ಸಾಧ್ಯತೆ"),
]


def confidence_word(p: float) -> tuple[str, str]:
    """-> (en, kn) for how sure the matched probability makes this specific call."""
    for floor, en, kn in CONFIDENCE_WORDS:
        if p >= floor:
            return en, kn
    return CONFIDENCE_WORDS[-1][1:]

_COND = re.compile(r"^\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


class RuleError(ValueError):
    pass


def _cmp(value: float, expr: str) -> bool:
    """Only `<op> <number>` is allowed — never eval, so a rules file cannot run code."""
    m = _COND.match(str(expr))
    if not m:
        raise RuleError(f"bad condition {expr!r}; expected e.g. '>= 0.3'")
    op, num = m.group(1), float(m.group(2))
    return {
        ">=": value >= num, "<=": value <= num, ">": value > num,
        "<": value < num, "==": value == num, "!=": value != num,
    }[op]


@dataclass(frozen=True)
class Rule:
    id: str
    crop: str
    stage: str | list[str]  # a list means "any of these stages" — see matches()
    severity: str
    table: str
    when: dict
    action_kn: str
    action_en: str
    reason_kn: str
    reason_en: str
    source_doc: str
    district: str = ""

    def matches(self, facts: dict, crop: str, stage: str) -> bool:
        if self.crop != "any" and self.crop != crop:
            return False
        stages = self.stage if isinstance(self.stage, list) else [self.stage]
        if "any" not in stages and stage not in stages:
            return False
        for key, expr in self.when.items():
            if key not in facts:
                raise RuleError(f"rule {self.id}: unknown fact {key!r}")
            for e in (expr if isinstance(expr, list) else [expr]):
                if not _cmp(facts[key], e):
                    return False
        return True

    def driving_value(self, facts: dict) -> float:
        """The highest fact this rule's `when` reads — a proxy for how strongly the
        matched condition holds, used only to word the confidence, never the threshold."""
        vals = [facts[k] for k in self.when if k in facts]
        return max(vals) if vals else 0.0


def _load_file(path: Path) -> list[Rule]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    src = doc.get("source_doc", "")
    district = doc.get("district", "")
    out = []
    for r in doc.get("rules", []):
        missing = {"id", "action_kn", "action_en", "table"} - set(r)
        if missing:
            raise RuleError(f"{path.name}: rule missing {sorted(missing)}")
        out.append(Rule(
            id=r["id"], crop=r.get("crop", "any"), stage=r.get("stage", "any"),
            severity=r.get("severity", "info"), table=str(r["table"]), when=r.get("when", {}),
            action_kn=r["action_kn"], action_en=r["action_en"],
            reason_kn=r.get("reason_kn", ""), reason_en=r.get("reason_en", ""),
            source_doc=src, district=district,
        ))
    return out


def load_rules(rules_dir: Path = RULES_DIR) -> dict[str, list[Rule]]:
    """-> {district_name_or_'': [Rule]}. A district rule shadows a default with the same id."""
    base = _load_file(rules_dir / "default.yaml") if (rules_dir / "default.yaml").exists() else []
    packs = {"": base}
    for p in sorted((rules_dir / "districts").glob("*.yaml")):
        district = yaml.safe_load(p.read_text(encoding="utf-8")).get("district", p.stem)
        overrides = _load_file(p)
        by_id = {r.id: r for r in base}
        by_id.update({r.id: r for r in overrides})
        packs[district] = list(by_id.values())
    return packs


def facts_from(area: dict) -> dict:
    """Flatten a forecast body into the names a rule may reference."""
    f = {}
    for head in ("p_onset", "p_false_onset", "p_dry7", "p_dry14", "p_heavy"):
        for lead, v in area[head].items():
            f[f"{head}_{lead}"] = v
    f["p_dry7_w1_max"] = max(area["p_dry7"].values())
    f["onset_delay_weeks"] = area.get("onset_delay_weeks", 0.0)
    return f


CLIM_ONSET_DOY = 152  # 1 June — the calendar anchor `onset_delay_weeks` is measured against

# Ragi/groundnut kharif growth stages, in weeks after actual sowing (CRIDA sowing windows
# put both crops' kharif-rainfed sowing at 1 June onward — schema/common.schema.json#stage).
# Weeks-after-sowing boundaries are a documented agronomic approximation (~90-120 day
# kharif cycle for ragi/groundnut), not a per-cell measurement — the rules this feeds are
# already the coarse, published CRIDA tables, not a precision the forecast itself claims.
_STAGE_BOUNDS = [(0, "sowing"), (1, "vegetative"), (6, "flowering"), (10, "maturity")]


def crop_stage(as_of: date, onset_delay_weeks: float) -> str:
    """-> one of the contract's stage enum values, from how far past the actual
    (climatology + measured delay) sowing date `as_of` is. Never guesses ahead of
    onset: before the delayed sowing date, every rule sees `pre_sowing`."""
    sowing_doy = CLIM_ONSET_DOY + max(0.0, onset_delay_weeks) * 7
    weeks_since_sowing = (as_of.timetuple().tm_yday - sowing_doy) / 7
    if weeks_since_sowing < 0:
        return "pre_sowing"
    stage = "sowing"
    for floor, name in _STAGE_BOUNDS:
        if weeks_since_sowing >= floor:
            stage = name
    return stage


def evaluate(area: dict, crop: str = "ragi", stage: str = "pre_sowing",
             packs: dict[str, list[Rule]] | None = None) -> list[dict]:
    """Advisories for one area, most severe first, capped at the contract's limit."""
    packs = packs or load_rules()
    rules = packs.get(area.get("district_en", ""), packs[""])
    facts = facts_from(area)

    hits = [r for r in rules if r.matches(facts, crop, stage)]
    hits.sort(key=lambda r: (SEVERITY_ORDER.get(r.severity, 9), r.id))

    out = []
    for r in hits[:MAX_ADVISORIES]:
        conf_en, conf_kn = confidence_word(r.driving_value(facts))
        out.append({
            "rule_id": r.id,
            "crop": crop,
            "stage": stage,
            "severity": r.severity,
            "action_en": r.action_en,
            "action_kn": r.action_kn,
            "confidence_word_en": conf_en,
            "confidence_word_kn": conf_kn,
            **({"reason_en": r.reason_en} if r.reason_en else {}),
            **({"reason_kn": r.reason_kn} if r.reason_kn else {}),
            "source": {
                "doc": r.source_doc,
                "table": r.table,
                **({"district": r.district} if r.district else {}),
            },
        })
    return out
