import { Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState, lazy, Suspense } from "react";
import Welcome from "./pages/Welcome.jsx";
import Today from "./pages/Today.jsx";
import Why from "./pages/Why.jsx";
import RainReport from "./pages/RainReport.jsx";

import { loadPrefs, flushOutbox } from "./lib/store.js";
import { t } from "./i18n/strings.js";

// The officer tools pull in MapLibre — ~290 kB gzipped. Splitting them out keeps
// that off a farmer's 2G connection entirely; it only loads if an officer asks.
const Officer = lazy(() => import("./pages/Officer.jsx"));
const Verify  = lazy(() => import("./pages/Verify.jsx"));
const Ops = ({ children }) => (
  <Suspense fallback={<div className="ops" style={{ padding: 20, fontSize: 13 }}>Loading operations tools…</div>}>
    {children}
  </Suspense>
);

/** Once a farmer has chosen a language and a hobli, the app opens on the decision. */
const Entry = () => (loadPrefs().onboarded ? <Navigate to="/today" replace /> : <Welcome />);

export default function App() {
  const [offline, setOffline] = useState(!navigator.onLine);
  const { lang } = loadPrefs();

  useEffect(() => {
    // Signal returning is the only reliable moment to drain queued rain reports.
    const on = () => { setOffline(false); flushOutbox(); };
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    flushOutbox();  // and once at boot, for reports queued in a previous session
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  return (
    <>
      {offline ? <div className="offline" role="status">{t("offline", lang)}</div> : null}
      <Routes>
        <Route path="/" element={<Entry />} />
        <Route path="/welcome" element={<Welcome />} />
        <Route path="/today" element={<Today />} />
        <Route path="/why" element={<Why />} />
        <Route path="/rain" element={<RainReport />} />
        <Route path="/officer" element={<Ops><Officer /></Ops>} />
        <Route path="/verify" element={<Ops><Verify /></Ops>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
