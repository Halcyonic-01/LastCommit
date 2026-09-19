"""P3 acceptance: rules engine, advisory contract, message composition, web build."""

import json
import subprocess
import sys
from pathlib import Path

import re

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from varshadrishti import contract as c  # noqa: E402
from varshadrishti.rules import engine as E  # noqa: E402

FORECAST = ROOT / "forecast"
WEB = ROOT / "web"


def area(dry, heavy=0.10, onset=0.10, district=""):
    lead = lambda a: {"w1": a, "w2": a, "w3": a, "w4": a}  # noqa: E731
    return {
        "district_en": district, "p_onset": lead(onset), "p_false_onset": lead(0.10),
        "p_dry7": lead(dry), "p_dry14": lead(0.10), "p_heavy": lead(heavy),
        "onset_delay_weeks": 2.0,
    }


@pytest.fixture(scope="module")
def packs():
    return E.load_rules()


# --- the rules engine ------------------------------------------------------


@pytest.mark.parametrize(
    "name,a,expect_rule",
    [
        ("normal", area(0.10), "normal.continue"),
        ("mild dry spell", area(0.35), "dryspell.presowing.delay"),
        ("severe dry spell", area(0.60), "dryspell.presowing.switch_crop"),
        ("heavy rain", area(0.10, heavy=0.45), "heavyrain.drainage"),
    ],
)
def test_five_hand_made_scenarios(packs, name, a, expect_rule):
    ids = [x["rule_id"] for x in E.evaluate(a, packs=packs)]
    assert expect_rule in ids, f"{name}: got {ids}"


def test_district_plan_overrides_the_statewide_threshold(packs):
    """Tumakuru's own plan switches crop at 0.40; the statewide default waits for 0.45."""
    mid = 0.42
    tum = [x["rule_id"] for x in E.evaluate(area(mid, district="Tumakuru"), packs=packs)]
    other = [x["rule_id"] for x in E.evaluate(area(mid, district="Kolara"), packs=packs)]
    assert "dryspell.presowing.switch_crop" in tum
    assert "dryspell.presowing.switch_crop" not in other


def test_every_advisory_cites_a_table(packs):
    for dry in (0.10, 0.35, 0.60):
        for a in E.evaluate(area(dry), packs=packs):
            assert a["source"]["doc"], "advisory with no source document"
            assert a["source"]["table"], "advisory with no table"


def test_every_advisory_has_both_languages(packs):
    for dry in (0.10, 0.35, 0.60):
        for a in E.evaluate(area(dry), packs=packs):
            assert a["action_kn"].strip() and a["action_en"].strip()


def test_advisories_are_capped_and_severity_ordered(packs):
    out = E.evaluate(area(0.60, heavy=0.50), packs=packs)
    assert len(out) <= E.MAX_ADVISORIES
    order = [E.SEVERITY_ORDER[a["severity"]] for a in out]
    assert order == sorted(order), "advisories must lead with the most severe"


def test_conditions_cannot_execute_code():
    """A rules file is data. Anything that is not `<op> <number>` is refused."""
    for bad in ("__import__('os').system('true')", "0.5 if True else 0", ">= x", "eval(1)"):
        with pytest.raises(E.RuleError):
            E._cmp(0.5, bad)


def test_a_rule_referencing_an_unknown_fact_fails_loudly(packs):
    r = E.Rule(id="bad", crop="any", stage="any", severity="info", table="1",
               when={"p_nonexistent_w1": ">= 0.5"}, action_kn="x", action_en="x",
               reason_kn="", reason_en="", source_doc="d")
    with pytest.raises(E.RuleError):
        r.matches(E.facts_from(area(0.3)), "ragi", "pre_sowing")


def test_range_conditions_need_both_bounds(packs):
    """`[">= 0.30", "< 0.45"]` must exclude both sides, not just one."""
    rules = {r.id: r for r in packs[""]}
    delay = rules["dryspell.presowing.delay"]
    assert delay.matches(E.facts_from(area(0.35)), "ragi", "pre_sowing")
    assert not delay.matches(E.facts_from(area(0.20)), "ragi", "pre_sowing")
    assert not delay.matches(E.facts_from(area(0.60)), "ragi", "pre_sowing")


