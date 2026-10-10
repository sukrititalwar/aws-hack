import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ago, t, type Lang } from "../i18n";
import type { DrainMetrics, DrainRow, LonLat } from "../types";
import { deviceId, frameFromVideo, getPosition, resizeImage, sleep, store, stored } from "../util";

type Tab = "report" | "list" | "metrics";

const SEV = {
  blocked: { en: "Fully blocked", hi: "पूरी तरह बंद", cls: "nogo", glyph: "✕" },
  partial: { en: "Partly blocked", hi: "आंशिक रूप से बंद", cls: "risky", glyph: "!" },
} as const;

const S = {
  report: { en: "Report a drain", hi: "नाले की रिपोर्ट" },
  list: { en: "Priority list", hi: "प्राथमिकता सूची" },
  metrics: { en: "Impact", hi: "असर" },
  intro: {
    en: "A blocked drain only helps if it is cleared before the rain. Send a photo of the drain; we group duplicates, rank by blockage and rain forecast, and a worker is sent.",
    hi: "बारिश से पहले नाला साफ़ हो तभी फ़ायदा है। नाले की फ़ोटो भेजें; हम डुप्लिकेट जोड़कर बारिश के अनुमान से प्राथमिकता तय करते हैं।",
  },
  note: { en: "Note (optional)", hi: "टिप्पणी (वैकल्पिक)" },
  send: { en: "Send report", hi: "रिपोर्ट भेजें" },
  checking: { en: "Checking the drain…", hi: "नाले की जाँच…" },
  thanks: { en: "Report received", hi: "रिपोर्ट मिल गई" },
  grouped: { en: "reports for this drain", hi: "रिपोर्ट इसी नाले की" },
  code: { en: "Dispatcher access code", hi: "डिस्पैचर कोड" },
  worker: { en: "Worker name", hi: "कर्मचारी का नाम" },
  assign: { en: "Assign", hi: "सौंपें" },
  after: { en: "Upload after-photo (clears the drain)", hi: "बाद की फ़ोटो भेजें (नाला साफ़)" },
  none: { en: "No open blocked drains reported.", hi: "कोई बंद नाला दर्ज नहीं।" },
  open: { en: "Open", hi: "खुला" },
  assigned: { en: "Assigned", hi: "सौंपा गया" },
  cleared: { en: "Cleared", hi: "साफ़" },
  before: { en: "Cleared before rain", hi: "बारिश से पहले साफ़" },
  median: { en: "Median hours to clear", hi: "साफ़ होने का औसत समय (घंटे)" },
  repeat: { en: "Repeat blockages", hi: "दोबारा बंद" },
  reported: { en: "Reported", hi: "दर्ज" },
} as const;
const s = (k: keyof typeof S, l: Lang) => S[k][l];
const rc = (n: number, l: Lang) => (l === "hi" ? `${n} रिपोर्ट इसी नाले की` : `${n} report${n === 1 ? "" : "s"} for this drain`);

interface Props {
  lang: Lang;
  center: LonLat;
  onClose: () => void;
}

