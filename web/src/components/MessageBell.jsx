import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { supabase } from "../lib/supabase.js";
import { lastSeen, newestMessageAt } from "../lib/messages.js";
import { t } from "../i18n/strings.js";
import { Bell } from "./Marks.jsx";

// The tab bar is three destinations and stays three — that is a deliberate low-literacy
// finding, not an oversight (see Tabs.jsx). Officer messages are occasional rather than
// a place you go, so they hang off the header with a dot when there is something new.
export default function MessageBell({ areaId, lang = "kn" }) {
  const [unread, setUnread] = useState(false);

  useEffect(() => {
    let live = true;
    newestMessageAt(supabase, areaId)
      .then((newest) => { if (live && newest) setUnread(newest > lastSeen()); })
      .catch(() => {});  // no Supabase, or offline — simply no badge
    return () => { live = false; };
  }, [areaId]);

  return (
    <Link to="/messages" aria-label={t("messages", lang)}
      style={{ position: "relative", display: "flex", color: "var(--ink)", padding: 2 }}>
      <Bell size={21} />
      {unread ? (
        <span aria-hidden="true" style={{ position: "absolute", top: 0, right: 0, width: 9, height: 9,
          borderRadius: 5, background: "var(--risk)", border: "1.5px solid var(--paper)" }} />
      ) : null}
    </Link>
  );
}
