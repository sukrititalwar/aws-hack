import { ArrowLeft, ArrowUp, ArrowUpDown, Bell, ChevronDown, ChevronUp, CornerUpLeft, CornerUpRight, Info, LocateFixed, MapPinned, MapPinOff, Navigation, OctagonX, Pause, Play, RotateCcw, Route as RouteIcon, Scan, Share2, ShieldQuestion, Star, Target, TriangleAlert, UserRound, Volume2, VolumeX, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, geocode, PREDICTIVE_ROUTE_ENABLED } from "../api";
import { authEnabled, useAuth } from "../auth";
import { usePlaces } from "../places";
import { KIND_ICON } from "./AccountSheet";
import { PREDICTIVE_UI, predictiveReason, t, VERDICT_UI, vehicleInfo, type Lang } from "../i18n";
import { VehicleIcon, VerdictIcon } from "../icons";
import type { CompareRow, CoverageArea, LonLat, Mode, PlaceKind, PredictiveRiskLevel, PredictiveRouteResult, RouteResult, Vehicle } from "../types";
import { calculateBearing, getPosition, haversineMeters, interpolatePolyline, polylineTotalMeters, speak, type UserLocation } from "../util";

export const DELHI_COVERAGE_AREAS: CoverageArea[] = [
  { name: "Central Delhi: Minto Bridge, ITO, Pragati Maidan, Moolchand", bbox: [77.195, 28.555, 77.265, 28.645] },
  { name: "North-west Delhi: DTU, Rohini, Samaypur Badli", bbox: [77.095, 28.715, 77.165, 28.770] },
];

export const DEMO_PRESETS = [
  {
    id: "minto",
    name: { en: "CP ➔ Ajmeri Gate (Minto Bridge)", hi: "CP ➔ अजमेरी गेट (मिंटो ब्रिज)" },
    desc: { en: "81 cm water hazard · Safe detour", hi: "81 सेमी बाढ़ · सुरक्षित चक्कर" },
    from: [77.2205, 28.6328] as LonLat,
    fromName: { en: "Connaught Place (CP)", hi: "कनॉट प्लेस (CP)" },
    to: [77.2235, 28.6430] as LonLat,
    toName: { en: "Ajmeri Gate (via Minto Bridge)", hi: "अजमेरी गेट (मिंटो ब्रिज होकर)" },
  },
  {
    id: "moolchand",
    name: { en: "Def Col ➔ Lajpat (Moolchand)", hi: "डिफेंस कॉलोनी ➔ लाजपत (मूलचंद)" },
    desc: { en: "45 cm water · Open drain hazard", hi: "45 सेमी बाढ़ · खुला नाला जोखिम" },
    from: [77.2280, 28.5720] as LonLat,
    fromName: { en: "Defence Colony", hi: "डिफेंस कॉलोनी" },
    to: [77.2370, 28.5640] as LonLat,
    toName: { en: "Lajpat Nagar", hi: "लाजपत नगर" },
  },
];

type Field = "from" | "to";

interface Props {
  vehicle: Vehicle;
  lang: Lang;
  mode: Mode;
  city?: string;
  at?: number;
  center: LonLat;
  from: LonLat | null;
  to: LonLat | null;
  setFrom: (p: LonLat | null) => void;
  setTo: (p: LonLat | null) => void;
  picking: Field | null;
  setPicking: (f: Field | null) => void;
  result: RouteResult | null;
  setResult: (r: RouteResult | null) => void;
  alt: Vehicle | null;
  setAlt: (v: Vehicle | null, g: CompareRow["geometry"] | null) => void;
  showCoverage: (areas: CoverageArea[] | null) => void;
  coverage?: CoverageArea[] | null;
  userLocation?: UserLocation | null;
  setUserLocation?: (loc: UserLocation | null) => void;
  navigating?: boolean;
  setNavigating?: (b: boolean) => void;
  followUser?: boolean;
  setFollowUser?: (b: boolean) => void;
  onSignIn: () => void;
  onClose: () => void;
}

const STATUS: Record<CompareRow["status"], { en: string; hi: string }> = {
  usual: { en: "Usual route", hi: "सामान्य रास्ता" },
  usual_with_care: { en: "Usual, go slow", hi: "सामान्य, धीरे" },
  detour: { en: "Detour", hi: "घूमकर" },
  stuck: { en: "No dry route", hi: "सूखा रास्ता नहीं" },
};

// Older API builds prefixed the coverage warning onto the note; strip it so coverage and safety stay separate.
const COVERAGE_PREFIX = "One of your points is outside the routable area. ";

type Summary = { cls: "clear" | "detour" | "bad" | "unknown"; title: { en: string; hi: string } };

/** The headline for a route. "Nothing reported" is never presented as "safe". */
function summarise(r: RouteResult): Summary {
  if (!r.normal) return { cls: "bad", title: { en: "No route found", hi: "रास्ता नहीं मिला" } };
  if (!r.safe) return { cls: "bad", title: { en: "No dry route found", hi: "सूखा रास्ता नहीं मिला" } };
  const n = r.avoided_spots.length;
  if (n > 0) return { cls: "detour", title: { en: `Avoids ${n} flooded spot${n === 1 ? "" : "s"}`, hi: `${n} पानी भरी जगहों से बचता है` } };
  if (r.spots_considered === 0) return { cls: "unknown", title: { en: "No live reports in this area", hi: "इस इलाके से कोई लाइव रिपोर्ट नहीं" } };
  return { cls: "clear", title: { en: "No flooding reported on this route", hi: "इस रास्ते पर पानी भराव की कोई रिपोर्ट नहीं" } };
}

const SUMMARY_ICON = { clear: Navigation, detour: RouteIcon, bad: OctagonX, unknown: ShieldQuestion } as const;