# --- rule output still satisfies the frozen contract -----------------------


def test_generated_forecast_is_contract_valid():
    c.load_and_validate(FORECAST / "latest.json", "forecast.schema.json")


def test_every_area_now_carries_an_advisory():
    latest = json.loads((FORECAST / "latest.json").read_text())
    missing = [k for k, a in latest["areas"].items() if not a.get("advisories")]
    assert not missing, f"{len(missing)} areas have no advisory"


def test_advisories_in_output_all_cite_a_real_crida_table():
    latest = json.loads((FORECAST / "latest.json").read_text())
    for a in latest["areas"].values():
        for adv in a["advisories"]:
            assert "CRIDA" in adv["source"]["doc"]
            assert adv["source"]["table"]


def test_rule_coverage_is_not_one_rule_for_everything():
    """If a single rule fires everywhere the thresholds are wrong, not the weather."""
    latest = json.loads((FORECAST / "latest.json").read_text())
    used = {adv["rule_id"] for a in latest["areas"].values() for adv in a["advisories"]}
    assert len(used) >= 3, f"only {used} fired across the whole state"


# --- the Telegram message --------------------------------------------------


def test_telegram_message_carries_the_decision_and_its_source():
    sys.path.insert(0, str(ROOT / "services" / "telegram"))
    import send  # noqa: PLC0415

    text = send.compose(FORECAST / "area" / "KGIS-H-180901.json")
    assert "ಬಿತ್ತನೆ" in text, "no Kannada sowing instruction"
    assert "CRIDA" in text, "no citation"
    assert "ಅಂದಾಜು" in text, "weeks 3-4 must be marked as outlook"
    assert "%" in text


# --- the built web app -----------------------------------------------------


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_build_ships_a_service_worker_and_manifest():
    for f in ("sw.js", "manifest.webmanifest", "index.html"):
        assert (WEB / "dist" / f).exists(), f"dist/{f} missing"


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_build_ships_the_data_the_app_reads():
    assert (WEB / "dist" / "forecast" / "latest.json").exists()
    assert (WEB / "dist" / "forecast" / "index.json").exists()
    assert len(list((WEB / "dist" / "forecast" / "area").glob("*.json"))) > 1000
    for layer in ("blocks", "hoblis", "districts"):
        assert (WEB / "dist" / "geo" / f"{layer}.geojson").exists()


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_service_worker_caches_what_the_farmer_needs_offline():
    """The offline promise in one assertion: the area file, the map and the shell."""
    sw = (WEB / "dist" / "sw.js").read_text()
    # the daily forecast may go stale but must never be missing
    assert 'StaleWhileRevalidate({cacheName:"forecast"' in sw
    # polygons never change between releases — serve them from cache first
    assert 'CacheFirst({cacheName:"geo"' in sw
    # a reload on any route must fall back to the app shell, not a 404
    assert 'createHandlerBoundToURL("index.html")' in sw


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_index_html_registers_the_service_worker():
    html = (WEB / "dist" / "index.html").read_text()
    assert "registerSW.js" in html, "the built page never registers the worker"
    assert (WEB / "dist" / "registerSW.js").exists()


