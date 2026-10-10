import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API, CITIES, setCity as setApiCity, WHATSAPP_JOIN, WHATSAPP_NUMBER } from "./api";
import BusSheet from "./components/BusSheet";
import DrainSheet from "./components/DrainSheet";
import DemoBar from "./components/DemoBar";
import MapView from "./components/MapView";
import ReportFlow from "./components/ReportFlow";
import RoutePanel from "./components/RoutePanel";
import SpotSheet from "./components/SpotSheet";
import { t, VEHICLES, VERDICT_UI, type Lang } from "./i18n";
import type { CompareRow, Hotspot, LonLat, Mode, Report, RouteResult, Spot, Vehicle, Weather } from "./types";
import { getPosition, store, stored } from "./util";

type Panel = { kind: "none" } | { kind: "report" } | { kind: "route" } | { kind: "spot"; spot: Spot } | { kind: "hotspot"; h: Hotspot } | { kind: "bus" } | { kind: "drains" };

// WhatsApp replies link here as ?city=..&lat=..&lon=..
const URLQ = new URLSearchParams(location.search);
const initialCity = (() => {
  const c = URLQ.get("city") || stored<string>("city", "delhi");
  return CITIES[c] ? c : "delhi";
})();
setApiCity(initialCity);

function RainBanner({ w, lang, city }: { w: Weather | null; lang: Lang; city: string }) {
  if (!w) return null;
  const name = CITIES[city][lang === "hi" ? "hi" : "label"];
  const cls = w.hotspotsAtRisk > 0 ? "storm" : w.rainPast3h >= 2 || w.maxRainNowAtHotspots >= 1 ? "wet" : "";
  const mins = Math.max(0, Math.round((Date.now() / 1000 - w.updatedAt) / 60));
  const text = lang === "hi"
    ? `${name}: पिछले 3 घंटे ${w.rainPast3h.toFixed(1)} मिमी · अभी ${w.rainNow.toFixed(1)} मिमी/घं · अगले 3 घंटे ${w.rainNext3h.toFixed(1)} मिमी${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} जगहें ख़तरे में` : ""}`
    : `${name}: ${w.rainPast3h.toFixed(1)} mm last 3 h · ${w.rainNow.toFixed(1)} mm/h now · ${w.rainNext3h.toFixed(1)} mm next 3 h${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} hotspots at risk` : ""}`;
  return (
    <div className={`banner rain small ${cls}`} title={w.source}>
      <span aria-hidden>{cls ? "🌧️" : "☀️"}</span>
      <span>{text} <span className="muted">· {mins} min</span></span>
    </div>
  );
}

