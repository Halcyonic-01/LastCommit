"""CRIDA advisory rules. Finite YAML, no LLM anywhere in the decision path."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = ROOT / "rules"

MAX_ADVISORIES = 3  # the contract's cap: a farmer gets one decision, not a list
SEVERITY_ORDER = {"critical": 0, "warn": 1, "watch": 2, "info": 3}

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
    stage: str
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
        if self.stage != "any" and self.stage != stage:
            return False
        for key, expr in self.when.items():
            if key not in facts:
                raise RuleError(f"rule {self.id}: unknown fact {key!r}")
            for e in (expr if isinstance(expr, list) else [expr]):
                if not _cmp(facts[key], e):
                    return False
        return True


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
        out.append({
            "rule_id": r.id,
            "crop": crop,
            "stage": stage,
            "severity": r.severity,
            "action_en": r.action_en,
            "action_kn": r.action_kn,
            "confidence_word_en": "likely",
            "confidence_word_kn": "ಸಾಧ್ಯತೆ ಇದೆ",
            **({"reason_en": r.reason_en} if r.reason_en else {}),
            **({"reason_kn": r.reason_kn} if r.reason_kn else {}),
            "source": {
                "doc": r.source_doc,
                "table": r.table,
                **({"district": r.district} if r.district else {}),
            },
        })
    return out