# --- responsive layout ----------------------------------------------------


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_layout_reflows_instead_of_sitting_in_a_phone_sliver():
    """430px is right on a phone and broken on a laptop — the same markup must do both."""
    # the officer bundle ships its own stylesheet, so name the app one explicitly
    css = next((WEB / "dist" / "assets").glob("index-*.css")).read_text()
    flat = css.replace(" ", "")
    phone = re.search(r"\.shell\{[^}]*max-width:(\d+)px", flat)
    assert phone, "the phone column has no max-width"
    assert 380 <= int(phone.group(1)) <= 480, f"phone column is {phone.group(1)}px"
    assert "@media(min-width:900px)" in flat, "no desktop breakpoint"
    # at desktop the scroll area becomes a two-column grid and the tabs stop floating
    wide = flat.split("@media(min-width:900px)")[1]
    assert "grid-template-columns" in wide
    assert "position:static" in wide, "bottom tab bar must not stay sticky on desktop"
    # The scroll area fills the window, so the content has to grow into it or a
    # dead band opens above the tab bar. Columns stretch and the hero absorbs it.
    assert "align-items:stretch" in wide, "spread columns must stretch to equal height"
    raw_wide = css.split("@media (min-width: 900px)")[1]
    assert re.search(r"\.band\.-hero[^{]*\{[^}]*flex:1 1 auto", raw_wide), (
        "the hero photo must absorb the column's spare height")
    assert re.search(r"\.band\.-hero[^{]*\{[^}]*max-height", raw_wide), (
        "an uncapped hero crops a landscape photo into a slab on a tall window")


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_no_page_sets_layout_in_an_inline_style():
    """An inline `display` beats a media query — that is what broke every page once."""
    offenders = []
    for f in (WEB / "src" / "pages").glob("*.jsx"):
        src = f.read_text()
        for marker in ('className="spread', 'className="plate', 'className="band'):
            for line in src.splitlines():
                if marker in line and ("display:" in line or 'display: "' in line):
                    offenders.append(f"{f.name}: {line.strip()[:90]}")
    assert not offenders, "layout containers must take display from CSS:\n" + "\n".join(offenders)


@pytest.mark.skipif(not (WEB / "dist").exists(), reason="run `npm run build` in web/ first")
def test_base_rules_come_before_the_media_query():
    """A base rule written after @media silently overrides the desktop layout."""
    css = (WEB / "src" / "styles.css").read_text()
    first_media = css.index("@media (min-width: 900px)")
    # only classes that are restyled at the breakpoint can be clobbered this way
    for cls in (".shell {", ".tabs {", ".band {"):
        assert css.index(cls) < first_media, f"{cls} base rule sits after the media query"


# --- loose ends closed after the P3 review --------------------------------


def test_scratch_previews_are_not_in_the_repo_or_the_build():
    """Two design-scratch pages once shipped inside dist. Nothing unreferenced ships."""
    stray = [p for p in WEB.rglob("_bul*.html") if "node_modules" not in p.parts]
    assert not stray, f"scratch previews still present: {[str(p) for p in stray]}"


def test_full_size_photo_originals_are_ignored():
    """`.attic` holds the JPEGs the shipped .webp files were cut from — 4 MB git skips."""
    out = subprocess.run(["git", "check-ignore", ".attic/"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0, ".attic/ is not gitignored — 4 MB of originals would push"


def test_a_rain_report_is_stored_before_it_is_sent():
    """The tap happens in a field with no bars. Queue first, network second, never lose it."""
    store = (WEB / "src" / "lib" / "store.js").read_text()
    page = (WEB / "src" / "pages" / "RainReport.jsx").read_text()
    for fn in ("queueReport", "flushOutbox", "readOutbox"):
        assert f"export function {fn}" in store or f"export async function {fn}" in store, fn
    assert "onClick={submit}" in page, "the send button must not just flip a flag"
    assert "queueReport(" in page, "submit does not persist the report"
    # the confirmation may not claim "sent" — the report is on the phone until it drains
    assert "S.savedHere" in page and "S.willSend" in page


def test_a_failed_save_is_not_reported_as_success():
    """Private-window storage throws. The farmer must be told to tap again, not thanked."""
    store = (WEB / "src" / "lib" / "store.js").read_text()
    page = (WEB / "src" / "pages" / "RainReport.jsx").read_text()
    assert "return false;" in store, "writeOutbox must report a blocked write"
    assert 'sent === "stored"' in page and "S.notSaved" in page
    # and it says why, rather than repeating the headline back at the farmer
    assert "S.noSpace" in page


def test_queued_reports_drain_when_the_signal_returns():
    app = (WEB / "src" / "App.jsx").read_text()
    assert app.count("flushOutbox()") >= 2, "flush on the online event and once at boot"


def test_the_outbox_cannot_grow_without_bound():
    store = (WEB / "src" / "lib" / "store.js").read_text()
    assert re.search(r"MAX_QUEUED\s*=\s*\d+", store), "an unbounded queue fills the device"
    assert "slice(-MAX_QUEUED)" in store, "the cap must actually be applied on write"
