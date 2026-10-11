import { Bus, Camera, CloudRain, History, Layers, MessageCircle, Monitor, Moon, Navigation, Radio, Shield, Sun, TriangleAlert, UserRound, Waves, WifiOff, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API, CITIES, setCity as setApiCity, WHATSAPP_JOIN, WHATSAPP_NUMBER } from "./api";
import AccountSheet from "./components/AccountSheet";
import BusSheet from "./components/BusSheet";
import { authEnabled, useAuth } from "./auth";
import DrainSheet from "./components/DrainSheet";
import DemoBar from "./components/DemoBar";
import MapView from "./components/MapView";
import ReportFlow from "./components/ReportFlow";
import RoutePanel from "./components/RoutePanel";
import SpotSheet from "./components/SpotSheet";
import { t, VEHICLES, type Lang } from "./i18n";
import { VehicleIcon, VerdictIcon } from "./icons";
import type { CompareRow, CoverageArea, Hotspot, LonLat, Mode, Report, RouteResult, Spot, Theme, Vehicle, Weather } from "./types";
import { getPosition, store, stored } from "./util";

type Panel = { kind: "none" } | { kind: "report" } | { kind: "route" } | { kind: "spot"; spot: Spot } | { kind: "hotspot"; h: Hotspot } | { kind: "bus" } | { kind: "drains" } | { kind: "account" };

// WhatsApp replies link here as ?city=..&lat=..&lon=..
const URLQ = new URLSearchParams(location.search);
const initialCity = (() => {
  const c = URLQ.get("city") || stored<string>("city", "delhi");
  return CITIES[c] ? c : "delhi";
})();
setApiCity(initialCity);

/** Compact live-rain status for the toolbar. Full numbers are in the tooltip / screen-reader label. */
function RainStatus({ w, lang, city }: { w: Weather | null; lang: Lang; city: string }) {
  if (!w) return null;
  const name = CITIES[city][lang === "hi" ? "hi" : "label"];
  const cls = w.hotspotsAtRisk > 0 ? "storm" : w.rainPast3h >= 2 || w.maxRainNowAtHotspots >= 1 ? "wet" : "";
  const mins = Math.max(0, Math.round((Date.now() / 1000 - w.updatedAt) / 60));
  const full = lang === "hi"
    ? `${name}: पिछले 3 घंटे ${w.rainPast3h.toFixed(1)} मिमी · अभी ${w.rainNow.toFixed(1)} मिमी/घं · अगले 3 घंटे ${w.rainNext3h.toFixed(1)} मिमी${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} जगहें ख़तरे में` : ""} · ${mins} मिनट पहले`
    : `${name}: ${w.rainPast3h.toFixed(1)} mm last 3 h · ${w.rainNow.toFixed(1)} mm/h now · ${w.rainNext3h.toFixed(1)} mm next 3 h${w.hotspotsAtRisk ? ` · ${w.hotspotsAtRisk} hotspots at risk` : ""} · updated ${mins} min ago`;
  const Icon = cls ? CloudRain : Sun;
  return (
    <span className={`rainpill ${cls}`} title={`${full}\n${w.source}`} aria-label={full} role="status">
      <Icon size={16} aria-hidden />
      <span>{w.rainNow.toFixed(1)} mm/h</span>
      <span className="rp-extra">· {w.rainNext3h.toFixed(0)} mm {lang === "hi" ? "अगले 3 घं" : "next 3 h"}</span>
      {w.hotspotsAtRisk > 0 && <span className="rp-risk">{w.hotspotsAtRisk} {lang === "hi" ? "ख़तरे में" : "at risk"}</span>}
      <span className="rp-age">{mins}m</span>
    </span>
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
        picking={!!picking} onPick={onPick} dark={dark} coverage={panel.kind === "route" ? coverage : null}
        onSpot={(s) => setPanel({ kind: "spot", spot: s })} onHotspot={(h) => setPanel({ kind: "hotspot", h })} />

      <header className="topbar">
        <div className="toolbar">
          <span className="brand" title="Can My Scooter Cross?"><Waves size={20} aria-hidden /><span className="brand-name">Can My Scooter Cross?</span></span>
          <select className="citysel" value={city} onChange={(e) => setCity(e.target.value)} aria-label="City">
            {Object.entries(CITIES).map(([k, c]) => <option key={k} value={k}>{lang === "hi" ? c.hi : c.label}</option>)}
          </select>
          {mode === "live" && <RainStatus w={weather} lang={lang} city={city} />}
          <span className="spacer" />
          <div className="seg" role="radiogroup" aria-label="Mode">
            <button role="radio" aria-checked={mode === "live"} className={mode === "live" ? "on" : ""} onClick={() => setMode("live")}><Radio size={15} aria-hidden /> <span className="live-label">{t("live", lang)}</span></button>
            <button role="radio" aria-checked={mode === "demo"} className={mode === "demo" ? "on" : ""} onClick={() => setMode("demo")}><History size={15} aria-hidden /> <span className="seg-label">{t("demo", lang)}</span></button>
          </div>
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

      {panel.kind === "none" && <Legend lang={lang} raised={mode === "demo"} />}

      {panel.kind === "none" && (
        <div className={`fabs${mode === "demo" ? " above-demo" : ""}`}>
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
          alt={alt.v} setAlt={(v, g) => setAltState({ v, g })} showCoverage={setCoverage} onSignIn={() => setPanel({ kind: "account" })}
          onClose={() => { setPanel({ kind: "none" }); setRoute(null); setPicking(null); setAltState({ v: null, g: null }); setCoverage(null); }} />
      )}
      {panel.kind === "account" && <AccountSheet lang={lang} center={center} onClose={() => setPanel({ kind: "none" })} onRoute={(p) => openRoute(p)} />}
      {panel.kind === "drains" && <DrainSheet lang={lang} center={center} onClose={() => setPanel({ kind: "none" })} />}
      {panel.kind === "bus" && <BusSheet mode={mode} at={at} lang={lang} onClose={() => setPanel({ kind: "none" })} />}
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
