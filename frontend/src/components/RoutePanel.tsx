import { ArrowLeft, Bell, Info, LocateFixed, MapPinned, MapPinOff, Scan, Navigation, OctagonX, Route as RouteIcon, Share2, ShieldQuestion, Star, TriangleAlert, UserRound, X } from "lucide-react";
import { useState } from "react";
import { api, geocode, hasLocationKey } from "../api";
import { authEnabled, useAuth } from "../auth";
import { usePlaces } from "../places";
import { KIND_ICON } from "./AccountSheet";
import { t, VERDICT_UI, vehicleInfo, type Lang } from "../i18n";
import { VehicleIcon, VerdictIcon } from "../icons";
import type { CompareRow, CoverageArea, LonLat, Mode, PlaceKind, RouteResult, Vehicle } from "../types";
import { getPosition } from "../util";

type Field = "from" | "to";

interface Props {
  vehicle: Vehicle;
  lang: Lang;
  mode: Mode;
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
const COVERAGE_PREFIX = "One of your points is outside the routable demo area. ";

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

function PlaceField({ field, value, label, p }: { field: Field; value: LonLat | null; label: string; p: Props }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ title: string; pos: LonLat }[]>([]);
  const set = field === "from" ? p.setFrom : p.setTo;
  return (
    <div className="placefield">
      <label className="field-label">{label}</label>
      <div className="row">
        <span className={`endpoint inline ${field}`}>{field === "from" ? "A" : "B"}</span>
        {hasLocationKey ? (
          <input className="input" placeholder={value ? fmt(value) : t("search", p.lang)} value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={async (e) => { if (e.key === "Enter" && q.trim()) setHits(await geocode(q, p.center)); }} />
        ) : (
          <span className="input readonly">{value ? fmt(value) : "—"}</span>
        )}
      </div>
      {hits.length > 0 && (
        <ul className="hits">
          {hits.map((h) => (
            <li key={h.title}><button className="link" onClick={() => { set(h.pos); setHits([]); setQ(h.title); }}>{h.title}</button></li>
          ))}
        </ul>
      )}
      <div className="row gap chips">
        {field === "from" && (
          <button className="chip" onClick={() => getPosition().then(set).catch(() => alert("Location not available"))}>
            <LocateFixed size={16} aria-hidden /> {t("myLocation", p.lang)}
          </button>
        )}
        <button className={`chip${p.picking === field ? " active" : ""}`} onClick={() => p.setPicking(p.picking === field ? null : field)}>
          <MapPinned size={16} aria-hidden /> {t("tapMap", p.lang)}
        </button>
      </div>
      <SavedChips value={value} set={set} lang={p.lang} onSignIn={p.onSignIn} />
    </div>
  );
}

export default function RoutePanel(p: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [contact, setContact] = useState("");
  const [subMsg, setSubMsg] = useState("");
  const [alertsOpen, setAlertsOpen] = useState(false);
  const L = p.lang;
  const veh = vehicleInfo(p.vehicle);
  const r = p.result;

  async function go() {
    if (!p.from || !p.to) return;
    setBusy(true);
    setErr("");
    try {
      p.setResult(await api.route(p.from, p.to, p.vehicle, p.mode, p.at));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
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

  const leg = r?.safe ?? r?.normal ?? null;
  const sum = r ? summarise(r) : null;
  const SumIcon = sum ? SUMMARY_ICON[sum.cls] : Navigation;
  const outside = !!r && (r.out_of_area ?? r.note.startsWith(COVERAGE_PREFIX));
  const note = r ? r.note.replace(COVERAGE_PREFIX, "") : "";
  const showNormal = !!(r?.normal && r.safe && r.safe.distance_m !== r.normal.distance_m);

  const shareText = r && p.from && p.to && leg
    ? [
        `Can My Scooter Cross? · ${veh.en} route · checked ${clock(r.checked_at)}`,
        `${sum!.title.en}. ${(leg.distance_m / 1000).toFixed(1)} km · ${Math.round(leg.duration_min)} min.`,
        note,
        `From ${fmt(p.from)} to ${fmt(p.to)}: https://www.google.com/maps/dir/${p.from[1]},${p.from[0]}/${p.to[1]},${p.to[0]}`,
        "Based on reports, not a guarantee. If unsure, don't cross.",
      ].filter(Boolean).join("\n")
    : "";

  return (
    <div className="sheet route-sheet" role="dialog" aria-label={t("safeRoute", L)}>
      <header className="sheet-head">
        <div>
          <p className="eyebrow">{t("safeRoute", L)}</p>
          <h2 className="row gap"><VehicleIcon v={p.vehicle} size={22} /> {veh[L]}</h2>
        </div>
        <button className="icon-btn" onClick={p.onClose} aria-label={t("close", L)}><X size={20} /></button>
      </header>

      {!r && (
        <>
          <PlaceField field="from" value={p.from} label={t("from", L)} p={p} />
          <PlaceField field="to" value={p.to} label={t("to", L)} p={p} />
          <button className="btn primary big-btn" disabled={!p.from || !p.to || busy} onClick={go}>
            <Navigation size={18} aria-hidden /> {busy ? (L === "hi" ? "खोज रहे हैं…" : "Checking route…") : t("findRoute", L)}
          </button>
          {err && <p className="error-box">{err}</p>}
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
