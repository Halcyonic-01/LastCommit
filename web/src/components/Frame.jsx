import { t } from "../i18n/strings.js";

export const Shell = ({ children, className = "" }) => <div className={`shell ${className}`}>{children}</div>;

export const Msg = ({ kind, lang = "kn", detail }) => (
  <div className="grow pad" style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 6, textAlign: "center" }}>
    <div className="h1">{t(kind, lang)}</div>
    {detail ? <div className="gloss">{detail}</div> : null}
  </div>
);

/** The printed-form label that opens a block. Kannada word, English rubric above it. */
export const Rubric = ({ children, en }) => (
  <div style={{ marginBottom: 8 }}>
    {en ? <div className="rubric">{en}</div> : null}
    <div className="h2" style={{ marginTop: 2 }}>{children}</div>
  </div>
);
