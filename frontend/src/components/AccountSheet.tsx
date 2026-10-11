import { Briefcase, House, LocateFixed, LogOut, MapPin, Navigation, Search, Trash2, X } from "lucide-react";
import { useState } from "react";
import { geocode, hasLocationKey } from "../api";
import { authApi, AuthError, authEnabled, MOCK, useAuth } from "../auth";
import { t, type Lang } from "../i18n";
import { usePlaces } from "../places";
import type { LonLat, PlaceKind, SavedPlace } from "../types";
import { getPosition } from "../util";

type Step = "signin" | "signup" | "confirm" | "forgot" | "reset";

const S = {
  title: { en: "Account", hi: "खाता" },
  signin: { en: "Sign in", hi: "साइन इन" },
  signup: { en: "Create account", hi: "खाता बनाएँ" },
  email: { en: "Email", hi: "ईमेल" },
  password: { en: "Password", hi: "पासवर्ड" },
  newPassword: { en: "New password", hi: "नया पासवर्ड" },
  pwHint: { en: "At least 8 characters with a number and a lowercase letter.", hi: "कम से कम 8 अक्षर, एक अंक और एक छोटा अक्षर।" },
  code: { en: "6-digit code from your email", hi: "ईमेल में आया 6 अंकों का कोड" },
  confirm: { en: "Confirm email", hi: "ईमेल की पुष्टि करें" },
  sent: { en: "We emailed you a code.", hi: "हमने आपको कोड ईमेल किया है।" },
  resend: { en: "Send the code again", hi: "कोड फिर भेजें" },
  forgot: { en: "Forgot password?", hi: "पासवर्ड भूल गए?" },
  reset: { en: "Reset password", hi: "पासवर्ड बदलें" },
  back: { en: "Back to sign in", hi: "साइन इन पर वापस" },
  haveNo: { en: "No account yet?", hi: "खाता नहीं है?" },
  haveYes: { en: "Already have an account?", hi: "पहले से खाता है?" },
  why: { en: "Sign in to save Home, Work and other frequent places and use them in one tap when planning a safe route.", hi: "Home, Work और बार-बार जाने वाली जगहें सेव करें, और सुरक्षित रास्ता खोजते समय एक टैप में इस्तेमाल करें।" },
  off: { en: "Sign-in is not set up on this deployment yet.", hi: "इस ऐप में साइन इन अभी चालू नहीं है।" },
  signout: { en: "Sign out", hi: "साइन आउट" },
  places: { en: "Saved places", hi: "सेव की हुई जगहें" },
  noPlaces: { en: "No saved places yet. Add Home or Work below.", hi: "अभी कोई जगह सेव नहीं है। नीचे Home या Work जोड़ें।" },
  add: { en: "Add a place", hi: "जगह जोड़ें" },
  name: { en: "Name (e.g. Gym)", hi: "नाम (जैसे जिम)" },
  searchAddr: { en: "Search an address", hi: "पता खोजें" },
  here: { en: "Use my location", hi: "मेरी जगह इस्तेमाल करें" },
  save: { en: "Save place", hi: "जगह सेव करें" },
  routeTo: { en: "Route here", hi: "यहाँ का रास्ता" },
  del: { en: "Delete", hi: "हटाएँ" },
  mock: { en: "Local test mode: any email works, nothing is sent.", hi: "लोकल टेस्ट मोड: कोई भी ईमेल चलेगा।" },
} as const;
const s = (k: keyof typeof S, l: Lang) => S[k][l];

export const KIND_ICON = { home: House, work: Briefcase, other: MapPin } as const;
const KIND_LABEL: Record<PlaceKind, { en: string; hi: string }> = {
  home: { en: "Home", hi: "घर" }, work: { en: "Work", hi: "ऑफ़िस" }, other: { en: "Other", hi: "अन्य" },
};

interface Props {
  lang: Lang;
  center: LonLat;
  onClose: () => void;
  onRoute: (p: LonLat) => void;
}

export default function AccountSheet({ lang, center, onClose, onRoute }: Props) {
  const { user } = useAuth();
  return (
    <div className="sheet" role="dialog" aria-label={s("title", lang)}>
      <header className="sheet-head">
        <div><p className="eyebrow">{s("title", lang)}</p><h2>{user ? user.email : s("signin", lang)}</h2></div>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}><X size={20} /></button>
      </header>
      {!authEnabled ? <p className="muted">{s("off", lang)}</p> : user ? <Signed lang={lang} center={center} onRoute={onRoute} onClose={onClose} /> : <Forms lang={lang} />}
    </div>
  );
}

