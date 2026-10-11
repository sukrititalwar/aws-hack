import { Bus, Camera, CloudRain, FlaskConical, Layers, MessageCircle, Monitor, Moon, Navigation, Shield, Sun, TriangleAlert, UserRound, Waves, WifiOff, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API, CITIES, setCity as setApiCity, WHATSAPP_JOIN, WHATSAPP_NUMBER } from "./api";
import AccountSheet from "./components/AccountSheet";
import BusSheet from "./components/BusSheet";
import { authEnabled, useAuth } from "./auth";
import DemoBar from "./components/DemoBar";
import DrainSheet from "./components/DrainSheet";
import MapRoot from "./components/MapRoot";
import RainPanel from "./components/RainPanel";
import ReportFlow from "./components/ReportFlow";
import RoutePanel from "./components/RoutePanel";
import SimPanel from "./components/SimPanel";
import SpotSheet from "./components/SpotSheet";
import { t, VEHICLES, type Lang } from "./i18n";
import { VehicleIcon, VerdictIcon } from "./icons";
import type { CompareRow, CoverageArea, Hotspot, LonLat, Mode, RainCity, RainIndia, Report, RouteResult, SimPayload, Spot, Theme, Vehicle, Weather } from "./types";

const NO_REPORTS = new Map<string, Report>();   // spot details come from the spot itself
const INDIA_BOUNDS: [number, number, number, number] = [68.2, 6.0, 97.6, 35.8];
import { getPosition, store, stored } from "./util";

type Panel = { kind: "none" } | { kind: "report" } | { kind: "route" } | { kind: "spot"; spot: Spot } | { kind: "hotspot"; h: Hotspot } | { kind: "bus" } | { kind: "drains" } | { kind: "account" } | { kind: "rain" } | { kind: "sim" };

// WhatsApp replies link here as ?city=..&lat=..&lon=..
const URLQ = new URLSearchParams(location.search);
const initialCity = (() => {
  const c = URLQ.get("city") || stored<string>("city", "delhi");
  return CITIES[c] ? c : "delhi";
})();
setApiCity(initialCity);

/** Compact live-rain status for the toolbar. Full numbers are in the tooltip / screen-reader label. */
function RainStatus({ w, lang, city, onOpen }: { w: Weather | null; lang: Lang; city: string; onOpen: () => void }) {
  if (!w) return null;
  const name = CITIES[city][lang === "hi" ? "hi" : "label"];
  const sim = !!w.simulated;
  const cls = w.hotspotsAtRisk > 0 ? "storm" : w.rainPast3h >= 2 || w.maxRainNowAtHotspots >= 1 ? "wet" : "";
  const mins = Math.max(0, Math.round((Date.now() / 1000 - w.updatedAt) / 60));
  const full = lang === "hi"
    ? `${name}: पिछले 3 घंटे ${w.rainPast3h.toFixed(1)} मिमी · अभी ${w.rainNow.toFixed(1)} मिमी/घं · अगले 3 घंटे ${w.rainNext3h.toFixed(1)} मिमी${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} जगहें ख़तरे में` : ""} · ${mins} मिनट पहले`
    : `${name}: ${w.rainPast3h.toFixed(1)} mm last 3 h · ${w.rainNow.toFixed(1)} mm/h now · ${w.rainNext3h.toFixed(1)} mm next 3 h${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} hotspots at risk` : ""} · updated ${mins} min ago`;
  const Icon = cls ? CloudRain : Sun;
  return (
    <button type="button" className={`rainpill ${cls}${sim ? " sim" : ""}`} onClick={onOpen}
      title={`${full}\n${w.source}\n${lang === "hi" ? "पूरे भारत में बारिश देखें" : "Tap to see where it is raining across India"}`} aria-label={`${full}. ${lang === "hi" ? "पूरे भारत में बारिश देखें" : "Open rain across India"}`}>
      <Icon size={16} aria-hidden />
      {sim && <span className="simtag inline">DEMO</span>}
      <span>{w.rainNow.toFixed(1)} mm/h</span>
      <span className="rp-extra">· {w.rainNext3h.toFixed(0)} mm {lang === "hi" ? "अगले 3 घं" : "next 3 h"}</span>
      {w.hotspotsAtRisk > 0 && <span className="rp-risk">{w.hotspotsAtRisk} {lang === "hi" ? "ख़तरे में" : "at risk"}</span>}
      {!sim && <span className="rp-age">{mins}m</span>}
    </button>
  );
}