export default function DrainSheet({ lang, center, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("list");
  const [rows, setRows] = useState<DrainRow[] | null>(null);
  const [metrics, setMetrics] = useState<DrainMetrics | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<DrainRow | null>(null);
  const [token, setToken] = useState(stored<string>("adminToken", ""));

  const load = useCallback(() => {
    api.drains().then((r) => setRows(r.drains)).catch((e) => setErr(String(e.message ?? e)));
    api.drainMetrics().then(setMetrics).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="sheet" role="dialog" aria-label={t("drains", lang)}>
      <header className="sheet-head">
        <h2>🕳️ {t("drains", lang)} · DrainReady</h2>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}>✕</button>
      </header>
      <div className="seg tabs" role="tablist">
        {(["list", "report", "metrics"] as Tab[]).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => { setTab(k); setOpen(null); }}>{s(k, lang)}</button>
        ))}
      </div>
      {err && <p className="error-box">{err}</p>}

      {tab === "report" && <ReportTab lang={lang} center={center} onDone={() => { load(); setTab("list"); }} />}

      {tab === "list" && !open && (
        <>
          {rows && rows.length === 0 && <p className="muted">{s("none", lang)}</p>}
          <ul className="drainlist">
            {rows?.map((r) => {
              const sev = SEV[r.severity ?? "partial"];
              return (
                <li key={r.groupId}>
                  <button onClick={() => setOpen(r)}>
                    <span className={`sevchip ${sev.cls}`}><i aria-hidden>{sev.glyph}</i> {sev[lang]}</span>
                    <span className="drain-main">
                      <strong>{r.nearHotspot ?? (r.blockage_type ? r.blockage_type : lang === "hi" ? "नाला" : "Drain")}</strong>
                      <span className="small muted">
                        {rc(r.reportCount, lang)} · {ago(Date.now() / 1000 - r.firstReported, lang)}
                        {r.assignedTo ? ` · 👷 ${r.assignedTo}` : ""}
                      </span>
                      <span className="small">{r.urgent ? "🌧 " : ""}{r.reasons.join(" · ")}</span>
                    </span>
                    <span className="score" title="priority score">{r.score.toFixed(1)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {tab === "list" && open && <DetailTab row={open} lang={lang} token={token} setToken={(v) => { setToken(v); store("adminToken", v); }} onBack={() => { setOpen(null); load(); }} />}

      {tab === "metrics" && metrics && (
        <div className="metrics">
          <div className="metric"><b>{metrics.cleared_before_rain}</b><span>{s("before", lang)} <small>({metrics.rain_forecast_cases} {lang === "hi" ? "बारिश वाले मामले" : "rain cases"})</small></span></div>
          <div className="metric"><b>{metrics.median_hours_to_clear ?? "–"}</b><span>{s("median", lang)}</span></div>
          <div className="metric"><b>{metrics.repeat_blockages}</b><span>{s("repeat", lang)}</span></div>
          <div className="metric"><b>{metrics.reported}</b><span>{s("reported", lang)} · {metrics.open} {s("open", lang)} · {metrics.assigned} {s("assigned", lang)} · {metrics.cleared} {s("cleared", lang)}</span></div>
          <p className="small muted">{metrics.basis}</p>
        </div>
      )}
    </div>
  );
}

function ReportTab({ lang, center, onDone }: { lang: Lang; center: LonLat; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DrainRow | null>(null);
  const [error, setError] = useState("");
  const pos = useRef<LonLat>(center);
  useEffect(() => { getPosition().then((p) => { pos.current = p; }).catch(() => undefined); }, []);

  async function pick(f?: File) {
    if (!f) return;
    try {
      if (f.type.startsWith("video/")) f = await frameFromVideo(f);
    } catch (e) { return setError(e instanceof Error ? e.message : String(e)); }
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError("");
  }

  async function send() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const blob = await resizeImage(file);
      const up = await api.drainUploadUrl({ lat: pos.current[1], lon: pos.current[0], note: note || undefined, deviceId: deviceId() });
      await api.uploadPhoto(up.uploadUrl, up.fields, blob);
      for (let i = 0; i < 40; i++) {
        await sleep(1800);
        const d = await api.drain(up.reportId).catch(() => null);
        if (d && d.status !== "analysing") {
          if (d.status === "rejected") setError(d.rejection_reason || "Could not use this photo.");
          else setResult(d);
          return;
        }
      }
      setError("Analysis is taking too long. Please try again.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    const sev = SEV[result.severity ?? "partial"];
    return (
      <div className="result">
        <div className={`big ${sev.cls}`}>
          <div className="bigline"><span>✅ {s("thanks", lang)}</span></div>
          <p className="bigwhy">{sev[lang]}{result.blockage_type ? ` · ${result.blockage_type}` : ""}</p>
        </div>
        {(lang === "hi" ? result.reasoning_hi : result.reasoning) && <p className="reasoning">“{lang === "hi" ? result.reasoning_hi : result.reasoning}”</p>}
        <p className="small">{rc(result.reportCount, lang)}. {result.urgent ? (lang === "hi" ? "बारिश का अनुमान है: जल्दी साफ़ कराया जाएगा।" : "Rain is forecast, so this is prioritised.") : ""}</p>
        <div className="actions"><button className="btn primary" onClick={onDone}>{s("list", lang)}</button></div>
      </div>
    );
  }
  return (
    <div>
      <p className="muted small">{s("intro", lang)}</p>
      {!file ? (
        <label className="camera">
          <input type="file" accept="image/*,video/*" capture="environment" onChange={(e) => pick(e.target.files?.[0])} />
          <span className="camera-icon" aria-hidden>🕳️</span>
          <span>{t("photoOrVideo", lang)}</span>
        </label>
      ) : (
        <img className="thumb" src={preview} alt="" />
      )}
      <label className="field-label" htmlFor="dnote">{s("note", lang)}</label>
      <input id="dnote" className="input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="error-box">{error}</p>}
      <button className="btn primary big-btn" disabled={!file || busy} onClick={send}>{busy ? s("checking", lang) : s("send", lang)}</button>
    </div>
  );
}

function DetailTab({ row, lang, token, setToken, onBack }: { row: DrainRow; lang: Lang; token: string; setToken: (v: string) => void; onBack: () => void }) {
  const [d, setD] = useState<DrainRow>(row);
  const [worker, setWorker] = useState("");
  const [msg, setMsg] = useState("");
  const refresh = () => api.drain(row.groupId).then(setD).catch(() => undefined);
  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const sev = SEV[d.severity ?? "partial"];

  async function assign() {
    try { await api.assignDrain(d.groupId, worker.trim(), token); setMsg("✅"); refresh(); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  async function afterPhoto(f?: File) {
    if (!f) return;
    setMsg(lang === "hi" ? "जाँच हो रही है…" : "Checking the after-photo…");
    try {
      const up = await api.afterUrl(d.groupId, token);
      await api.uploadPhoto(up.uploadUrl, up.fields, await resizeImage(f));
      for (let i = 0; i < 30; i++) {
        await sleep(1800);
        const x = await api.drain(d.groupId);
        if (x.status === "cleared" || x.afterNote) { setD(x); setMsg(x.status === "cleared" ? "✅" : x.afterNote ?? ""); return; }
      }
      setMsg("Still checking, refresh in a moment.");
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div className="result">
      <button className="link" onClick={onBack}>← {s("list", lang)}</button>
      <div className={`big ${sev.cls}`}>
        <div className="bigline"><span>{sev[lang]}</span><span className="bigglyph">{sev.glyph}</span></div>
        <p className="bigwhy">{d.reasons.join(" · ")}</p>
      </div>
      {d.photoUrl && <img className="photo" src={d.photoUrl} alt="Reported drain" />}
      {d.afterUrl && <><p className="small muted">{lang === "hi" ? "बाद की फ़ोटो" : "After"} {d.clearanceVerified ? "✔ verified clear" : ""}</p><img className="photo" src={d.afterUrl} alt="After clearance" /></>}
      {(lang === "hi" ? d.reasoning_hi : d.reasoning) && <p className="reasoning">“{lang === "hi" ? d.reasoning_hi : d.reasoning}”</p>}
      <p className="small">{d.status === "assigned" ? `👷 ${d.assignedTo}` : s(d.status === "cleared" ? "cleared" : "open", lang)} · {rc(d.reportCount, lang)}</p>
      <a className="btn" target="_blank" rel="noreferrer" href={`https://www.google.com/maps?q=${d.lat},${d.lon}`}>🗺️ {lang === "hi" ? "मैप में खोलें" : "Open in Maps"}</a>

      {d.status !== "cleared" && (
        <details className="watch" open={!!token}>
          <summary>👷 {lang === "hi" ? "डिस्पैचर" : "Dispatcher"}</summary>
          <input className="input" type="password" value={token} placeholder={s("code", lang)} onChange={(e) => setToken(e.target.value)} />
          <div className="row gap" style={{ marginTop: 8 }}>
            <input className="input" value={worker} placeholder={s("worker", lang)} onChange={(e) => setWorker(e.target.value)} />
            <button className="btn" disabled={!worker.trim() || !token} onClick={assign}>{s("assign", lang)}</button>
          </div>
          <label className="btn" style={{ marginTop: 8 }}>
            📷 {s("after", lang)}
            <input type="file" accept="image/*" capture="environment" hidden disabled={!token} onChange={(e) => afterPhoto(e.target.files?.[0])} />
          </label>
        </details>
      )}
      {msg && <p className="small" role="status">{msg}</p>}
    </div>
  );
}