function Forms({ lang }: { lang: Lang }) {
  const [step, setStep] = useState<Step>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) {
      if (e instanceof AuthError && e.code === "needs_confirmation") { setStep("confirm"); setInfo(s("sent", lang)); authApi.resend(email).catch(() => undefined); }
      else setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }
  const go = (st: Step) => { setStep(st); setError(""); setInfo(""); setCode(""); };
  const em = email.trim().toLowerCase();

  return (
    <form className="authform" onSubmit={(e) => {
      e.preventDefault();
      if (step === "signin") run(() => authApi.signIn(em, password));
      if (step === "signup") run(async () => { await authApi.signUp(em, password); go("confirm"); setInfo(s("sent", lang)); if (MOCK) await authApi.signIn(em, password); });
      if (step === "confirm") run(async () => { await authApi.confirm(em, code); await authApi.signIn(em, password).catch(() => go("signin")); });
      if (step === "forgot") run(async () => { await authApi.forgot(em); setStep("reset"); setInfo(s("sent", lang)); });
      if (step === "reset") run(async () => { await authApi.resetPassword(em, code, password); go("signin"); setInfo(lang === "hi" ? "पासवर्ड बदल गया। साइन इन करें।" : "Password changed. Sign in."); });
    }}>
      {step === "signin" && <p className="muted small">{s("why", lang)}</p>}
      {MOCK && <p className="small review-tag">{s("mock", lang)}</p>}
      {info && <p className="small" role="status">{info}</p>}

      <label className="field-label" htmlFor="acc-email">{s("email", lang)}</label>
      <input id="acc-email" className="input" type="email" autoComplete="email" inputMode="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} disabled={busy || step === "confirm" || step === "reset"} />

      {(step === "signin" || step === "signup" || step === "reset") && (
        <>
          <label className="field-label" htmlFor="acc-pw">{step === "reset" ? s("newPassword", lang) : s("password", lang)}</label>
          <input id="acc-pw" className="input" type="password" required minLength={8} value={password}
            autoComplete={step === "signin" ? "current-password" : "new-password"} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
          {step !== "signin" && <p className="small muted">{s("pwHint", lang)}</p>}
        </>
      )}
      {(step === "confirm" || step === "reset") && (
        <>
          <label className="field-label" htmlFor="acc-code">{s("code", lang)}</label>
          <input id="acc-code" className="input" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} disabled={busy} />
        </>
      )}
      {error && <p className="error-box" role="alert">{error}</p>}

      <button className="btn primary big-btn" type="submit" disabled={busy || !em || (step !== "forgot" && step !== "confirm" && password.length < 8 && step !== "signin") }>
        {busy ? "…" : step === "signin" ? s("signin", lang) : step === "signup" ? s("signup", lang) : step === "confirm" ? s("confirm", lang) : s("reset", lang)}
      </button>

      <div className="authlinks">
        {step === "signin" && <>
          <button type="button" className="link" onClick={() => go("forgot")}>{s("forgot", lang)}</button>
          <span className="muted small">{s("haveNo", lang)} <button type="button" className="link" onClick={() => go("signup")}>{s("signup", lang)}</button></span>
        </>}
        {step === "signup" && <span className="muted small">{s("haveYes", lang)} <button type="button" className="link" onClick={() => go("signin")}>{s("signin", lang)}</button></span>}
        {step === "confirm" && <button type="button" className="link" onClick={() => run(async () => { await authApi.resend(em); setInfo(s("sent", lang)); })}>{s("resend", lang)}</button>}
        {(step === "forgot" || step === "reset" || step === "confirm") && <button type="button" className="link" onClick={() => go("signin")}>{s("back", lang)}</button>}
      </div>
    </form>
  );
}

function Signed({ lang, center, onRoute, onClose }: { lang: Lang; center: LonLat; onRoute: (p: LonLat) => void; onClose: () => void }) {
  const { places, loading, error, add, remove, reload } = usePlaces();
  return (
    <div className="result">
      <section className="rsec">
        <h3 className="sec-title">{s("places", lang)}</h3>
        {loading && <div className="spinner" aria-label="Loading" />}
        {error && <p className="error-box" role="alert">{error} <button className="link" onClick={reload}>{lang === "hi" ? "फिर कोशिश करें" : "Try again"}</button></p>}
        {!loading && !error && places.length === 0 && <p className="muted small">{s("noPlaces", lang)}</p>}
        <ul className="placelist">
          {places.map((p) => <PlaceRow key={p.placeId} p={p} lang={lang} onRoute={() => { onRoute([p.lon, p.lat]); onClose(); }} onDelete={() => remove(p.placeId)} />)}
        </ul>
      </section>
      <AddPlace lang={lang} center={center} add={add} />
      <button className="btn" onClick={() => { authApi.signOut(); onClose(); }}><LogOut size={16} aria-hidden /> {s("signout", lang)}</button>
    </div>
  );
}