const clock = (s?: number) => new Date((s ?? Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const riskLabel = (level: PredictiveRiskLevel, lang: Lang) => ({
  lower_relative_concern: PREDICTIVE_UI.lower[lang],
  watch: PREDICTIVE_UI.watch[lang],
  elevated: PREDICTIVE_UI.elevated[lang],
  unknown: PREDICTIVE_UI.unknown[lang],
})[level];

/** Same trip for other vehicles: "scooter must detour, but a car/bus can take the usual road". */
function Compare({ rows, lang, current, alt, setAlt }: { rows: CompareRow[]; lang: Lang; current: Vehicle; alt: Vehicle | null;
  setAlt: Props["setAlt"] }) {
  return (
    <section className="rsec">
      <h3 className="sec-title">{lang === "hi" ? "यही सफ़र, दूसरी गाड़ियाँ" : "Same trip, other vehicles"}</h3>
      <ul className="compare">
        {rows.map((r) => {
          const v = vehicleInfo(r.vehicle);
          const extra = r.status === "detour" ? ` · +${Math.max(0, Math.round(r.extra_min))} min` : "";
          const why = r.blocking.length ? `${lang === "hi" ? "रुकावट" : "Blocked at"}: ${r.blocking.join(", ")}`
            : r.risky.length ? `${lang === "hi" ? "जोखिम" : "Risky"}: ${r.risky.join(", ")}` : "";
          return (
            <li key={r.vehicle}>
              <button className={alt === r.vehicle ? "sel" : ""} aria-pressed={alt === r.vehicle} disabled={!r.geometry}
                onClick={() => (alt === r.vehicle ? setAlt(null, null) : setAlt(r.vehicle, r.geometry))}>
                <span className="cicon"><VehicleIcon v={r.vehicle} size={20} /></span>
                <span className="cmain">
                  <span className="cname">{v[lang]}{r.vehicle === current ? (lang === "hi" ? " (आप)" : " (you)") : ""}</span>
                  <span className="small muted">{r.geometry
                    ? `${(r.safe_km ?? r.usual_km).toFixed(1)} km · ${Math.round(r.safe_min ?? r.usual_min)} min${extra}${why ? ` · ${why}` : ""}`
                    : r.note}</span>
                </span>
                <span className={`cstat ${r.status}`}>{STATUS[r.status][lang]}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="hint">{lang === "hi" ? "किसी गाड़ी पर टैप करें: उसका रास्ता हरी डैश लाइन में दिखेगा।" : "Tap a vehicle to show its route as a green dashed line."}</p>
    </section>
  );
}

const fmt = (p: LonLat | null) => (p ? `${p[1].toFixed(4)}, ${p[0].toFixed(4)}` : "");

const near = (a: LonLat, b: LonLat) => Math.abs(a[0] - b[0]) < 0.0003 && Math.abs(a[1] - b[1]) < 0.0003;   // ~30 m

/** One-tap saved places for this field, and "save this point" for signed-in users. */
function SavedChips({ value, set, lang, onSignIn }: { value: LonLat | null; set: (p: LonLat) => void; lang: Lang; onSignIn: () => void }) {
  const { user } = useAuth();
  const { places, add } = usePlaces();
  const [saving, setSaving] = useState(false);
  const [kind, setKind] = useState<PlaceKind>("home");
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  if (!authEnabled) return null;
  if (!user) {
    return (
      <div className="row gap chips savedchips">
        <button className="chip" onClick={onSignIn}><UserRound size={16} aria-hidden /> {lang === "hi" ? "सेव की हुई जगहों के लिए साइन इन करें" : "Sign in to use saved places"}</button>
      </div>
    );
  }
  const already = value ? places.find((x) => near([x.lon, x.lat], value)) : undefined;
  async function save() {
    if (!value) return;
    setMsg("");
    try {
      await add({ label: kind === "other" ? name.trim() : kind === "home" ? "Home" : "Work", kind, lat: value[1], lon: value[0] });
      setSaving(false);
      setName("");
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  return (
    <div className="savedchips">
      {places.length > 0 && (
        <div className="row gap chips" aria-label={lang === "hi" ? "सेव की हुई जगहें" : "Saved places"}>
          {places.map((x) => {
            const Icon = KIND_ICON[x.kind];
            return <button key={x.placeId} className={`chip${value && near([x.lon, x.lat], value) ? " active" : ""}`} onClick={() => set([x.lon, x.lat])} title={x.address || x.label}><Icon size={16} aria-hidden /> <span>{x.label}</span></button>;
          })}
        </div>
      )}
      {value && !already && !saving && (
        <div className="row gap chips" style={{ marginTop: 6 }}>
          <button className="chip" onClick={() => setSaving(true)}><Star size={16} aria-hidden /> {lang === "hi" ? "इस जगह को सेव करें" : "Save this place"}</button>
        </div>
      )}
      {saving && (
        <div style={{ marginTop: 6 }}>
          <div className="row gap chips" role="radiogroup">
            {(["home", "work", "other"] as PlaceKind[]).map((k) => {
              const Icon = KIND_ICON[k];
              return <button key={k} role="radio" aria-checked={kind === k} className={`chip${kind === k ? " active" : ""}`} onClick={() => setKind(k)}><Icon size={16} aria-hidden /> {k === "home" ? "Home" : k === "work" ? "Work" : lang === "hi" ? "अन्य" : "Other"}</button>;
            })}
          </div>
          {kind === "other" && <input className="input" style={{ marginTop: 6 }} maxLength={40} placeholder={lang === "hi" ? "नाम" : "Name"} value={name} onChange={(e) => setName(e.target.value)} />}
          <div className="row gap" style={{ marginTop: 6 }}>
            <button className="btn primary" disabled={kind === "other" && !name.trim()} onClick={save}>{lang === "hi" ? "सेव" : "Save"}</button>
            <button className="btn" onClick={() => setSaving(false)}>{lang === "hi" ? "रद्द" : "Cancel"}</button>
          </div>
        </div>
      )}
      {msg && <p className="error-box" role="alert">{msg}</p>}
    </div>
  );
}

function PlaceField({ field, value, label, text, setText, p }: { field: Field; value: LonLat | null; label: string; text: string; setText: (s: string) => void; p: Props }) {
  const [hits, setHits] = useState<{ title: string; pos: LonLat }[]>([]);
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState(false);
  const set = field === "from" ? p.setFrom : p.setTo;
  const seq = useRef(0);

  // type-ahead: search 450 ms after the last keystroke (one request at a time, stale answers dropped)
  useEffect(() => {
    if (!typed) return;
    const q = text.trim();
    if (q.length < 3) { setHits([]); return; }
    const id = setTimeout(async () => {
      const mine = ++seq.current;
      setBusy(true);
      const r = await geocode(q, p.center);
      if (mine === seq.current) { setHits(r); setBusy(false); }
    }, 450);
    return () => clearTimeout(id);
  }, [text, typed]); // eslint-disable-line react-hooks/exhaustive-deps

  function choose(h: { title: string; pos: LonLat }) {
    seq.current++;
    set(h.pos); setHits([]); setTyped(false); setText(h.title.split(",").slice(0, 2).join(","));
  }
  function useMyLocation() {
    setText(t("locating", p.lang)); setTyped(false); setHits([]);
    getPosition().then((pos) => { set(pos); setText(t("yourLocation", p.lang)); })
      .catch(() => { setText(""); alert(p.lang === "hi" ? "आपकी जगह नहीं मिली। लोकेशन की अनुमति दें या मैप पर टैप करें।" : "Location not available. Allow location access, or tap the map."); });
  }
  return (
    <div className="placefield">
      <label className="field-label" htmlFor={`pf-${field}`}>{label}</label>
      <div className="row">
        <span className={`endpoint inline ${field}`}>{field === "from" ? "A" : "B"}</span>
        <input id={`pf-${field}`} className="input" placeholder={field === "from" ? t("yourLocation", p.lang) : t("search", p.lang)} value={text} autoComplete="off"
          autoCorrect="off" autoCapitalize="words" spellCheck={false}
          enterKeyHint="search" onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => { setText(e.target.value); setTyped(true); }}
          onKeyDown={async (e) => { if (e.key === "Enter" && text.trim()) { setTyped(false); setBusy(true); setHits(await geocode(text.trim(), p.center)); setBusy(false); } }} />
      </div>
      {(hits.length > 0 || busy) && (
        <ul className="hits" role="listbox">
          {busy && hits.length === 0 && <li className="muted small">{p.lang === "hi" ? "खोज रहे हैं…" : "Searching…"}</li>}
          {hits.map((h) => (
            <li key={h.title + h.pos[0]}><button className="link" role="option" onClick={() => choose(h)}><MapPinned size={14} aria-hidden /> {h.title}</button></li>
          ))}
        </ul>
      )}
      <div className="row gap chips">
        {field === "from" && (
          <button className="chip" onClick={useMyLocation}>
            <LocateFixed size={16} aria-hidden /> {t("myLocation", p.lang)}
          </button>
        )}
        <button className={`chip${p.picking === field ? " active" : ""}`} onClick={() => p.setPicking(p.picking === field ? null : field)}>
          <MapPinned size={16} aria-hidden /> {t("tapMap", p.lang)}
        </button>
      </div>
      <SavedChips value={value} set={(pt) => { set(pt); setText(""); }} lang={p.lang} onSignIn={p.onSignIn} />
    </div>
  );
}

function DelhiCoverageCard({ lang, showCoverage, coverageActive }: { lang: Lang; showCoverage: (a: CoverageArea[] | null) => void; coverageActive?: boolean }) {
  return (
    <div className="delhi-coverage-box">
      <div className="delhi-coverage-header">
        <span>📍 {lang === "hi" ? "दिल्ली कवरेज क्षेत्र (सक्रिय)" : "Active Delhi Coverage Areas"}</span>
        <button className="btn ghost small-btn" type="button" onClick={() => showCoverage(coverageActive ? null : DELHI_COVERAGE_AREAS)}>
          <Scan size={14} aria-hidden /> {coverageActive ? (lang === "hi" ? "कवरेज छिपाएँ" : "Hide boundary") : (lang === "hi" ? "मैप पर दिखाएँ" : "Show on map")}
        </button>
      </div>
      <div className="delhi-zone-item">
        <strong>1. Central Delhi</strong>
        <span>Minto Bridge, CP, ITO, Pragati Maidan, Moolchand, India Gate, Lajpat Nagar</span>
      </div>
      <div className="delhi-zone-item">
        <strong>2. North-West Delhi</strong>
        <span>DTU (Delhi Technological Univ), Rohini Sectors 11/16/17/18, Samaypur Badli</span>
      </div>
    </div>
  );
}

interface TurnInfo {
  type: "straight" | "right" | "left" | "destination";
  distanceMeters: number;
  instruction: string;
}

function getNextTurn(coords: LonLat[], currentDistMeters: number, lang: Lang, destName?: string): TurnInfo {
  const total = polylineTotalMeters(coords);
  const remaining = Math.max(0, total - currentDistMeters);
  if (remaining <= 35) {
    return {
      type: "destination",
      distanceMeters: Math.round(remaining),
      instruction: lang === "hi" ? "मंज़िल आ गई है" : (destName ? `Arriving at ${destName}` : "Arriving at destination"),
    };
  }

  let covered = 0;
  let currIdx = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const d = haversineMeters(coords[i], coords[i + 1]);
    if (covered + d >= currentDistMeters) {
      currIdx = i;
      break;
    }
    covered += d;
  }

  const currentBearing = calculateBearing(coords[currIdx], coords[currIdx + 1]);
  let distToNextTurn = 0;
  for (let i = currIdx + 1; i < coords.length - 1; i++) {
    distToNextTurn += haversineMeters(coords[i - 1], coords[i]);
    const nextBearing = calculateBearing(coords[i], coords[i + 1]);
    const diff = (nextBearing - currentBearing + 540) % 360 - 180;

    if (Math.abs(diff) >= 28) {
      const isRight = diff > 0;
      const turnName = isRight ? (lang === "hi" ? "दाएं मुड़ें" : "Turn right") : (lang === "hi" ? "बाएं मुड़ें" : "Turn left");
      const distRounded = Math.round(distToNextTurn);
      const prep = distRounded <= 40
        ? (lang === "hi" ? `अब ${turnName}` : `${turnName} now`)
        : (lang === "hi" ? `${distRounded} मी में ${turnName}` : `In ${distRounded}m, ${turnName}`);
      return {
        type: isRight ? "right" : "left",
        distanceMeters: distRounded,
        instruction: prep,
      };
    }
    if (distToNextTurn > 500) break;
  }

  return {
    type: "straight",
    distanceMeters: Math.round(remaining),
    instruction: lang === "hi" ? "सुरक्षित रास्ते पर सीधे चलें" : "Continue straight on safe route",
  };
}

export default function RoutePanel(p: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [contact, setContact] = useState("");
  const [subMsg, setSubMsg] = useState("");
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [prediction, setPrediction] = useState<PredictiveRouteResult | null>(null);
  const [predictionBusy, setPredictionBusy] = useState(false);
  const [predictionErr, setPredictionErr] = useState("");
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [muted, setMuted] = useState(false);
  const [lastSpokenSpot, setLastSpokenSpot] = useState<string>("");
  const [navMode, setNavMode] = useState<"sim" | "live">("sim");
  const [simProgress, setSimProgress] = useState(0);
  const [simPlaying, setSimPlaying] = useState(true);
  const [simSpeed, setSimSpeed] = useState<1 | 2 | 4>(1);
  const [arrived, setArrived] = useState(false);
  const L = p.lang;
  const veh = vehicleInfo(p.vehicle);
  const r = p.result;
  const ran = useRef("");

  function loadPreset(preset: typeof DEMO_PRESETS[0]) {
    ran.current = "";
    p.setResult(null);
    p.setAlt(null, null);
    p.setFrom(preset.from);
    setFromText(preset.fromName[L]);
    p.setTo(preset.to);
    setToText(preset.toName[L]);
    p.setPicking(null);
  }

  // Pre-feed values in simulation mode, or use device location in live mode
  useEffect(() => {
    if (p.mode === "sim") {
      p.setFrom([77.2205, 28.6328]);
      setFromText(L === "hi" ? "कनॉट प्लेस (CP)" : "Connaught Place (CP)");
      p.setTo([77.2235, 28.6430]);
      setToText(L === "hi" ? "अजमेरी गेट (मिंटो ब्रिज होकर)" : "Ajmeri Gate (via Minto Bridge)");
      return;
    }
    if (p.from) return;
    if (p.userLocation) {
      p.setFrom(p.userLocation.pos);
      setFromText(t("yourLocation", L));
      return;
    }
    setFromText(t("locating", L));
    getPosition().then((pos) => { p.setFrom(pos); setFromText(t("yourLocation", L)); }).catch(() => setFromText(""));
  }, [p.mode]); // eslint-disable-line react-hooks/exhaustive-deps

  // When points are tapped on the map, update input texts & invalidate previous route
  const prevFrom = useRef<LonLat | null>(p.from);
  const prevTo = useRef<LonLat | null>(p.to);
  useEffect(() => {
    if (p.from && (!prevFrom.current || prevFrom.current[0] !== p.from[0] || prevFrom.current[1] !== p.from[1])) {
      prevFrom.current = p.from;
      p.setResult(null);
      setFromText((cur) => {
        if (cur && cur !== t("locating", L) && cur !== t("yourLocation", L) && !cur.startsWith(t("droppedPin", L))) return cur;
        return `${t("droppedPin", L)} (${p.from![1].toFixed(4)}, ${p.from![0].toFixed(4)})`;
      });
    }
  }, [p.from, L]);

  useEffect(() => {
    if (p.to && (!prevTo.current || prevTo.current[0] !== p.to[0] || prevTo.current[1] !== p.to[1])) {
      prevTo.current = p.to;
      p.setResult(null);
      setToText((cur) => {
        if (cur && !cur.startsWith(t("droppedPin", L))) return cur;
        return `${t("droppedPin", L)} (${p.to![1].toFixed(4)}, ${p.to![0].toFixed(4)})`;
      });
    }
  }, [p.to, L]);

  // Route calculation triggers whenever both ends are chosen and not in picking mode
  useEffect(() => {
    if (!p.from || !p.to || p.picking) return;
    const key = `${p.from[0].toFixed(5)},${p.from[1].toFixed(5)}|${p.to[0].toFixed(5)},${p.to[1].toFixed(5)}|${p.vehicle}|${p.mode}|${p.at}`;
    if (ran.current === key) return;
    ran.current = key;
    go();
  }, [p.from, p.to, p.vehicle, p.mode, p.at, p.picking]); // eslint-disable-line react-hooks/exhaustive-deps

  function swap() {
    ran.current = "";
    const [f, t2, ft, tt] = [p.from, p.to, fromText, toText];
    p.setFrom(t2); p.setTo(f); setFromText(tt); setToText(ft);
  }

  useEffect(() => {
    setPrediction(null);
    setPredictionErr("");
  }, [p.result, p.vehicle, p.mode, p.from, p.to]);

  async function go() {
    if (!p.from || !p.to) return;
    setBusy(true);
    setErr("");
    setPrediction(null);
    try {
      p.setResult(await api.route(p.from, p.to, p.vehicle, p.mode, p.at));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function predict() {
    if (!p.from || !p.to) return;
    setPredictionBusy(true);
    setPredictionErr("");
    setPrediction(null);
    try {
      setPrediction(await api.predictiveRoute(p.from, p.to, p.vehicle));
    } catch (e) {
      setPredictionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPredictionBusy(false);
    }
  }

  async function watch() {
    const g = r?.safe?.geometry ?? r?.normal?.geometry;
    if (!g) return;
    try {
      const res = await api.subscribe({ contact: contact.trim(), vehicle: p.vehicle, name: "My route", route: g });
      setSubMsg(res.note);
    } catch (e) {
      setSubMsg(e instanceof Error ? e.message : String(e));
    }
  }

  // Active route geometry
  const leg = r?.safe ?? r?.normal ?? null;
  const coords = leg?.geometry?.coordinates ?? [];
  const totalMeters = polylineTotalMeters(coords);
  const spotsOnRoute = leg?.spots_on_route ?? [];

  // Start navigation handler
  function startNav() {
    setSimProgress(0);
    setSimPlaying(true);
    setArrived(false);
    p.setNavigating?.(true);
    p.setFollowUser?.(true);
    if (coords.length >= 2) {
      p.setUserLocation?.({
        pos: coords[0],
        heading: calculateBearing(coords[0], coords[1]),
        speed: 9.5 * simSpeed,
        accuracy: 4,
      });
    }
    speak(L === "hi" ? "नेविगेशन शुरू हो गया है। सुरक्षित रास्ता अनुसरण करें।" : "Starting navigation. Follow the safe route.", L);
  }

  // Simulation drive animation loop
  useEffect(() => {
    if (!p.navigating || navMode !== "sim" || !simPlaying || coords.length < 2) return;
    const intervalMs = 150;
    const speedMps = 9.5 * simSpeed; // ~34 km/h cruising scooter speed
    const stepMeters = speedMps * (intervalMs / 1000);

    const timer = setInterval(() => {
      setSimProgress((prev) => {
        const next = prev + stepMeters;
        if (next >= totalMeters) {
          clearInterval(timer);
          setSimPlaying(false);
          setArrived(true);
          const lastPt = coords[coords.length - 1];
          p.setUserLocation?.({
            pos: lastPt,
            heading: 0,
            speed: 0,
            accuracy: 3,
          });
          speak(L === "hi" ? "आप अपनी मंज़िल पर पहुँच गए हैं।" : "You have arrived at your destination.", L);
          return totalMeters;
        }

        const interpolated = interpolatePolyline(coords, next);
        p.setUserLocation?.({
          pos: interpolated.pos,
          heading: interpolated.heading,
          speed: speedMps,
          accuracy: 5,
        });
        return next;
      });
    }, intervalMs);

    return () => clearInterval(timer);
  }, [p.navigating, navMode, simPlaying, simSpeed, coords, totalMeters]);

  // Dynamic distance & speed calculations
  const liveDistMeters = navMode === "sim"
    ? Math.max(0, totalMeters - simProgress)
    : (p.userLocation && p.to)
      ? haversineMeters(p.userLocation.pos, p.to)
      : leg?.distance_m ?? 0;
  const liveDistKm = (liveDistMeters / 1000).toFixed(1);
  const liveSpeedKmh = navMode === "sim"
    ? (simPlaying && !arrived ? Math.round(9.5 * simSpeed * 3.6) : 0)
    : p.userLocation?.speed != null
      ? Math.round(p.userLocation.speed * 3.6)
      : 0;

  const currentPos: LonLat | null = navMode === "sim"
    ? (coords.length > 0 ? interpolatePolyline(coords, simProgress).pos : null)
    : (p.userLocation?.pos ?? null);

  const closestHazard = (currentPos && spotsOnRoute.length > 0)
    ? spotsOnRoute.map((s) => ({
        spot: s,
        dist: haversineMeters(currentPos, [s.lon, s.lat]),
      })).sort((a, b) => a.dist - b.dist)[0]
    : null;
  const hazardAhead = closestHazard && closestHazard.dist <= 500 ? closestHazard : null;
  const turnInfo = coords.length > 1 ? getNextTurn(coords, simProgress, L, toText) : null;

  // Voice announcements for water hazards ahead
  useEffect(() => {
    if (!p.navigating || muted || !hazardAhead) return;
    const spotKey = `${hazardAhead.spot.spotId}-${Math.round(hazardAhead.dist / 150)}`;
    if (lastSpokenSpot === spotKey) return;
    setLastSpokenSpot(spotKey);
    const msg = L === "hi"
      ? `सावधान: ${Math.round(hazardAhead.dist)} मीटर आगे पानी भराव है, गहराई लगभग ${hazardAhead.spot.depth_high} सेंटीमीटर। सुरक्षित चक्कर लें।`
      : `Caution: Flooded road ${Math.round(hazardAhead.dist)} meters ahead, depth about ${hazardAhead.spot.depth_high} centimeters. Following safe detour.`;
    speak(msg, L);
  }, [p.navigating, muted, hazardAhead, lastSpokenSpot, L]);

  // Active Google Maps style Navigation HUD
  if (p.navigating && r) {
    const remainingMin = Math.max(1, Math.round(liveDistMeters / (9.5 * (navMode === "sim" ? simSpeed : 1)) / 60));
    const arrivalTime = new Date(Date.now() + remainingMin * 60000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

    const TurnIcon = turnInfo?.type === "right"
      ? CornerUpRight
      : turnInfo?.type === "left"
        ? CornerUpLeft
        : turnInfo?.type === "destination"
          ? Target
          : ArrowUp;

    return (
      <>
        <div className="nav-hud-top" role="status">
          <div className="nav-hud-direction">
            <div className={`nav-hud-icon${turnInfo?.type === "destination" ? " arrived" : ""}`}>
              <TurnIcon size={22} />
            </div>
            <div className="nav-hud-text">
              <h4>{turnInfo?.instruction || (L === "hi" ? "सुरक्षित रास्ता" : "Following Safe Route")}</h4>
              <p>{toText || (L === "hi" ? "मंज़िल की ओर" : "Heading to destination")}</p>
            </div>
            <button className="icon-btn" onClick={() => setMuted(!muted)} aria-label={muted ? "Unmute" : "Mute"}>
              {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
            </button>
          </div>
          {hazardAhead && (
            <div className="nav-alert-banner">
              <TriangleAlert size={18} />
              <span>{L === "hi"
                ? `${hazardAhead.spot.place ?? "पानी भरी जगह"} (${Math.round(hazardAhead.dist)} मी आगे, ~${hazardAhead.spot.depth_high} सेमी)`
                : `${hazardAhead.spot.place ?? "Flooded spot"} in ${Math.round(hazardAhead.dist)}m (~${hazardAhead.spot.depth_high} cm)`}</span>
            </div>
          )}
        </div>

        {!p.followUser && (
          <button className="fab-recenter" onClick={() => p.setFollowUser?.(true)} aria-label={L === "hi" ? "मेरी लोकेशन पर आएँ" : "Recenter on my location"} title={L === "hi" ? "मेरी लोकेशन पर आएँ" : "Recenter"}>
            <Target size={22} />
          </button>
        )}

        <div className="nav-hud-bottom">
          <div className="nav-stats-row">
            <div>
              <span className="nav-eta-big">{remainingMin} <small style={{ fontSize: "1rem" }}>min</small></span>
              <span className="nav-sub-stats">({liveDistKm} km · {arrivalTime})</span>
            </div>
            <div className="nav-badges-group">
              <span className="nav-speed-badge">
                {liveSpeedKmh > 0 ? `${liveSpeedKmh} km/h` : "0 km/h"}
              </span>
              <button
                type="button"
                className={`nav-mode-pill ${navMode === "sim" ? "on" : ""}`}
                onClick={() => {
                  const next = navMode === "sim" ? "live" : "sim";
                  setNavMode(next);
                  if (next === "sim") {
                    setSimPlaying(true);
                  }
                }}
                title={navMode === "sim" ? "Switch to real phone GPS" : "Switch to route drive simulation"}
              >
                {navMode === "sim" ? "🛵 Simulation" : "🛰️ Live GPS"}
              </button>
            </div>
          </div>

          {/* Simulation controls bar */}
          {navMode === "sim" && (
            <div className="nav-sim-bar">
              <button
                type="button"
                className="nav-sim-btn"
                onClick={() => setSimPlaying(!simPlaying)}
                title={simPlaying ? "Pause drive" : "Play drive"}
              >
                {simPlaying ? <Pause size={14} /> : <Play size={14} />}
                <span>{simPlaying ? (L === "hi" ? "रोकें" : "Pause") : (L === "hi" ? "चलाएं" : "Play")}</span>
              </button>
              <button
                type="button"
                className="nav-sim-btn"
                onClick={() => setSimSpeed((s) => (s === 1 ? 2 : s === 2 ? 4 : 1))}
                title="Simulation speed multiplier"
              >
                <span>⚡ {simSpeed}x</span>
              </button>
              <button
                type="button"
                className="nav-sim-btn"
                onClick={() => {
                  setSimProgress(0);
                  setSimPlaying(true);
                  setArrived(false);
                }}
                title="Restart route drive"
              >
                <RotateCcw size={14} />
                <span>{L === "hi" ? "पुनः" : "Restart"}</span>
              </button>
            </div>
          )}

          <div className="nav-actions-row">
            <button className="btn-nav-recenter" onClick={() => p.setFollowUser?.(true)}>
              <Target size={16} /> {p.followUser ? (L === "hi" ? "फॉलो जारी" : "Following") : (L === "hi" ? "रीसेंटर करें" : "Re-center")}
            </button>
            <button className="btn-nav-exit" onClick={() => { p.setNavigating?.(false); p.setFollowUser?.(false); setSimPlaying(false); }}>
              <X size={18} /> {L === "hi" ? "समाप्त" : "Exit"}
            </button>
          </div>
        </div>
      </>
    );
  }

  // While choosing a point, shrink to a bar so the map stays tappable.
  if (p.picking) {
    return (
      <div className="sheet peek" role="dialog" aria-label={t("tapMap", L)}>
        <div className="row gap" style={{ justifyContent: "space-between" }}>
          <span className="row gap"><MapPinned size={18} aria-hidden /> <strong>{t("tapMap", L)}</strong>
            <span className={`endpoint inline ${p.picking}`}>{p.picking === "from" ? "A" : "B"}</span></span>
          <button className="btn ghost" onClick={() => p.setPicking(null)}>{t("cancel", L)}</button>
        </div>
      </div>
    );
  }

  const sum = r ? summarise(r) : null;
  const SumIcon = sum ? SUMMARY_ICON[sum.cls] : Navigation;
  const outside = !!r && (r.out_of_area ?? (r.note.startsWith(COVERAGE_PREFIX) || r.note.startsWith("One of your points is outside the routable")));
  const note = r ? r.note.replace(COVERAGE_PREFIX, "").replace("One of your points is outside the routable area. ", "").replace("One of your points is outside the routable demo area. ", "") : "";
  const showNormal = !!(r?.normal && r.safe && r.safe.distance_m !== r.normal.distance_m);
  const selectedPrediction = prediction?.vehicle_options.find((option) => option.vehicle === p.vehicle);

  const [collapsed, setCollapsed] = useState(false);

  // On mobile screens, start in peek mode once route is calculated so map is visible
  useEffect(() => {
    if (r && window.innerWidth < 760) {
      setCollapsed(true);
    }
  }, [r]);

  const shareText = r && p.from && p.to && leg
    ? [
        `Can My Scooter Cross? · ${veh.en} route · checked ${clock(r.checked_at)}`,
        `${sum!.title.en}. ${(leg.distance_m / 1000).toFixed(1)} km · ${Math.round(leg.duration_min)} min.`,
        note,
        `From ${fmt(p.from)} to ${fmt(p.to)}: https://www.google.com/maps/dir/${p.from[1]},${p.from[0]}/${p.to[1]},${p.to[0]}`,
        "Based on reports, not a guarantee. If unsure, don't cross.",
      ].filter(Boolean).join("\n")
    : "";

  // Mobile compact peek mode: leaves map clear with large Start Navigation button
  if (collapsed && r && sum && !(outside && !r.normal)) {
    return (
      <div className="sheet route-sheet peek" role="dialog" aria-label={t("safeRoute", L)}>
        <div className="route-peek-head" onClick={() => setCollapsed(false)}>
          <div className="sum-head" style={{ margin: 0, flex: 1, minWidth: 0 }}>
            <span className="sum-icon"><SumIcon size={18} aria-hidden /></span>
            <strong style={{ fontSize: "0.92rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sum.title[L]}</strong>
          </div>
          <div className="row gap" style={{ flexShrink: 0 }}>
            <button className="icon-btn sm" onClick={(e) => { e.stopPropagation(); setCollapsed(false); }} aria-label="Expand details" title="Expand">
              <ChevronUp size={18} />
            </button>
            <button className="icon-btn sm" onClick={p.onClose} aria-label={t("close", L)} title={t("close", L)}>
              <X size={16} />
            </button>
          </div>
        </div>

        {leg && (
          <div className="row gap" style={{ justifyContent: "space-between", alignItems: "baseline", margin: "6px 0 8px" }}>
            <span className="sum-big" style={{ fontSize: "1.15rem" }}>
              {(leg.distance_m / 1000).toFixed(1)} km · {Math.round(leg.duration_min)} min
            </span>
            <button className="link small" onClick={() => setCollapsed(false)}>
              {L === "hi" ? "विवरण देखें ▲" : "Details ▲"}
            </button>
          </div>
        )}

        {leg && (
          <button className="btn-nav-start" style={{ width: "100%", margin: "0" }} onClick={startNav}>
            <Navigation size={18} style={{ fill: "currentColor" }} />
            <span>{L === "hi" ? "नेविगेशन शुरू करें (लाइव GPS + ड्राइव)" : "Start Navigation (Live GPS / Drive)"}</span>
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="sheet route-sheet" role="dialog" aria-label={t("safeRoute", L)}>
      <header className="sheet-head">
        <div>
          <p className="eyebrow">{t("safeRoute", L)}</p>
          <h2 className="row gap"><VehicleIcon v={p.vehicle} size={22} /> {veh[L]}</h2>
        </div>
        <div className="row gap" style={{ flexShrink: 0 }}>
          {r && (
            <button className="icon-btn sm" onClick={() => setCollapsed(true)} aria-label="Collapse to map" title="Collapse to map">
              <ChevronDown size={18} />
            </button>
          )}
          <button className="icon-btn sm" onClick={p.onClose} aria-label={t("close", L)}><X size={18} /></button>
        </div>
      </header>

      {!r && (
        <>
          <div className="demo-presets-card">
            <span className="eyebrow" style={{ color: "var(--primary)" }}>⚡ {L === "hi" ? "डेमो एक-क्लिक रास्ते" : "Demo 1-Click Routes"}</span>
            <div className="row gap" style={{ marginTop: 4 }}>
              {DEMO_PRESETS.map((dp) => (
                <button key={dp.id} type="button" className="preset-btn" onClick={() => loadPreset(dp)}>
                  <span className="preset-name">{dp.name[L]}</span>
                  <span className="preset-tag">{dp.desc[L]}</span>
                </button>
              ))}
            </div>
          </div>

          <PlaceField field="from" value={p.from} label={t("from", L)} text={fromText} setText={setFromText} p={p} />
          <button className="btn ghost swapbtn" onClick={swap} disabled={!p.from && !p.to} aria-label={t("swap", L)} title={t("swap", L)}>
            <ArrowUpDown size={16} aria-hidden /> {t("swap", L)}
          </button>
          <PlaceField field="to" value={p.to} label={t("to", L)} text={toText} setText={setToText} p={p} />
          <button className="btn primary big-btn" disabled={!p.from || !p.to || busy} onClick={go}>
            <Navigation size={18} aria-hidden /> {busy ? (L === "hi" ? "खोज रहे हैं…" : "Checking route…") : t("findRoute", L)}
          </button>
          {err && <p className="error-box">{err}</p>}
          <DelhiCoverageCard lang={L} showCoverage={p.showCoverage} coverageActive={!!p.coverage} />
        </>
      )}

      {r && outside && !r.normal && (
        <div className="route-result">
          <section className="summary unknown" role="status">
            <div className="sum-head">
              <span className="sum-icon"><MapPinOff size={20} aria-hidden /></span>
              <strong>{L === "hi" ? "यह सफ़र हमारे कवरेज से बाहर है" : "Outside our coverage"}</strong>
            </div>
            <p className="sum-note">{note}</p>
            <p className="sum-note">{L === "hi"
              ? "यह बाढ़ का फ़ैसला नहीं है। हमारे पास इन इलाक़ों का सड़क डेटा है:"
              : "This is not a flood verdict. We have road data for these areas:"}</p>
            <ul className="areas">
              {(r.coverage ?? []).map((a) => <li key={a.name}>{a.name}</li>)}
            </ul>
            <p className="fresh">{L === "hi" ? "पिन इन इलाक़ों के अंदर रखें।" : "Put both pins inside one of these areas."}</p>
          </section>
          <div className="actions">
            {!!r.coverage?.length && (
              <button className="btn primary grow" onClick={() => p.showCoverage(r.coverage!)}>
                <Scan size={18} aria-hidden /> {L === "hi" ? "कवर इलाक़े दिखाएँ" : "Show covered areas"}
              </button>
            )}
            <button className="btn ghost" onClick={() => { p.setResult(null); p.setAlt(null, null); p.showCoverage(null); }}>
              <ArrowLeft size={18} aria-hidden /> {L === "hi" ? "बदलें" : "Change"}
            </button>
          </div>
        </div>
      )}

      {r && sum && !(outside && !r.normal) && (
        <div className="route-result">
          {outside && (
            <div className="coverage" role="note">
              <Info size={18} aria-hidden />
              <span>{L === "hi"
                ? "एक बिंदु हमारे रूटिंग क्षेत्र से बाहर है, इसलिए रास्ता अधूरा हो सकता है। यह बाढ़ का फ़ैसला नहीं है।"
                : "One point is outside the area we have road data for, so this route may be incomplete. This is a coverage limit, not a flood verdict."}</span>
            </div>
          )}

          <section className={`summary ${sum.cls}`} role="status">
            <div className="sum-head">
              <span className="sum-icon"><SumIcon size={20} aria-hidden /></span>
              <strong>{sum.title[L]}</strong>
            </div>
            {leg && (
              <div className="sum-stats">
                <span className="sum-big">{(leg.distance_m / 1000).toFixed(1)}<small> km</small></span>
                <span className="sum-big">{Math.round(leg.duration_min)}<small> min</small></span>
                {r.safe && r.extra_min > 0 && <span className="pill">+{Math.round(r.extra_min)} min</span>}
              </div>
            )}
            {note && (sum.cls === "detour" || sum.cls === "bad") && <p className="sum-note">{note}</p>}
            <p className="fresh">
              {L === "hi" ? "जाँचा गया" : "Checked"} {clock(r.checked_at)} · {r.spots_considered ?? "–"} {L === "hi" ? "रिपोर्ट इस इलाके में" : `live report${r.spots_considered === 1 ? "" : "s"} in this area`}
            </p>
            {sum.cls === "unknown" && (
              <p className="sum-note">{L === "hi" ? "रिपोर्ट न होने का मतलब सूखी सड़क नहीं है। अंडरपास पर ध्यान दें।" : "No reports isn't the same as dry roads. Take care at underpasses."}</p>
            )}
          </section>

          {leg && (
            <button className="btn-nav-start" style={{ width: "100%", margin: "12px 0 6px" }} onClick={startNav}>
              <Navigation size={20} style={{ fill: "currentColor" }} />
              <span>{L === "hi" ? "नेविगेशन शुरू करें (लाइव GPS + ड्राइव)" : "Start Navigation (Live GPS / Drive)"}</span>
            </button>
          )}

          <DelhiCoverageCard lang={L} showCoverage={p.showCoverage} coverageActive={!!p.coverage} />

          <div className="demo-presets-card" style={{ marginTop: 8 }}>
            <span className="eyebrow" style={{ color: "var(--primary)" }}>⚡ {L === "hi" ? "अन्य डेमो रास्ता देखें" : "Try Another Demo Route"}</span>
            <div className="row gap" style={{ marginTop: 4 }}>
              {DEMO_PRESETS.map((dp) => (
                <button key={dp.id} type="button" className="preset-btn" onClick={() => loadPreset(dp)}>
                  <span className="preset-name">{dp.name[L]}</span>
                  <span className="preset-tag">{dp.desc[L]}</span>
                </button>
              ))}
            </div>
          </div>

          {PREDICTIVE_ROUTE_ENABLED && p.mode === "live" && p.from && p.to && (
            <section className="rsec">
              <div className="row gap" style={{ justifyContent: "space-between" }}>
                <h3 className="sec-title">{PREDICTIVE_UI.title[L]}</h3>
                <button className="btn small-btn" onClick={predict} disabled={predictionBusy}>
                  <TriangleAlert size={16} aria-hidden />
                  {predictionBusy ? PREDICTIVE_UI.loading[L] : PREDICTIVE_UI.button[L]}
                </button>
              </div>
              <p className="hint">{PREDICTIVE_UI.disclaimer[L]}</p>
              {predictionErr && <p className="error-box">{predictionErr}</p>}
              {prediction && (
                <>
                  {prediction.data_quality.weather !== "available" && (
                    <p className="coverage">{PREDICTIVE_UI.weatherMissing[L]}</p>
                  )}
                  {(!prediction.data_quality.reports_available
                    || !prediction.data_quality.hotspots_available) && (
                    <p className="coverage">{PREDICTIVE_UI.reportsMissing[L]}</p>
                  )}
                  <p className="small muted">
                    {prediction.data_quality.active_reports} {PREDICTIVE_UI.reports[L]} ·{" "}
                    {prediction.data_quality.forecast_locations} {L === "hi" ? "मौसम बिंदु" : "forecast locations"}
                  </p>
                  {selectedPrediction && (
                    <p className="sum-note">
                      <strong>{selectedPrediction.risk_score === null
                        ? PREDICTIVE_UI.unknown[L]
                        : `${riskLabel(selectedPrediction.risk_level, L)} · ${PREDICTIVE_UI.score[L]} ${selectedPrediction.risk_score}/100`}</strong>
                    </p>
                  )}
                  {prediction.recommended_vehicle ? (
                    <p className="sum-note">
                      {L === "hi" ? "कम सूचकांक वाला व्यवहार्य विकल्प:" : "Feasible option with lower index:"}{" "}
                      {vehicleInfo(prediction.recommended_vehicle)[L]}
                    </p>
                  ) : (
                    <p className="sum-note">{PREDICTIVE_UI.noComparable[L]}</p>
                  )}
                  <h4 className="small">{PREDICTIVE_UI.vehicles[L]}</h4>
                  <ul className="compare">
                    {prediction.vehicle_options.map((option) => (
                      <li key={option.vehicle}>
                        <button className={p.alt === option.vehicle ? "sel" : ""} aria-pressed={p.alt === option.vehicle}
                          disabled={!option.feasible || !option.route}
                          onClick={() => option.route && p.setAlt(option.vehicle, option.route.geometry)}>
                          <span className="cicon"><VehicleIcon v={option.vehicle} size={20} /></span>
                          <span className="cmain">
                            <span className="cname">{vehicleInfo(option.vehicle)[L]}</span>
                            <span className="small muted">{option.route
                              ? `${(option.route.distance_m / 1000).toFixed(1)} km · ${Math.round(option.route.duration_min)} min · ${option.risk_score === null
                                ? PREDICTIVE_UI.unknown[L]
                                : `${riskLabel(option.risk_level, L)} · ${option.risk_score}/100`} · ${PREDICTIVE_UI.coverage[L]} ${Math.round(option.coverage_fraction * 100)}%`
                              : PREDICTIVE_UI.noRoute[L]}</span>
                          </span>
                          <span className="cstat">{option.vehicle === prediction.recommended_vehicle
                            ? PREDICTIVE_UI.recommended[L] : riskLabel(option.risk_level, L)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <h4 className="small">{PREDICTIVE_UI.departures[L]}</h4>
                  <ul className="compare">
                    {prediction.departure_alternatives.map((option) => (
                      <li key={option.offset_min}>
                        <button className={option.recommended ? "sel" : ""} aria-pressed={option.recommended}
                          onClick={() => p.setAlt(p.vehicle, option.route.geometry)}>
                          <span className="cmain">
                            <span className="cname">{option.offset_min === 0 ? PREDICTIVE_UI.now[L]
                              : `${option.offset_min} ${PREDICTIVE_UI.after[L]}`} ·{" "}
                              {new Date(option.departure_at * 1000).toLocaleTimeString(L === "hi" ? "hi-IN" : "en-IN",
                                { hour: "2-digit", minute: "2-digit" })}</span>
                            <span className="small muted">{option.risk_score === null
                              ? riskLabel(option.risk_level, L)
                              : `${riskLabel(option.risk_level, L)} · ${option.risk_score}/100`}</span>
                          </span>
                          {option.recommended && <span className="cstat">{PREDICTIVE_UI.recommended[L]}</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                  {selectedPrediction?.reasons.map((reason) => (
                    <p className="hint" key={reason}>{predictiveReason(reason, L)}</p>
                  ))}
                </>
              )}
            </section>
          )}

          {(showNormal || r.safe) && (
            <section className="rsec legs">
              {r.safe && (
                <div className="leg"><span className="swatch" aria-hidden />
                  <span>{L === "hi" ? "सुझाया रास्ता" : "Suggested route"} · {(r.safe.distance_m / 1000).toFixed(1)} km · {Math.round(r.safe.duration_min)} min</span>
                </div>
              )}
              {showNormal && r.normal && (
                <div className="leg">
                  <span className="swatch dashed" aria-hidden />
                  <span>{t("normalRoute", L)} · {(r.normal.distance_m / 1000).toFixed(1)} km · {Math.round(r.normal.duration_min)} min</span>
                  {r.normal.spots_on_route.length > 0 && (
                    <ul className="spotlist">
                      {r.normal.spots_on_route.map((s) => (
                        <li key={s.spotId} className={VERDICT_UI[s.verdict].cls}>
                          <VerdictIcon cls={VERDICT_UI[s.verdict].cls} size={14} /> {s.place ?? "Flooded spot"} · ~{s.depth_high} cm
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          )}

          {!!r.compare?.length && <Compare rows={r.compare} lang={L} current={p.vehicle} alt={p.alt} setAlt={p.setAlt} />}

          {r.safe && p.mode === "live" && (
            <section className="rsec alerts">
              <div className="alerts-head">
                <Bell size={18} aria-hidden />
                <div>
                  <strong>{t("watchRoute", L)}</strong>
                  <p className="hint">{L === "hi"
                    ? "इस रास्ते पर आपकी गाड़ी के लिए 'नहीं' वाली नई फ़ोटो रिपोर्ट आए तो संदेश मिलेगा।"
                    : "We message you when a new photo report on this route is No-go for your vehicle."}</p>
                </div>
                {!alertsOpen && <button className="btn small-btn" onClick={() => setAlertsOpen(true)}>{L === "hi" ? "चालू करें" : "Turn on"}</button>}
              </div>
              {alertsOpen && (
                <div className="row gap">
                  <input className="input grow" value={contact} placeholder={t("contact", L)} onChange={(e) => setContact(e.target.value)} />
                  <button className="btn" onClick={watch} disabled={!contact.trim()}>{t("subscribe", L)}</button>
                </div>
              )}
              {subMsg && <p className="hint" role="status">{subMsg}</p>}
            </section>
          )}

          <div className="actions">
            {shareText && (
              <a className="btn primary grow" target="_blank" rel="noreferrer" href={`https://wa.me/?text=${encodeURIComponent(shareText)}`}>
                <Share2 size={18} aria-hidden /> {L === "hi" ? "रास्ता भेजें" : "Share route"}
              </a>
            )}
            <button className="btn ghost" onClick={() => { p.setResult(null); p.setAlt(null, null); }}>
              <ArrowLeft size={18} aria-hidden /> {L === "hi" ? "बदलें" : "Change"}
            </button>
          </div>
          <p className="disclaimer"><TriangleAlert size={14} aria-hidden /> {t("disclaimer", L)}</p>
        </div>
      )}
    </div>
  );
}
