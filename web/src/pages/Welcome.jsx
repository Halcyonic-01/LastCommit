import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getIndex } from "../lib/api.js";
import { loadPrefs, savePrefs } from "../lib/store.js";
import { LANGS, S, t } from "../i18n/strings.js";
import Photo from "../components/Photo.jsx";
import Speak from "../components/Speak.jsx";
import { Shell } from "../components/Frame.jsx";
import { Fwd, Pin, Tick } from "../components/Marks.jsx";

export default function Welcome() {
  const nav = useNavigate();
  const p0 = loadPrefs();
  const [lang, setLang] = useState(p0.lang);
  const [areaId, setAreaId] = useState(p0.areaId);
  const [areas, setAreas] = useState(null);

  useEffect(() => { getIndex().then((d) => setAreas(d.areas)).catch(() => setAreas({})); }, []);

  // Keep the list short for a slow phone, but never drop the selected one —
  // a <select> whose value is absent silently shows the first option instead.
  const all = areas ? Object.entries(areas).filter(([, a]) => a.level === "panchayat") : [];
  const list = all.length > 400
    ? [...all.filter(([id]) => id === areaId), ...all.filter(([id]) => id !== areaId).slice(0, 400)]
    : all;

  // KGIS ships no Kannada name for hoblis, but their parent taluk and district
  // have one. Resolve them here so a Kannada reader still gets a place they know.
  const go = () => {
    const a = areas?.[areaId];
    const taluk = a?.parent_id ? areas?.[a.parent_id] : null;
    const district = Object.values(areas ?? {}).find(
      (x) => x.level === "district" && x.district_en === a?.district_en);
    savePrefs({
      lang, areaId, onboarded: true,
      place: {
        taluk_kn: taluk?.name_kn ?? "", taluk_en: taluk?.name_en ?? "",
        district_kn: district?.name_kn ?? "",
      },
    });
    nav("/today");
  };

  return (
    <Shell>
      {/* The land itself opens the app — ploughed, furrowed, nothing sown yet.
          That is the question this product answers, stated as a picture. */}
      <Photo name="land" lang={lang} className="-hero -tall">
        <div className="on-photo">
          <div style={{ borderLeft: "3px solid var(--ink-on-photo)", paddingLeft: 12 }}>
            <div className="kn" style={{ fontSize: 34, fontWeight: 800, lineHeight: 1.05 }}>{S.app[lang] ?? S.app.en}</div>
            <div className="kn" style={{ fontSize: 15.5, fontWeight: 500, marginTop: 3, opacity: .92 }}>{S.tagline[lang] ?? S.tagline.en}</div>
          </div>
        </div>
      </Photo>

      <div className="grow pad" style={{ paddingTop: 22, paddingBottom: 18, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div className="rubric">Language · ಭಾಷೆ</div>
            <div className="h2" style={{ marginTop: 2 }}>{t("pickLang", lang)}</div>
          </div>
          <Speak text={S.pickLang.kn} lang={lang} variant="icon" />
        </div>

        {/* Four plates, each set in its own script at display size. The script is
            the label — nothing here needs to be read in another language first. */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, background: "var(--rule2)", border: "1px solid var(--rule2)", marginTop: 12 }}>
          {LANGS.map((l) => {
            const on = lang === l.code;
            return (
              <button key={l.code} type="button" onClick={() => setLang(l.code)} aria-pressed={on}
                style={{ background: on ? "var(--ink)" : "var(--paper2)", color: on ? "var(--paper2)" : "var(--ink)",
                  minHeight: 88, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2, position: "relative" }}>
                <span className="kn" style={{ fontSize: 27, fontWeight: 700, lineHeight: 1.15 }}>{l.script}</span>
                <span style={{ fontSize: 10.5, letterSpacing: ".08em", textTransform: "uppercase", opacity: .62 }}>{l.en}</span>
                {on ? <span style={{ position: "absolute", top: 9, right: 9 }}><Tick size={16} /></span> : null}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop: 26 }}>
          <div className="rubric">Location · ಸ್ಥಳ</div>
          <div className="h2" style={{ marginTop: 2, display: "flex", alignItems: "center", gap: 7 }}>
            <Pin size={19} /> {t("pickPlace", lang)}
          </div>
          <select value={areaId} onChange={(e) => setAreaId(e.target.value)} aria-label={t("pickPlace", lang)}
            style={{ marginTop: 10, width: "100%", minHeight: "var(--tap)", border: "1.5px solid var(--ink)", borderRadius: 2,
              padding: "0 12px", fontSize: 17, fontFamily: "var(--kn)", fontWeight: 600, background: "var(--paper2)" }}>
            {list.map(([id, a]) => (
              <option key={id} value={id}>{a.name_kn || a.name_en} — {a.name_en}{a.district_en ? ` (${a.district_en})` : ""}</option>
            ))}
          </select>
          <div className="gloss" style={{ marginTop: 6 }}>
            {list.length ? `${list.length} hoblis · your choice stays on this phone` : "loading hoblis…"}
          </div>
        </div>

        <div style={{ marginTop: "auto", paddingTop: 24 }}>
          <button type="button" className="btn" onClick={go}>
            {t("start", lang)} <Fwd size={21} sw={2.6} />
          </button>
        </div>
      </div>
    </Shell>
  );
}