/** Map legend: colour + icon + words, collapsible so it never covers the map on a phone. */
function Legend({ lang, raised }: { lang: Lang; raised: boolean }) {
  const [open, setOpen] = useState(() => window.matchMedia?.("(min-width: 760px)").matches ?? false);
  const hi = lang === "hi";
  const rows: [React.ReactNode, string][] = [
    [<span className="lg-dot go"><VerdictIcon cls="go" size={12} /></span>, hi ? "पार कर सकते हैं" : "Passable for your vehicle"],
    [<span className="lg-dot risky"><VerdictIcon cls="risky" size={12} /></span>, hi ? "जोखिम भरा" : "Potentially unsafe"],
    [<span className="lg-dot nogo"><VerdictIcon cls="nogo" size={12} /></span>, hi ? "असुरक्षित" : "Unsafe"],
    [<span className="lg-dot risky"><VerdictIcon cls="risky" glyph="?" size={12} /></span>, hi ? "जाँच ज़रूरी (अनिश्चित)" : "Requires inspection (unsure)"],
    [<span className="lg-dot dashed" />, hi ? "बारिश से अनुमान" : "Predicted from rain, no photo yet"],
    [<span className="lg-ring" />, hi ? "अक्सर भरता है" : "Floods often (news-cited)"],
    [<span className="lg-badges"><CloudRain size={13} /><Shield size={13} /><MessageCircle size={13} /></span>, hi ? "बारिश · आधिकारिक · सोशल" : "Rain · official · social source"],
  ];
  return (
    <div className={`legend-ctl${raised ? " raised" : ""}`}>
      {open ? (
        <div className="legend-card" role="region" aria-label={hi ? "संकेत" : "Map legend"}>
          <div className="legend-head">
            <strong>{hi ? "आपकी सवारी के लिए" : "For your vehicle"}</strong>
            <button className="icon-btn sm" onClick={() => setOpen(false)} aria-label={t("close", lang)}><X size={16} /></button>
          </div>
          <ul>{rows.map(([icon, label]) => <li key={label}>{icon}<span>{label}</span></li>)}</ul>
        </div>
      ) : (
        <button className="legend-btn" onClick={() => setOpen(true)} aria-expanded={false}>
          <Layers size={18} aria-hidden /> {hi ? "संकेत" : "Legend"}
        </button>
      )}
    </div>
  );
}

const THEME_NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<Theme, { en: string; hi: string }> = {
  system: { en: "Theme: match device", hi: "थीम: डिवाइस जैसी" },
  light: { en: "Theme: light", hi: "थीम: लाइट" },
  dark: { en: "Theme: dark", hi: "थीम: डार्क" },
};
const darkQuery = () => window.matchMedia?.("(prefers-color-scheme: dark)");

