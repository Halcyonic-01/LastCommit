import { useState } from "react";
import { photo } from "../lib/photos.js";
import { pick } from "../i18n/strings.js";

/** A photo band. The LQIP paints on the first frame so a 2G phone never shows
 *  an empty rectangle; the WebP fades in over it when it lands.
 *  `scrim` darkens the foot of the image and belongs only where text sits on it —
 *  a figure in an article gets the photograph undimmed. */
export default function Photo({ name, lang = "kn", height, className = "", children,
                                scrim = true, credit = true }) {
  const p = photo(name);
  const [on, setOn] = useState(false);
  return (
    <figure className={`band ${className}`} style={{ height, margin: 0 }}>
      <img className="lqip" src={p.lqip} alt="" aria-hidden="true" />
      <img
        className={`real${on ? " in" : ""}`}
        src={p.src}
        alt={pick(p.alt, lang)}
        loading={className.includes("-hero") ? "eager" : "lazy"}
        decoding="async"
        onLoad={() => setOn(true)}
      />
      {scrim ? <div className="scrim" /> : null}
      {credit ? <figcaption className="credit">{p.credit} · {p.licence}</figcaption> : null}
      {children}
    </figure>
  );
}
