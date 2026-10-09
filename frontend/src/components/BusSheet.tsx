import { useEffect, useState } from "react";
import { api } from "../api";
import { t, VERDICT_UI, type Lang } from "../i18n";
import type { BusImpact, Mode } from "../types";

/** Bus routes passing a spot that is risky / no-go for buses (likely diverted), or no-go on foot. */
export default function BusSheet({ mode, at, lang, onClose }: { mode: Mode; at?: number; lang: Lang; onClose: () => void }) {
  const [data, setData] = useState<BusImpact | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.busImpact(mode, mode === "demo" ? at : undefined).then(setData).catch((e) => setErr(String(e.message ?? e)));
  }, [mode, at]);

  return (
    <div className="sheet" role="dialog" aria-label="Bus routes affected">
      <header className="sheet-head">
        <h2>🚌 {lang === "hi" ? "प्रभावित बस रूट" : "Bus routes affected"}</h2>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}>✕</button>
      </header>
      {err && <p className="error-box">{err}</p>}
      {!data && !err && <div className="spinner" aria-hidden />}
      {data && data.routes_known === 0 && (
        <p className="muted">{lang === "hi" ? "इस शहर के बस रूट का डेटा अभी नहीं है।" : "No bus route data loaded for this city yet (import the city's GTFS feed)."}</p>
      )}
      {data && data.routes_known > 0 && data.affected.length === 0 && (
        <p>✅ {lang === "hi" ? `${data.routes_known} रूट जाँचे: कोई प्रभावित नहीं।` : `Checked ${data.routes_known} routes: none pass a flooded spot right now.`}</p>
      )}
      {data && data.affected.length > 0 && (
        <>
          <p className="small muted">{lang === "hi" ? `${data.routes_known} में से ${data.affected.length} रूट पानी भरी जगह से गुज़रते हैं।` : `${data.affected.length} of ${data.routes_known} routes pass a flooded spot. Expect diversions or delays.`}</p>
          <ul className="buslist">
            {data.affected.map((r) => (
              <li key={r.ref + r.name}>
                <span className={`busref ${VERDICT_UI[r.worst].cls}`}>{r.ref}</span>
                <strong>{r.name}</strong>
                <div className="small">
                  {r.spots.map((s) => (
                    <div key={s.spotId}>
                      {VERDICT_UI[s.bus].glyph} {s.place ?? "Flooded spot"} · ~{s.depth_high} cm
                      {s.bus === "NO_GO" ? (lang === "hi" ? " · बस नहीं जा सकती" : " · bus can't pass") : s.bus === "RISKY" ? (lang === "hi" ? " · धीरे" : " · slow / risky") : ""}
                      {s.pedestrian === "NO_GO" ? (lang === "hi" ? " · स्टॉप तक पैदल ख़तरनाक" : " · unsafe to walk to stops") : ""}
                      {s.predicted ? " 🌧" : ""}
                    </div>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="disclaimer">{lang === "hi" ? "बस रूट: GTFS/OpenStreetMap। वास्तविक डायवर्ज़न ट्रांसपोर्ट विभाग तय करता है।" : "Routes from GTFS / OpenStreetMap. Actual diversions are decided by the operator."}</p>
    </div>
  );
}
