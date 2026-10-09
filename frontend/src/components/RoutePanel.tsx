import { useState } from "react";
import { api, geocode, hasLocationKey } from "../api";
import { t, VERDICT_UI, vehicleInfo, type Lang } from "../i18n";
import type { CompareRow, LonLat, Mode, RouteResult, Vehicle } from "../types";
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
  onClose: () => void;
}

const STATUS: Record<CompareRow["status"], { en: string; hi: string }> = {
  usual: { en: "Usual route OK", hi: "सामान्य रास्ता ठीक" },
  usual_with_care: { en: "Usual route, go slow", hi: "सामान्य रास्ता, धीरे" },
  detour: { en: "Must detour", hi: "घूमकर जाएँ" },
  stuck: { en: "No dry route", hi: "कोई सूखा रास्ता नहीं" },
};

/** Same trip for other vehicles: "scooter must detour, but a car/bus can take the usual road". */
function Compare({ rows, lang, current, alt, setAlt }: { rows: CompareRow[]; lang: Lang; current: Vehicle; alt: Vehicle | null;
  setAlt: Props["setAlt"] }) {
  return (
    <div>
      <p className="field-label">{lang === "hi" ? "यही सफ़र, दूसरी गाड़ियाँ" : "Same trip, other vehicles"}</p>
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
                <span className="cicon" aria-hidden>{v.icon}</span>
                <span>
                  <strong>{v[lang]}{r.vehicle === current ? (lang === "hi" ? " (आप)" : " (you)") : ""}</strong>
                  <br />
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
      <p className="small muted">{lang === "hi" ? "किसी गाड़ी पर टैप करें: उसका रास्ता हरे रंग में दिखेगा।" : "Tap a vehicle to see its route in green on the map."}</p>
    </div>
  );
}

const fmt = (p: LonLat | null) => (p ? `${p[1].toFixed(4)}, ${p[0].toFixed(4)}` : "");

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
      <div className="row gap">
        {field === "from" && (
          <button className="chip" onClick={() => getPosition().then(set).catch(() => alert("Location not available"))}>📍 {t("myLocation", p.lang)}</button>
        )}
        <button className={`chip${p.picking === field ? " active" : ""}`} onClick={() => p.setPicking(p.picking === field ? null : field)}>
          👆 {t("tapMap", p.lang)}
        </button>
      </div>
    </div>
  );
}

export default function RoutePanel(p: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [contact, setContact] = useState("");
  const [subMsg, setSubMsg] = useState("");
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
          <strong>👆 {t("tapMap", L)}: <span className={`endpoint inline ${p.picking}`}>{p.picking === "from" ? "A" : "B"}</span></strong>
          <button className="btn" onClick={() => p.setPicking(null)}>{t("cancel", L)}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="sheet" role="dialog" aria-label={t("safeRoute", L)}>
      <header className="sheet-head">
        <h2>🧭 {t("safeRouteFor", L)} {veh.icon} {veh[L]}</h2>
        <button className="icon-btn" onClick={p.onClose} aria-label={t("close", L)}>✕</button>
      </header>

      {!r && (
        <>
          <PlaceField field="from" value={p.from} label={t("from", L)} p={p} />
          <PlaceField field="to" value={p.to} label={t("to", L)} p={p} />
          <button className="btn primary big-btn" disabled={!p.from || !p.to || busy} onClick={go}>
            {busy ? "…" : t("findRoute", L)}
          </button>
          {err && <p className="error-box">{err}</p>}
        </>
      )}

      {r && (
        <div className="route-result">
          <div className={`route-note ${r.safe ? (r.avoided_spots.length ? "ok" : "plain") : "bad"}`} role="status">
            {r.safe ? "✅ " : "⛔ "}{r.note}
          </div>
          <div className="legs">
            {r.normal && r.safe && r.safe.distance_m !== r.normal.distance_m && (
              <div className="leg normal">
                <span className="swatch dashed" aria-hidden /> {t("normalRoute", L)}: {(r.normal.distance_m / 1000).toFixed(1)} km · {Math.round(r.normal.duration_min)} min
                {r.normal.spots_on_route.length > 0 && (
                  <ul className="small">
                    {r.normal.spots_on_route.map((s) => (
                      <li key={s.spotId}>{VERDICT_UI[s.verdict].glyph} {s.place ?? "Flooded spot"} (~{s.depth_high} cm)</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {r.safe && (
              <div className="leg safe">
                <span className="swatch" aria-hidden /> {veh.icon} {(r.safe.distance_m / 1000).toFixed(1)} km · {Math.round(r.safe.duration_min)} min
              </div>
            )}
          </div>
          {!!r.compare?.length && <Compare rows={r.compare} lang={L} current={p.vehicle} alt={p.alt} setAlt={p.setAlt} />}
          {r.safe && p.mode === "live" && (
            <details className="watch">
              <summary>🔔 {t("watchRoute", L)}</summary>
              <div className="row gap">
                <input className="input" value={contact} placeholder={t("contact", L)} onChange={(e) => setContact(e.target.value)} />
                <button className="btn" onClick={watch} disabled={!contact.trim()}>{t("subscribe", L)}</button>
              </div>
              {subMsg && <p className="small muted">{subMsg}</p>}
            </details>
          )}
          <div className="actions">
            <button className="btn" onClick={() => { p.setResult(null); p.setAlt(null, null); }}>{L === "hi" ? "बदलें" : "Change"}</button>
            {r.safe && p.from && p.to && (
              <a className="btn primary" target="_blank" rel="noreferrer"
                href={`https://wa.me/?text=${encodeURIComponent(`Safe ${veh.en.toLowerCase()} route: ${r.note} https://www.google.com/maps/dir/${p.from[1]},${p.from[0]}/${p.to[1]},${p.to[0]}`)}`}>
                📤 {L === "hi" ? "रास्ता भेजें" : "Share route"}
              </a>
            )}
          </div>
          <p className="disclaimer">⚠️ {t("disclaimer", L)}</p>
        </div>
      )}
    </div>
  );
}
