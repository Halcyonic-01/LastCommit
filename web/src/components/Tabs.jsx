import { NavLink } from "react-router-dom";
import { Ear, Cloud, Sun } from "./Marks.jsx";
import { t } from "../i18n/strings.js";

/** Three destinations, never more. Same three on every screen — the "consistent,
 *  always-visible help" finding from the low-literacy interface studies. */
export default function Tabs({ lang = "kn" }) {
  const items = [
    { to: "/today", Mark: Sun,   key: "today" },
    { to: "/rain",  Mark: Cloud, key: "rainReport" },
    { to: "/why",   Mark: Ear,   key: "why" },
  ];
  return (
    <nav className="tabs" aria-label="Main">
      {items.map(({ to, Mark, key }) => (
        <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "on" : "")}>
          <Mark size={23} />
          <span className="lbl">{t(key, lang)}</span>
        </NavLink>
      ))}
    </nav>
  );
}