export default function App() {
  const [vehicle, setVehicleState] = useState<Vehicle>(stored<Vehicle>("vehicle", "scooter"));
  const [lang, setLangState] = useState<Lang>(stored<Lang>("lang", "en"));
  const [mode, setMode] = useState<Mode>("live");
  const [spots, setSpots] = useState<Spot[]>([]);
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [weather, setWeather] = useState<Weather | null>(null);
  const [city, setCityState] = useState(initialCity);
  const [alt, setAltState] = useState<{ v: Vehicle | null; g: CompareRow["geometry"] | null }>({ v: null, g: null });
  const [panel, setPanel] = useState<Panel>({ kind: "none" });
  const [from, setFrom] = useState<LonLat | null>(null);
  const [to, setTo] = useState<LonLat | null>(null);
  const [picking, setPicking] = useState<"from" | "to" | null>(null);
  const [route, setRoute] = useState<RouteResult | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [err, setErr] = useState("");
  // demo replay
  const [timeline, setTimeline] = useState<{ start: number; end: number; reports: Report[] } | null>(null);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const urlPos: LonLat | null = URLQ.get("lat") && URLQ.get("lon") ? [Number(URLQ.get("lon")), Number(URLQ.get("lat"))] : null;
  const center = useMemo<LonLat>(() => (city === initialCity && urlPos) || CITIES[city].center, [city]); // eslint-disable-line react-hooks/exhaustive-deps

  function setCity(c: string) {
    setApiCity(c);
    store("city", c);
    setCityState(c);
    setSpots([]);
    setHotspots([]);
    setWeather(null);
    setRoute(null);
    setFrom(null);
    setTo(null);
    setTimeline(null);
    setAltState({ v: null, g: null });
    setPanel({ kind: "none" });
  }

  const setVehicle = (v: Vehicle) => { setVehicleState(v); store("vehicle", v); setRoute(null); setAltState({ v: null, g: null }); };
  const setLang = (l: Lang) => { setLangState(l); store("lang", l); document.documentElement.lang = l; };

  useEffect(() => {
    const on = () => setOffline(false), off = () => setOffline(true);
    addEventListener("online", on);
    addEventListener("offline", off);
    return () => { removeEventListener("online", on); removeEventListener("offline", off); };
  }, []);

  // hotspots + live rain, refreshed every 5 min
  useEffect(() => {
    if (!API) return;
    const load = () => api.hotspots().then((r) => { setHotspots(r.hotspots); setWeather(r.weather); }).catch(() => undefined);
    load();
    const id = setInterval(load, 5 * 60000);
    return () => clearInterval(id);
  }, [city]);

  // live spots: poll every 30 s
  const loadLive = useCallback(() => {
    api.spots("live").then((r) => { setSpots(r.spots); setErr(""); }).catch((e) => setErr(String(e.message ?? e)));
  }, []);
  useEffect(() => {
    if (mode !== "live" || !API) return;
    loadLive();
    const id = setInterval(loadLive, 30000);
    return () => clearInterval(id);
  }, [mode, loadLive, city]);

  // demo: load the archived timeline, then spots at the scrubbed time (debounced)
  useEffect(() => {
    if (mode !== "demo") return;
    setRoute(null);
    api.timeline().then((tl) => {
      if (!tl.start || !tl.end) return setErr("No demo reports seeded yet. Run scripts/seed_demo.py.");
      const t0 = tl.start - 10 * 60, t1 = tl.end + 60 * 60;
      setTimeline({ start: t0, end: t1, reports: tl.reports });
      setAt(t0);
    }).catch((e) => setErr(String(e.message ?? e)));
  }, [mode, city]);
  const debounce = useRef<number>();
  useEffect(() => {
    if (mode !== "demo" || !at) return;
    clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      api.spots("demo", at).then((r) => setSpots(r.spots)).catch(() => undefined);
    }, 200);
  }, [mode, at]);

  const known = useMemo(() => new Map((timeline?.reports ?? []).map((r) => [r.reportId, r])), [timeline]);

  function openRoute(dest?: LonLat) {
    setRoute(null);
    if (dest) setTo(dest);
    if (!from) getPosition().then(setFrom).catch(() => undefined);
    setPanel({ kind: "route" });
  }

  function onPick(p: LonLat) {
    if (picking === "from") setFrom(p);
    if (picking === "to") setTo(p);
    setPicking(null);
  }

  const worstCount = spots.filter((s) => s.verdicts[vehicle] === "NO_GO").length;

  return (
    <div className="app">
      <MapView center={center} spots={spots} hotspots={hotspots} vehicle={vehicle} lang={lang} route={route} altRoute={alt.g}
        from={panel.kind === "route" ? from : null} to={panel.kind === "route" ? to : null}
        picking={!!picking} onPick={onPick}
        onSpot={(s) => setPanel({ kind: "spot", spot: s })} onHotspot={(h) => setPanel({ kind: "hotspot", h })} />

      <header className="topbar">
        <div className="toprow">
          <div className="row gap">
            <span className="brand" aria-hidden>🌊</span>
            <select className="citysel" value={city} onChange={(e) => setCity(e.target.value)} aria-label="City">
              {Object.entries(CITIES).map(([k, c]) => <option key={k} value={k}>{lang === "hi" ? c.hi : c.label}</option>)}
            </select>
          </div>
          <div className="row gap">
            <div className="seg" role="radiogroup" aria-label="Mode">
              <button role="radio" aria-checked={mode === "live"} className={mode === "live" ? "on" : ""} onClick={() => setMode("live")}>● {t("live", lang)}</button>
              <button role="radio" aria-checked={mode === "demo"} className={mode === "demo" ? "on" : ""} onClick={() => setMode("demo")}>⏪ {t("demo", lang)}</button>
            </div>
            <button className="chip" onClick={() => setLang(lang === "en" ? "hi" : "en")} aria-label="Language">{lang === "en" ? "हिं" : "EN"}</button>
          </div>
        </div>
        <div className="vehicles" role="radiogroup" aria-label={t("imOn", lang)}>
          <span className="imon">{t("imOn", lang)}:</span>
          {VEHICLES.map((v) => (
            <button key={v.id} role="radio" aria-checked={vehicle === v.id} className={`vchip${vehicle === v.id ? " on" : ""}`} onClick={() => setVehicle(v.id)}>
              <span aria-hidden>{v.icon}</span> {v[lang]}
            </button>
          ))}
        </div>
        <div className="legend" aria-hidden>
          {(["GO", "RISKY", "NO_GO"] as const).map((k) => (
            <span key={k} className={`lg ${VERDICT_UI[k].cls}`}><i>{VERDICT_UI[k].glyph}</i> {VERDICT_UI[k][lang]}</span>
          ))}
          <span className="lg ringlg"><i /> {lang === "hi" ? "अक्सर भरता है" : "Floods often"}</span>
          <span className="muted">· {t("legend", lang)}</span>
        </div>
        {mode === "live" && <RainBanner w={weather} lang={lang} city={city} />}
        {offline && <div className="banner warn">📴 {t("offline", lang)}</div>}
        {!API && <div className="banner warn">{t("noApi", lang)}: set VITE_API_URL</div>}
        {err && API && <div className="banner warn" onClick={() => setErr("")}>{err}</div>}
                {spots.length > 0 && panel.kind === "none" && (
          <div className="banner info small">{worstCount} {lang === "hi" ? "जगहें आपकी सवारी के लिए बंद" : `spot${worstCount === 1 ? "" : "s"} NO-GO for your vehicle`} · {spots.length} {lang === "hi" ? "कुल" : "total"}</div>
        )}
      </header>

      {panel.kind === "none" && (
        <div className={`fabs${mode === "demo" ? " above-demo" : ""}`}>
          {mode === "live" && <button className="fab primary" onClick={() => setPanel({ kind: "report" })}>📷 {t("report", lang)}</button>}
          <button className="fab" onClick={() => openRoute()}>🧭 {t("safeRoute", lang)}</button>
          {vehicle === "bus" && <button className="fab" onClick={() => setPanel({ kind: "bus" })} aria-label="Bus routes affected">🚌</button>}
          {mode === "live" && <button className="fab" style={{ flex: "0 0 auto" }} onClick={() => setPanel({ kind: "drains" })} aria-label="Blocked drains">🕳️</button>}
          {mode === "live" && WHATSAPP_NUMBER && (
            <a className="fab wa" style={{ flex: "0 0 auto", textDecoration: "none", display: "grid", placeItems: "center" }}
              href={`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(WHATSAPP_JOIN || "hi")}`} target="_blank" rel="noreferrer"
              aria-label={lang === "hi" ? "WhatsApp से रिपोर्ट करें" : "Report on WhatsApp"}>💬</a>
          )}
        </div>
      )}

      {mode === "demo" && timeline && panel.kind !== "report" && (
        <DemoBar start={timeline.start} end={timeline.end} at={at} setAt={setAt} playing={playing} setPlaying={setPlaying} lang={lang} count={spots.length} />
      )}

      {panel.kind === "report" && (
        <ReportFlow fallbackCenter={center} vehicle={vehicle} lang={lang} setLang={setLang}
          onClose={() => setPanel({ kind: "none" })} onDone={loadLive} onRoute={(p) => openRoute(p)} />
      )}
      {panel.kind === "spot" && (
        <SpotSheet spot={panel.spot} mode={mode} known={known} vehicle={vehicle} lang={lang} setLang={setLang}
          onClose={() => setPanel({ kind: "none" })} onRoute={(p) => openRoute(p)} />
      )}
      {panel.kind === "route" && (
        <RoutePanel vehicle={vehicle} lang={lang} mode={mode} at={at} center={center} from={from} to={to} setFrom={setFrom} setTo={setTo}
          picking={picking} setPicking={setPicking} result={route} setResult={setRoute}
          alt={alt.v} setAlt={(v, g) => setAltState({ v, g })}
          onClose={() => { setPanel({ kind: "none" }); setRoute(null); setPicking(null); setAltState({ v: null, g: null }); }} />
      )}
      {panel.kind === "drains" && <DrainSheet lang={lang} center={center} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "bus" && <BusSheet mode={mode} at={at} lang={lang} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "hotspot" && (
        <div className="sheet" role="dialog" aria-label={panel.h.name}>
          <header className="sheet-head">
            <h2>◯ {lang === "hi" ? panel.h.name_hi ?? panel.h.name : panel.h.name}</h2>
            <button className="icon-btn" onClick={() => setPanel({ kind: "none" })} aria-label={t("close", lang)}>✕</button>
          </header>
          <p>{t("hotspot", lang)}.</p>
          {panel.h.risk === "likely_flooded_soon" && <div className="banner warn">🌧️ {t("rainSoon", lang)} ({Math.round(panel.h.rainNext3h ?? 0)} mm {lang === "hi" ? "अगले 3 घंटे" : "next 3 h"})</div>}
          {panel.h.rainPast3h != null && (
            <p className="small">{lang === "hi" ? "बारिश" : "Rain"}: {panel.h.rainPast3h.toFixed(1)} mm {lang === "hi" ? "पिछले 3 घंटे" : "last 3 h"} · {(panel.h.rainNext3h ?? 0).toFixed(1)} mm {lang === "hi" ? "अगले 3 घंटे" : "next 3 h"}</p>
          )}
          <p className="muted small">{lang === "hi" ? "अभी कोई लाइव रिपोर्ट नहीं। अंडरपास सबसे पहले भरते हैं — जाने से पहले जाँचें।" : "No live report here right now. Underpasses flood first, so check before entering."}</p>
          {panel.h.source_url && (
            <p className="small">
              {lang === "hi" ? "स्रोत (समाचार)" : "Ground truth"}: <a href={panel.h.source_url} target="_blank" rel="noreferrer">{new URL(panel.h.source_url).hostname.replace("www.", "")}</a>
              {panel.h.osm_match && <><br /><span className="muted">{lang === "hi" ? "स्थान" : "Location"}: {panel.h.osm_match}</span></>}
            </p>
          )}
          <div className="actions"><button className="btn primary" onClick={() => openRoute([panel.h.lon, panel.h.lat])}>🧭 {t("routeFromHere", lang)}</button></div>
        </div>
      )}
    </div>
  );
}
