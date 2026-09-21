"""P9 acceptance: officer-facing pages describe the real model, not an approximation of it.

Each check reads the actual constant the frontend text is describing, rather than
asserting a copied-in string twice — a future recalibration that changes a threshold
fails these loudly instead of leaving the officer screen quietly wrong.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti.features import labels as L  # noqa: E402
from varshadrishti.pipeline import blend as BL  # noqa: E402

WEB = ROOT / "web" / "src"
OFFICER = (WEB / "pages" / "Officer.jsx").read_text()
VERIFY = (WEB / "pages" / "Verify.jsx").read_text()
REPLAY = (WEB / "pages" / "Replay.jsx").read_text()
HAZARD_MAP = (WEB / "components" / "HazardMap.jsx").read_text()
STRINGS = (WEB / "i18n" / "strings.js").read_text()
WHY = (WEB / "pages" / "Why.jsx").read_text()

KANNADA = re.compile(r"[ಀ-೿]")


def test_heavy_rain_legend_states_the_real_imd_threshold_not_a_percentile():
    """HEAVY_MM is a fixed IMD absolute threshold — nothing in the codebase computes a
    per-cell percentile for it, so the legend's old '95th percentile' described a
    different design than the one actually shipped."""
    assert "percentile" not in OFFICER.lower()
    assert str(L.HEAVY_MM) in OFFICER


def test_false_onset_legend_states_the_real_kill_window():
    """The Moron-Robertson kill rule is a FALSE_DRY_DAYS-day near-dry window (10), not
    the 7-day "a week" the legend used to say."""
    assert f"{L.FALSE_DRY_DAYS}-day" in OFFICER
    assert "stops for a week" not in OFFICER


def test_dry_spell_legend_matches_the_real_thresholds():
    assert f"{L.DRY_SPELL_DAYS} consecutive days under {L.RAINY_DAY_MM} mm" in OFFICER


def test_verify_page_does_not_claim_monotonic_weight_decay():
    """NWP_WEIGHT is measured, not assumed, and dips at w3 (0.01) before rising at w4
    (0.06) — the caption used to say 'weighted down as lead grows', true for w1->w3 but
    false for w3->w4."""
    weights = [BL.NWP_WEIGHT[w] for w in ("w1", "w2", "w3", "w4")]
    assert weights != sorted(weights, reverse=True), \
        "weights are monotonic now - the removed 'weighted down as lead grows' caption may be true again"
    assert "weighted down as lead grows" not in VERIFY


def test_officer_pages_are_english_only():
    """Officer tools are a job requirement, not a preference — language there must
    never follow the farmer's own choice. No Kannada script anywhere on them."""
    for name, text in (("Officer.jsx", OFFICER), ("Verify.jsx", VERIFY), ("Replay.jsx", REPLAY)):
        assert not KANNADA.search(text), f"{name} still renders Kannada script"
        assert "name_kn" not in text, f"{name} still prefers a Kannada place name"


def test_hazard_map_component_carries_no_language_preference_of_its_own():
    """HazardMap is shared by Officer and Replay — it must not bake in a language
    choice either, since the officer pages that use it are English-only."""
    assert not KANNADA.search(HAZARD_MAP)


def test_farmer_language_is_only_ever_set_by_the_farmers_own_choice():
    """The only place `lang` is chosen is Welcome's language picker — no
    auto-detection (navigator.language, Intl, …) and no officer page sets it."""
    for pattern in ("navigator.language", "Intl.", "detectLang"):
        assert pattern not in (WEB / "pages" / "Welcome.jsx").read_text()
        assert pattern not in OFFICER and pattern not in VERIFY and pattern not in REPLAY
    assert "setLang" in (WEB / "pages" / "Welcome.jsx").read_text()


def test_why_spoken_no_longer_contradicts_the_outlook_note():
    """whySpoken used to end with a fixed 'trust this week and next', true only when
    the advisory horizon happened to be 2. It is concatenated with outlookNote, which
    already states the real horizon (now 1) — the two used to contradict each other
    read aloud back to back."""
    assert "Trust this week and next" not in STRINGS
    # Pin the property, not the syntax: both templates must land in the one string the
    # listen button reads, so a horizon claim cannot drift out of sync with the evidence.
    # The builder moved to lib/narration.js when Today started sharing it.
    narration = (WEB / "lib" / "narration.js").read_text(encoding="utf-8")
    body = re.search(r"export function whyNarration\(.*?\n\}", narration, re.S)
    assert body, "whyNarration() is gone — /why no longer has one narration builder"
    assert 'tpl("whySpoken"' in body.group(0)
    assert 'tpl("outlookNote"' in body.group(0)


def test_why_page_states_the_training_split_only_once():
    """The 'seasons scored' fact and the chronological-split fact used to both restate
    'scored after training stopped' — one line was cut, not both facts."""
    assert "everything it was allowed to learn from" not in WHY
    assert "chronological split" in WHY


# --- deployment ---------------------------------------------------------------

def test_no_shipped_frontend_code_hardcodes_a_localhost_backend():
    """A hardcoded localhost URL works on the author's laptop and nowhere else, and it
    fails as a browser mixed-content block rather than an obvious error."""
    offenders = []
    for f in sorted((WEB / "lib").glob("*.js")) + sorted((WEB / "pages").glob("*.jsx")) \
            + sorted((WEB / "components").glob("*.jsx")):
        text = f.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "localhost:" in line and "import.meta.env" not in line:
                offenders.append(f"{f.name}:{i}")
    assert not offenders, (
        "localhost backend without an env-var override: " + ", ".join(offenders))


def test_the_officer_server_can_be_told_its_host_port_and_origins():
    """A container is handed a port and must listen on every interface; a deployed
    server must also name the site allowed to read a farmer's name back."""
    src = (ROOT / "services" / "broadcast_server.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT"' in src
    assert 'os.environ.get("BROADCAST_HOST"' in src
    assert 'BROADCAST_ALLOWED_ORIGINS' in src
    assert '"Access-Control-Allow-Origin", "*"' not in src, "CORS must not be a fixed wildcard"


def test_the_build_only_needs_the_two_packages_the_split_actually_imports():
    """The full requirements.txt is the geo/ML stack. A static host must not install it
    to run a JSON split — requirements-build.txt is what keeps that build small."""
    lines = [x.strip().lower() for x in
             (ROOT / "requirements-build.txt").read_text(encoding="utf-8").splitlines()]
    pkgs = [x for x in lines if x and not x.startswith("#")]   # the comments name them too
    assert "jsonschema" in pkgs and "referencing" in pkgs
    for heavy in ("xarray", "geopandas", "xgboost", "torch", "pandas"):
        assert not any(p.startswith(heavy) for p in pkgs), \
            f"{heavy} does not belong in the frontend build"