/** Light / dark / match-device. The choice is applied as <html data-theme>, which the CSS tokens follow. */
function useTheme() {
  const [theme, setThemeState] = useState<Theme>(stored<Theme>("theme", "system"));
  const [deviceDark, setDeviceDark] = useState(() => darkQuery()?.matches ?? false);
  useEffect(() => {
    const q = darkQuery();
    if (!q) return;
    const on = (e: MediaQueryListEvent) => setDeviceDark(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);
  const setTheme = (t: Theme) => { setThemeState(t); store("theme", t); };
  return { theme, setTheme, dark: theme === "dark" || (theme === "system" && deviceDark) };
}

export default function App() {
  const { theme, setTheme, dark } = useTheme();
  const { user } = useAuth();
  const [coverage, setCoverage] = useState<CoverageArea[] | null>(null);
  const [vehicle, setVehicleState] = useState<Vehicle>(stored<Vehicle>("vehicle", "scooter"));
  const [lang, setLangState] = useState<Lang>(stored<Lang>("lang", "en"));
  const [mode, setModeState] = useState<Mode>("live");
  const [sim, setSim] = useState<SimPayload | null>(null);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rain, setRain] = useState<RainIndia | null>(null);
  const [rainErr, setRainErr] = useState("");
  const [rainSel, setRainSel] = useState<string | null>(null);
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
    if (!API || mode === "sim") return;
    const load = () => api.hotspots().then((r) => { setHotspots(r.hotspots); setWeather(r.weather); }).catch(() => undefined);
    load();
    const id = setInterval(load, 5 * 60000);
    return () => clearInterval(id);
  }, [city, mode]);

  // "where is it raining across India": load while the panel is open, refresh every 5 min
  useEffect(() => {
    if (panel.kind !== "rain" || !API) return;
    const load = () => api.rainIndia().then((r) => { setRain(r); setRainErr(""); }).catch((e) => setRainErr(String(e.message ?? e)));
    load();
    const id = setInterval(load, 5 * 60000);
    return () => clearInterval(id);
  }, [panel.kind]);

  // live spots: poll every 30 s
  const loadLive = useCallback(() => {
    api.spots("live").then((r) => { setSpots(r.spots); setErr(""); }).catch((e) => setErr(String(e.message ?? e)));
  }, []);
  useEffect(() => {
    if (!API || mode === "sim") return;
    loadLive();
    const id = setInterval(loadLive, 30000);
    return () => clearInterval(id);
  }, [loadLive, city, mode]);

  // DEMO storm: load once when entering, then follow the time slider (debounced)
  useEffect(() => {
    if (mode !== "sim" || !API) return;
    let off = false;
    api.simulation().then((r) => { if (!off) { setSim(r); setSpots(r.spots); setWeather(r.weather); setErr(""); setAt(r.scenario.start + 90 * 60); } })
      .catch((e) => { if (!off) setErr(String(e.message ?? e)); });
    return () => { off = true; };
  }, [mode]);
  useEffect(() => {
    if (mode !== "sim" || !API || !at) return;
    let off = false;
    const id = setTimeout(() => {
      api.simulation(at).then((r) => { if (!off) { setSim(r); setSpots(r.spots); setWeather(r.weather); setErr(""); } })
        .catch((e) => { if (!off) setErr(String(e.message ?? e)); });
    }, 150);
    return () => { off = true; clearTimeout(id); };
  }, [at, mode]);

  function setMode(m: Mode) {
    if (m === mode) return;
    setPlaying(false);
    if (m === "sim" && city !== "delhi") setCity("delhi");
    else { setSpots([]); setWeather(null); setRoute(null); setAltState({ v: null, g: null }); setPanel({ kind: "none" }); }
    if (m === "live") { setSim(null); setAt(0); setHotspots([]); }
    setModeState(m);
  }


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
      <MapRoot center={center} spots={panel.kind === "rain" ? [] : spots} hotspots={panel.kind === "rain" || mode === "sim" ? [] : hotspots} vehicle={vehicle}
        rainPoints={panel.kind === "rain" ? rain?.cities ?? null : null} viewBounds={panel.kind === "rain" ? INDIA_BOUNDS : null}
        onRainPoint={(c: RainCity) => setRainSel(c.key)} lang={lang} route={route} altRoute={alt.g}
        from={panel.kind === "route" ? from : null} to={panel.kind === "route" ? to : null}
        picking={!!picking} onPick={onPick} dark={dark} coverage={panel.kind === "route" ? coverage : null}
        onSpot={(s) => setPanel({ kind: "spot", spot: s })} onHotspot={(h) => setPanel({ kind: "hotspot", h })} />

      <header className="topbar">
        <div className="toolbar">
          <span className="brand" title="Can My Scooter Cross?"><Waves size={20} aria-hidden /><span className="brand-name">Can My Scooter Cross?</span></span>
          <select className="citysel" value={city} onChange={(e) => setCity(e.target.value)} aria-label="City" disabled={mode === "sim"}>
            {Object.entries(CITIES).map(([k, c]) => <option key={k} value={k}>{lang === "hi" ? c.hi : c.label}</option>)}
          </select>
          <div className="seg" role="radiogroup" aria-label="Mode">
            <button role="radio" aria-checked={mode === "live"} className={mode === "live" ? "on" : ""} onClick={() => setMode("live")}>{t("live", lang)}</button>
            <button role="radio" aria-checked={mode === "sim"} className={`simbtn${mode === "sim" ? " on" : ""}`} onClick={() => setMode("sim")}><FlaskConical size={14} aria-hidden /> {t("demo", lang)}</button>
          </div>
          <RainStatus w={weather} lang={lang} city={city} onOpen={() => { if (mode === "sim") { setPanel({ kind: "sim" }); return; } setRainSel(null); setPanel({ kind: "rain" }); }} />
          <span className="spacer" />
          <button className="chip icon-chip" onClick={() => setTheme(THEME_NEXT[theme])} aria-label={THEME_LABEL[theme][lang]} title={THEME_LABEL[theme][lang]}>
            {theme === "light" ? <Sun size={17} /> : theme === "dark" ? <Moon size={17} /> : <Monitor size={17} />}
          </button>
          <button className="chip lang" onClick={() => setLang(lang === "en" ? "hi" : "en")} aria-label="Language">{lang === "en" ? "हिं" : "EN"}</button>
          {authEnabled && (
            <button className={`chip icon-chip${user ? " signed" : ""}`} onClick={() => setPanel({ kind: "account" })}
              aria-label={user ? `${lang === "hi" ? "खाता" : "Account"}: ${user.email}` : lang === "hi" ? "साइन इन" : "Sign in"}
              title={user ? user.email : lang === "hi" ? "साइन इन" : "Sign in"}>
              <UserRound size={17} />
            </button>
          )}
        </div>
        <div className="vehicles" role="radiogroup" aria-label={t("imOn", lang)}>
          {VEHICLES.map((v) => (
            <button key={v.id} role="radio" aria-checked={vehicle === v.id} className={`vchip${vehicle === v.id ? " on" : ""}`} onClick={() => setVehicle(v.id)}>
              <VehicleIcon v={v.id} size={18} /> <span>{v[lang]}</span>
            </button>
          ))}
        </div>
        {mode === "sim" && (
          <button className="banner sim" onClick={() => setPanel({ kind: "sim" })}>
            <FlaskConical size={16} aria-hidden />
            <span><strong>{lang === "hi" ? "डेमो" : "DEMO"}</strong> — {lang === "hi" ? "हर मान डेमो के लिए बनाया गया है। ये असली रिपोर्ट नहीं हैं।" : "Every value is made up for a demo. These are not real reports."}</span>
          </button>
        )}
        {offline && <div className="banner warn"><WifiOff size={16} aria-hidden /> {t("offline", lang)}</div>}
        {!API && <div className="banner warn">{t("noApi", lang)}: set VITE_API_URL</div>}
        {err && API && <button className="banner warn" onClick={() => setErr("")}><TriangleAlert size={16} aria-hidden /> {err}</button>}
        {spots.length > 0 && panel.kind === "none" && (
          <div className={`statuspill${worstCount ? " nogo" : ""}`} role="status">
            {worstCount > 0 && <VerdictIcon cls="nogo" size={14} />}
            {worstCount} {lang === "hi" ? "जगहें आपकी सवारी के लिए असुरक्षित" : `unsafe for ${VEHICLES.find((v) => v.id === vehicle)!.en.toLowerCase()}`} · {spots.length} {lang === "hi" ? "कुल रिपोर्ट" : "reported"}
          </div>
        )}
      </header>

      {panel.kind === "none" && <Legend lang={lang} raised={mode === "sim"} />}
      {mode === "sim" && sim && (panel.kind === "none" || panel.kind === "spot") && (
        <DemoBar start={sim.scenario.start} end={sim.scenario.end} at={at || sim.now} setAt={setAt} playing={playing} setPlaying={setPlaying}
          lang={lang} count={spots.length} simulated />
      )}

      {panel.kind === "none" && (
        <div className={`fabs${mode === "sim" ? " above-demo" : ""}`}>
          {mode === "live" && <button className="fab primary" onClick={() => setPanel({ kind: "report" })}><Camera size={20} aria-hidden /> {t("report", lang)}</button>}
          <button className="fab" onClick={() => openRoute()}><Navigation size={20} aria-hidden /> {t("safeRoute", lang)}</button>
          {vehicle === "bus" && <button className="fab round" onClick={() => setPanel({ kind: "bus" })} aria-label="Bus routes affected" title="Bus routes affected"><Bus size={20} /></button>}
          {mode === "live" && <button className="fab round" onClick={() => setPanel({ kind: "drains" })} aria-label={t("drains", lang)} title={t("drains", lang)}><DrainIcon /></button>}
          {mode === "live" && WHATSAPP_NUMBER && (
            <a className="fab round wa"
              href={`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(WHATSAPP_JOIN || "hi")}`} target="_blank" rel="noreferrer"
              aria-label={lang === "hi" ? "WhatsApp से रिपोर्ट करें" : "Report on WhatsApp"}><MessageCircle size={20} /></a>
          )}
        </div>
      )}

      {panel.kind === "report" && (
        <ReportFlow fallbackCenter={center} vehicle={vehicle} lang={lang} setLang={setLang}
          onClose={() => setPanel({ kind: "none" })} onDone={loadLive} onRoute={(p) => openRoute(p)} />
      )}
      {panel.kind === "spot" && (
        <SpotSheet spot={panel.spot} mode={mode} known={NO_REPORTS} vehicle={vehicle} lang={lang} setLang={setLang}
          onClose={() => setPanel({ kind: "none" })} onRoute={(p) => openRoute(p)} />
      )}
      {panel.kind === "route" && (
        <RoutePanel vehicle={vehicle} lang={lang} mode={mode} at={mode === "sim" ? at : undefined} center={center} from={from} to={to} setFrom={setFrom} setTo={setTo}
          picking={picking} setPicking={setPicking} result={route} setResult={setRoute}
          alt={alt.v} setAlt={(v, g) => setAltState({ v, g })} showCoverage={setCoverage} onSignIn={() => setPanel({ kind: "account" })}
          onClose={() => { setPanel({ kind: "none" }); setRoute(null); setPicking(null); setAltState({ v: null, g: null }); setCoverage(null); }} />
      )}
      {panel.kind === "rain" && (
        <RainPanel lang={lang} data={rain} error={rainErr} onReload={() => { setRainErr(""); api.rainIndia().then(setRain).catch((e) => setRainErr(String(e.message ?? e))); }}
          selected={rainSel} onSelect={setRainSel} onClose={() => setPanel({ kind: "none" })}
          onOpenCity={(k) => { if (CITIES[k]) setCity(k); }} />
      )}
      {panel.kind === "sim" && <SimPanel lang={lang} data={sim} vehicle={vehicle} at={at || sim?.now || 0} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "account" && <AccountSheet lang={lang} center={center} onClose={() => setPanel({ kind: "none" })} onRoute={(p) => openRoute(p)} />}
      {panel.kind === "drains" && <DrainSheet lang={lang} center={center} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "bus" && <BusSheet mode={mode} at={mode === "sim" ? at : undefined} lang={lang} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "hotspot" && (
        <div className="sheet" role="dialog" aria-label={panel.h.name}>
          <header className="sheet-head">
            <div>
              <p className="eyebrow">{lang === "hi" ? "अक्सर भरने वाली जगह" : "Known flood spot"}</p>
              <h2>{lang === "hi" ? panel.h.name_hi ?? panel.h.name : panel.h.name}</h2>
            </div>
            <button className="icon-btn" onClick={() => setPanel({ kind: "none" })} aria-label={t("close", lang)}><X size={20} /></button>
          </header>
          <p>{t("hotspot", lang)}.</p>
          {panel.h.risk === "likely_flooded_soon" && <div className="banner warn"><CloudRain size={16} aria-hidden /> {t("rainSoon", lang)} ({Math.round(panel.h.rainNext3h ?? 0)} mm {lang === "hi" ? "अगले 3 घंटे" : "next 3 h"})</div>}
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
          <div className="actions"><button className="btn primary" onClick={() => openRoute([panel.h.lon, panel.h.lat])}><Navigation size={18} aria-hidden /> {t("routeFromHere", lang)}</button></div>
        </div>
      )}
    </div>
  );
}

/** Drain grate: lucide has no drain icon. */
function DrainIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 9v6M10.5 9v6M14 9v6M17.5 9v6" />
    </svg>
  );
}
