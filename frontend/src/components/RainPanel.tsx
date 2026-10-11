import { ArrowLeft, CloudRain, ExternalLink, MapPin, RefreshCw, Satellite, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ago, t, type Lang } from "../i18n";
import type { LivePosts, RainCity, RainIndia, RainLevel } from "../types";

const LEVEL: Record<RainLevel, { en: string; hi: string }> = {
  dry: { en: "Dry", hi: "सूखा" },
  light: { en: "Light rain", hi: "हल्की बारिश" },
  moderate: { en: "Moderate rain", hi: "मध्यम बारिश" },
  heavy: { en: "Heavy rain", hi: "भारी बारिश" },
  extreme: { en: "Extreme rain", hi: "अत्यधिक बारिश" },
};
const SRC: Record<string, string> = { news: "News", bluesky: "Bluesky", mastodon: "Mastodon", reddit: "Reddit", x: "X", youtube: "YouTube" };

const S = {
  title: { en: "Rain across India, now", hi: "भारत में अभी बारिश" },
  updated: { en: "updated", hi: "अपडेट" },
  note: {
    en: "Rain figures are model data (Open-Meteo): good for “where is it raining”, but not rain-gauge readings.",
    hi: "बारिश के आँकड़े मॉडल डेटा (Open-Meteo) हैं, वर्षामापी की रीडिंग नहीं।",
  },
  now: { en: "now", hi: "अभी" },
  last3: { en: "last 3 h", hi: "पिछले 3 घं" },
  next6: { en: "next 6 h", hi: "अगले 6 घं" },
  live: { en: "Live city", hi: "लाइव शहर" },
  dryRest: { en: "Dry right now", hi: "अभी सूखा" },
  open: { en: "Open this city", hi: "यह शहर खोलें" },
  feed: { en: "Reports from news and social media (last 24 h)", hi: "समाचार और सोशल मीडिया की रिपोर्ट (पिछले 24 घं)" },
  none: {
    en: "No posts about rain or waterlogging here in the last 24 h from the sources checked. That is normal on a calm day.",
    hi: "जाँचे गए स्रोतों में पिछले 24 घंटों में यहाँ बारिश या जलभराव की कोई पोस्ट नहीं मिली। शांत दिन में ऐसा सामान्य है।",
  },
  checked: { en: "Sources checked", hi: "जाँचे गए स्रोत" },
  retry: { en: "Try again", hi: "फिर कोशिश करें" },
  loading: { en: "Loading…", hi: "लोड हो रहा है…" },
  liveAdds: {
    en: "In this live city, posts that name a known flood spot also appear as pins on the map.",
    hi: "इस लाइव शहर में, किसी जानी-पहचानी जलभराव जगह का नाम लेने वाली पोस्ट मैप पर पिन भी बनती हैं।",
  },
} as const;
const s = (k: keyof typeof S, l: Lang) => S[k][l];

interface Props {
  lang: Lang;
  data: RainIndia | null;
  error: string;
  onReload: () => void;
  selected: string | null;
  onSelect: (key: string | null) => void;
  onOpenCity: (key: string) => void;
  onClose: () => void;
}

export default function RainPanel({ lang, data, error, onReload, selected, onSelect, onOpenCity, onClose }: Props) {
  const sel = data?.cities.find((c) => c.key === selected) ?? null;
  const raining = (data?.cities ?? []).filter((c) => c.level !== "dry").sort((a, b) => b.now * 3 + b.past3h + b.next6h - (a.now * 3 + a.past3h + a.next6h));
  const dry = (data?.cities ?? []).filter((c) => c.level === "dry");
  const mins = data ? Math.max(0, Math.round((Date.now() / 1000 - data.updatedAt) / 60)) : 0;

  return (
    <div className="sheet rainsheet" role="dialog" aria-label={s("title", lang)}>
      <header className="sheet-head">
        <div>
          <p className="eyebrow"><CloudRain size={13} aria-hidden /> {lang === "hi" ? "लाइव" : "Live"}</p>
          <h2>{s("title", lang)}</h2>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}><X size={20} /></button>
      </header>

      {error && <p className="error-box" role="alert">{error} <button className="link" onClick={onReload}><RefreshCw size={14} aria-hidden /> {s("retry", lang)}</button></p>}
      {!data && !error && <div className="spinner" aria-label={s("loading", lang)} />}

      {data && !sel && (
        <>
          <div className={`raincall${data.summary.counts.heavy || data.summary.counts.extreme ? " heavy" : ""}`} role="status">
            <strong>{data.summary.headline}</strong>
            <span className="small muted">{s("updated", lang)} {mins} min · {data.summary.raining}/{data.summary.checked}</span>
          </div>
          <ul className="rainlist">
            {raining.map((c) => <CityRow key={c.key} c={c} lang={lang} onClick={() => onSelect(c.key)} />)}
          </ul>
          {raining.length === 0 && <p className="muted">{lang === "hi" ? "जाँचे गए किसी भी शहर में अभी बारिश नहीं है।" : "No rain at any of the places checked."}</p>}
          <details className="rainDry">
            <summary>{s("dryRest", lang)} ({dry.length})</summary>
            <ul className="rainlist compact">{dry.map((c) => <CityRow key={c.key} c={c} lang={lang} onClick={() => onSelect(c.key)} />)}</ul>
          </details>
          <p className="disclaimer">{s("note", lang)}</p>
        </>
      )}

      {data && sel && <CityDetail c={sel} lang={lang} onBack={() => onSelect(null)} onOpenCity={onOpenCity} />}
    </div>
  );
}