function PlaceRow({ p, lang, onRoute, onDelete }: { p: SavedPlace; lang: Lang; onRoute: () => void; onDelete: () => Promise<void> }) {
  const Icon = KIND_ICON[p.kind];
  const [err, setErr] = useState("");
  return (
    <li>
      <span className="pl-icon"><Icon size={18} aria-hidden /></span>
      <span className="pl-main">
        <strong>{p.label}</strong>
        <span className="small muted">{p.address || `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`}</span>
        {err && <span className="small" role="alert" style={{ color: "var(--nogo)" }}>{err}</span>}
      </span>
      <button className="icon-btn sm" onClick={onRoute} aria-label={`${s("routeTo", lang)}: ${p.label}`} title={s("routeTo", lang)}><Navigation size={16} /></button>
      <button className="icon-btn sm" onClick={() => onDelete().catch((e) => setErr(String(e.message ?? e)))} aria-label={`${s("del", lang)}: ${p.label}`} title={s("del", lang)}><Trash2 size={16} /></button>
    </li>
  );
}

/** Add a place from the device location or an address search (Amazon Location Places). */
function AddPlace({ lang, center, add }: { lang: Lang; center: LonLat; add: (b: { label: string; kind: PlaceKind; lat: number; lon: number; address?: string }) => Promise<void> }) {
  const [kind, setKind] = useState<PlaceKind>("home");
  const [name, setName] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ title: string; pos: LonLat }[]>([]);
  const [pick, setPick] = useState<{ pos: LonLat; title?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  async function locate() {
    setMsg(null);
    try { setPick({ pos: await getPosition(), title: lang === "hi" ? "मेरी जगह" : "My location" }); }
    catch { setMsg({ text: lang === "hi" ? "जगह नहीं मिली। पता खोजें।" : "Location is not available. Search an address instead.", bad: true }); }
  }
  async function search() {
    if (!q.trim()) return;
    setMsg(null);
    const r = await geocode(q, center);
    setHits(r);
    if (!r.length) setMsg({ text: lang === "hi" ? "कोई नतीजा नहीं मिला।" : "No results. Try a landmark or area name.", bad: true });
  }
  async function save() {
    if (!pick) return;
    setBusy(true);
    setMsg(null);
    try {
      await add({ label: kind === "other" ? name.trim() : KIND_LABEL[kind].en, kind, lat: pick.pos[1], lon: pick.pos[0], address: pick.title });
      setPick(null); setName(""); setQ(""); setHits([]);
      setMsg({ text: lang === "hi" ? "सेव हो गया" : "Saved" });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), bad: true });
    } finally { setBusy(false); }
  }

  return (
    <section className="rsec">
      <h3 className="sec-title">{s("add", lang)}</h3>
      <div className="row gap chips" role="radiogroup" aria-label="Place type">
        {(["home", "work", "other"] as PlaceKind[]).map((k) => {
          const Icon = KIND_ICON[k];
          return <button key={k} type="button" role="radio" aria-checked={kind === k} className={`chip${kind === k ? " active" : ""}`} onClick={() => setKind(k)}><Icon size={16} aria-hidden /> {KIND_LABEL[k][lang]}</button>;
        })}
      </div>
      {kind === "other" && <input className="input" style={{ marginTop: 8 }} maxLength={40} placeholder={s("name", lang)} value={name} onChange={(e) => setName(e.target.value)} />}
      <div className="row gap chips" style={{ marginTop: 8 }}>
        <button type="button" className="chip" onClick={locate}><LocateFixed size={16} aria-hidden /> {s("here", lang)}</button>
      </div>
      {hasLocationKey && (
        <div className="row" style={{ marginTop: 8, gap: 8 }}>
          <input className="input" placeholder={s("searchAddr", lang)} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }} />
          <button type="button" className="icon-btn" onClick={search} aria-label={s("searchAddr", lang)}><Search size={18} /></button>
        </div>
      )}
      {hits.length > 0 && <ul className="hits">{hits.map((h) => <li key={h.title + h.pos.join()}><button type="button" className="link" onClick={() => { setPick({ pos: h.pos, title: h.title }); setHits([]); }}>{h.title}</button></li>)}</ul>}
      {pick && <p className="small" role="status"><MapPin size={14} aria-hidden /> {pick.title ?? `${pick.pos[1].toFixed(4)}, ${pick.pos[0].toFixed(4)}`}</p>}
      <button className="btn primary" style={{ marginTop: 8 }} disabled={!pick || busy || (kind === "other" && !name.trim())} onClick={save}>{busy ? "…" : s("save", lang)}</button>
      {msg && <p className={msg.bad ? "error-box" : "small"} role={msg.bad ? "alert" : "status"}>{msg.text}</p>}
    </section>
  );
}