function CityRow({ c, lang, onClick }: { c: RainCity; lang: Lang; onClick: () => void }) {
  return (
    <li>
      <button onClick={onClick}>
        <span className={`levelchip ${c.level}`}>{LEVEL[c.level][lang]}</span>
        <span className="rl-main">
          <strong>{c.name}{c.supported && <span className="livebadge"><Satellite size={11} aria-hidden /> {s("live", lang)}</span>}</strong>
          <span className="small muted">{c.state}{c.now < 0.05 && c.past3h > 0 ? ` · ${c.past3h.toFixed(1)} mm ${lang === "hi" ? "अभी-अभी" : "earlier"}` : ""}</span>
        </span>
        <span className="rl-nums"><b>{c.now.toFixed(1)}</b><small> mm/h</small></span>
      </button>
    </li>
  );
}

function CityDetail({ c, lang, onBack, onOpenCity }: { c: RainCity; lang: Lang; onBack: () => void; onOpenCity: (k: string) => void }) {
  const [posts, setPosts] = useState<LivePosts | null>(null);
  const [err, setErr] = useState("");
  const load = () => { setPosts(null); setErr(""); api.rainPosts(c.key).then(setPosts).catch((e) => setErr(String(e.message ?? e))); };
  useEffect(load, [c.key]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="result">
      <button className="link row gap" onClick={onBack}><ArrowLeft size={16} aria-hidden /> {s("title", lang)}</button>
      <div className="citycard">
        <div><h3>{c.name}</h3><span className="small muted">{c.state}</span></div>
        <span className={`levelchip ${c.level}`}>{LEVEL[c.level][lang]}</span>
      </div>
      <div className="rainstats">
        <div><b>{c.now.toFixed(1)}</b><span>mm/h {s("now", lang)}</span></div>
        <div><b>{c.past3h.toFixed(1)}</b><span>mm {s("last3", lang)}</span></div>
        <div><b>{c.next6h.toFixed(1)}</b><span>mm {s("next6", lang)}</span></div>
      </div>
      {c.supported && (
        <>
          <button className="btn primary" onClick={() => onOpenCity(c.key)}><MapPin size={16} aria-hidden /> {s("open", lang)}</button>
          <p className="small muted">{s("liveAdds", lang)}</p>
        </>
      )}

      <section className="rsec">
        <h3 className="sec-title">{s("feed", lang)}</h3>
        {!posts && !err && <div className="spinner" aria-label={s("loading", lang)} />}
        {err && <p className="error-box" role="alert">{err} <button className="link" onClick={load}>{s("retry", lang)}</button></p>}
        {posts && posts.posts.length === 0 && <p className="muted small">{s("none", lang)}</p>}
        <ul className="feed">
          {posts?.posts.map((p) => (
            <li key={p.id}>
              <div className="small muted">{SRC[p.source] ?? p.source} · {p.author} · {ago(Date.now() / 1000 - p.ts, lang)}</div>
              <p>{p.text}</p>
              {p.url && <a className="small" href={p.url} target="_blank" rel="noreferrer"><ExternalLink size={12} aria-hidden /> {lang === "hi" ? "स्रोत खोलें" : "Open source"}</a>}
            </li>
          ))}
        </ul>
        {posts && <p className="small muted">{s("checked", lang)}: {Object.entries(posts.sources_checked).map(([k, v]) => `${SRC[k.replace("google_", "")] ?? k} ${typeof v === "number" ? v : "✕"}`).join(" · ")}</p>}
      </section>
    </div>
  );
}
