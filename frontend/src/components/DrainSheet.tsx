import { ArrowLeft, Camera, CircleAlert, CircleCheck, CloudRain, Eye, HardHat, Map as MapIcon, RefreshCw, X } from "lucide-react";
import { VerdictIcon } from "../icons";
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
  uploading: { en: "Uploading the photo…", hi: "फ़ोटो भेज रहे हैं…" },
  analysing: { en: "Analysing the drain…", hi: "नाले की जाँच…" },
  retry: { en: "Retry analysis", hi: "फिर से जाँचें" },
  tryAgain: { en: "Try again", hi: "फिर कोशिश करें" },
  thanks: { en: "Report received", hi: "रिपोर्ट मिल गई" },
  code: { en: "Dispatcher access code", hi: "डिस्पैचर कोड" },
  worker: { en: "Worker name", hi: "कर्मचारी का नाम" },
  assign: { en: "Assign", hi: "सौंपें" },
  after: { en: "Upload after-photo", hi: "बाद की फ़ोटो भेजें" },
  none: { en: "No open blocked drains reported.", hi: "कोई बंद नाला दर्ज नहीं।" },
  open: { en: "Open", hi: "खुला" },
  assigned: { en: "Assigned", hi: "सौंपा गया" },
  cleared: { en: "Cleared", hi: "साफ़" },
  before: { en: "Cleared before rain", hi: "बारिश से पहले साफ़" },
  median: { en: "Median hours to clear", hi: "साफ़ होने का औसत समय (घंटे)" },
  repeat: { en: "Repeat blockages", hi: "दोबारा बंद" },
  reported: { en: "Reported", hi: "दर्ज" },
  review: { en: "Needs review", hi: "जाँच ज़रूरी" },
  awaiting: { en: "Awaiting dispatcher", hi: "डिस्पैचर की पुष्टि बाकी" },
  confirmClear: { en: "Confirm clear", hi: "साफ़ है, पुष्टि करें" },
  rejectPhoto: { en: "Reject photo", hi: "फ़ोटो अस्वीकार" },
} as const;
const s = (k: keyof typeof S, l: Lang) => S[k][l];
const rc = (n: number, l: Lang) => (l === "hi" ? `${n} रिपोर्ट इसी नाले की` : `${n} report${n === 1 ? "" : "s"} for this drain`);

/** Always say how a rating was produced when it was not the full AI. */
function FallbackNote({ d, lang }: { d: Pick<DrainRow, "analysisMode" | "analysisError">; lang: Lang }) {
  if (!d.analysisMode || d.analysisMode === "bedrock") return null;
  const basic = d.analysisMode === "rekognition_labels";
  return (
    <div className="inspect-banner" role="note">
      <strong><Eye size={16} aria-hidden /> {lang === "hi" ? "स्वचालित AI उपलब्ध नहीं" : "AI analysis unavailable"}</strong>
      <span>
        {basic
          ? (lang === "hi" ? "यह केवल सामान्य इमेज लेबल से आँका गया है और कम भरोसे का है। काम तय करने से पहले किसी व्यक्ति से जाँच कराएँ।"
                          : "Rated from basic image labels only (low confidence). A person should check it before work is scheduled.")
          : (lang === "hi" ? "कोई स्वचालित जाँच नहीं हुई। फ़ोटो किसी व्यक्ति को देखनी होगी।" : "Not rated automatically. A person needs to look at the photo.")}
      </span>
      {d.analysisError && <span className="small">({d.analysisError})</span>}
    </div>
  );
}

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
    api.drains().then((r) => { setRows(r.drains); setErr(""); }).catch((e) => setErr(String(e.message ?? e)));
    api.drainMetrics().then(setMetrics).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="sheet" role="dialog" aria-label={t("drains", lang)}>
      <header className="sheet-head">
        <div><p className="eyebrow">DrainReady</p><h2>{t("drains", lang)}</h2></div>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}><X size={20} /></button>
      </header>
      <div className="seg tabs" role="tablist">
        {(["list", "report", "metrics"] as Tab[]).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => { setTab(k); setOpen(null); }}>{s(k, lang)}</button>
        ))}
      </div>
      {err && <p className="error-box" role="alert">{err} <button className="link" onClick={load}>{s("tryAgain", lang)}</button></p>}

      {tab === "report" && <ReportTab lang={lang} center={center} onDone={() => { load(); setTab("list"); }} />}

      {tab === "list" && !open && (
        <>
          {!rows && !err && <div className="spinner" aria-label="Loading" />}
          {rows && rows.length === 0 && <p className="muted">{s("none", lang)}</p>}
          <ul className="drainlist">
            {rows?.map((r) => {
              const sev = SEV[r.severity ?? "partial"];
              return (
                <li key={r.groupId}>
                  <button onClick={() => setOpen(r)}>
                    <span className={`sevchip ${sev.cls}`}><VerdictIcon cls={sev.cls} size={13} /> {sev[lang]}</span>
                    <span className="drain-main">
                      <strong>{r.nearHotspot ?? (r.blockage_type ? r.blockage_type : lang === "hi" ? "नाला" : "Drain")}</strong>
                      <span className="small muted">
                        {rc(r.reportCount, lang)} · {ago(Date.now() / 1000 - r.firstReported, lang)}
                        {r.assignedTo ? <> · <HardHat size={13} aria-label="assigned to" /> {r.assignedTo}</> : ""}
                      </span>
                      <span className="small">{r.urgent ? <CloudRain size={13} aria-label="rain forecast" /> : null} {r.reasons.join(" · ")}</span>
                      {(r.awaitingReview || r.needsReview) && (
                        <span className="small review-tag"><CircleAlert size={13} aria-hidden /> {r.awaitingReview ? s("awaiting", lang) : s("review", lang)}</span>
                      )}
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

      {tab === "metrics" && !metrics && !err && <div className="spinner" aria-label="Loading" />}
      {tab === "metrics" && metrics && (
        <div className="metrics">
          <div className="metric"><b>{metrics.cleared_before_rain}</b><span>{s("before", lang)} <small>({metrics.rain_forecast_cases} {lang === "hi" ? "बारिश वाले मामले" : "rain cases"})</small></span></div>
          <div className="metric"><b>{metrics.median_hours_to_clear ?? "–"}</b><span>{s("median", lang)}</span></div>
          <div className="metric"><b>{metrics.repeat_blockages}</b><span>{s("repeat", lang)}</span></div>
          <div className="metric"><b>{metrics.reported}</b><span>{s("reported", lang)} · {metrics.open} {s("open", lang)} · {metrics.assigned} {s("assigned", lang)} · {metrics.cleared} {s("cleared", lang)}
            {metrics.cleared ? <small> ({metrics.cleared_ai_verified ?? 0} {lang === "hi" ? "AI से सत्यापित" : "AI-verified"}, {metrics.cleared_manual ?? 0} {lang === "hi" ? "डिस्पैचर द्वारा" : "by dispatcher"})</small> : null}</span></div>
          <p className="small muted">{metrics.basis}</p>
        </div>
      )}
    </div>
  );
}

type Stage = "idle" | "uploading" | "analysing" | "failed";

function ReportTab({ lang, center, onDone }: { lang: Lang; center: LonLat; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [note, setNote] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [secs, setSecs] = useState(0);
  const [result, setResult] = useState<DrainRow | null>(null);
  const [error, setError] = useState("");
  const [retryable, setRetryable] = useState(false);
  const reportId = useRef<string | null>(null);
  const pos = useRef<LonLat>(center);
  useEffect(() => { getPosition().then((p) => { pos.current = p; }).catch(() => undefined); }, []);

  // elapsed-time ticker so a slow analysis never looks frozen
  useEffect(() => {
    if (stage !== "uploading" && stage !== "analysing") return;
    setSecs(0);
    const id = setInterval(() => setSecs((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, [stage]);

  async function pick(f?: File) {
    if (!f) return;
    try {
      if (f.type.startsWith("video/")) f = await frameFromVideo(f);
    } catch (e) { return setError(e instanceof Error ? e.message : String(e)); }
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError("");
    reportId.current = null;
  }

  function fail(msg: string, canRetry: boolean) {
    setError(msg);
    setRetryable(canRetry);
    setStage("failed");
  }

  async function waitForAnalysis(id: string) {
    setStage("analysing");
    for (let i = 0; i < 45; i++) {
      await sleep(1800);
      const d = await api.drain(id).catch(() => null);
      if (!d || d.status === "analysing") continue;
      if (d.status === "rejected") { reportId.current = null; return fail(d.rejection_reason || "This photo could not be used.", false); }
      if (d.status === "error") return fail(d.rejection_reason || "The analysis failed.", true);
      setResult(d);
      setStage("idle");
      return;
    }
    fail(lang === "hi" ? "जाँच में बहुत समय लग रहा है। फिर से जाँचें दबाएँ।" : "The analysis is taking too long. Tap retry.", true);
  }

  async function send() {
    if (!file) return;
    setError("");
    setRetryable(false);
    try {
      if (!reportId.current) {
        setStage("uploading");
        const blob = await resizeImage(file);
        const up = await api.drainUploadUrl({ lat: pos.current[1], lon: pos.current[0], note: note || undefined, deviceId: deviceId() });
        reportId.current = up.reportId;
        await api.uploadPhoto(up.uploadUrl, up.fields, blob);
      }
      await waitForAnalysis(reportId.current);
    } catch (e) {
      // The upload failed: the photo has to be sent again.
      fail(e instanceof Error ? e.message : String(e), false);
      reportId.current = null;
    }
  }

  async function retry() {
    if (!reportId.current) return send();
    setError("");
    try {
      await api.retryDrain(reportId.current, deviceId());
      await waitForAnalysis(reportId.current);
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      if (/never arrived/i.test(m)) reportId.current = null;   // photo is not in S3: re-upload
      fail(m, false);
    }
  }

  if (result) {
    const sev = SEV[result.severity ?? "partial"];
    return (
      <div className="result">
        <div className={`big ${sev.cls}`}>
          <div className="bigline"><CircleCheck size={22} aria-hidden /><span>{s("thanks", lang)}</span></div>
          <p className="bigwhy">{sev[lang]}{result.blockage_type ? ` · ${result.blockage_type}` : ""}</p>
        </div>
        <FallbackNote d={result} lang={lang} />
        {(lang === "hi" ? result.reasoning_hi : result.reasoning) && <p className="reasoning">“{lang === "hi" ? result.reasoning_hi : result.reasoning}”</p>}
        <p className="small">{rc(result.reportCount, lang)}. {result.urgent ? (lang === "hi" ? "बारिश का अनुमान है: जल्दी साफ़ कराया जाएगा।" : "Rain is forecast, so this is prioritised.") : ""}</p>
        <div className="actions"><button className="btn primary" onClick={onDone}>{s("list", lang)}</button></div>
      </div>
    );
  }
  const busy = stage === "uploading" || stage === "analysing";
  return (
    <div>
      <p className="muted small">{s("intro", lang)}</p>
      {!file ? (
        <label className="camera">
          <input type="file" accept="image/*,video/*" capture="environment" onChange={(e) => pick(e.target.files?.[0])} />
          <span className="camera-icon" aria-hidden><Camera size={44} strokeWidth={1.5} /></span>
          <span>{t("photoOrVideo", lang)}</span>
        </label>
      ) : (
        <img className="thumb" src={preview} alt="" />
      )}
      <label className="field-label" htmlFor="dnote">{s("note", lang)}</label>
      <input id="dnote" className="input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} disabled={busy} />
      {busy && (
        <p className="progress" role="status" aria-live="polite">
          <span className="spinner inline" aria-hidden /> {stage === "uploading" ? s("uploading", lang) : s("analysing", lang)} <span className="muted">{secs}s</span>
        </p>
      )}
      {stage === "failed" && (
        <div className="error-box" role="alert">
          <p>{error}</p>
          <button className="btn" onClick={retryable ? retry : send}><RefreshCw size={16} aria-hidden /> {retryable ? s("retry", lang) : s("tryAgain", lang)}</button>
        </div>
      )}
      {error && stage === "idle" && <p className="error-box" role="alert">{error}</p>}
      {stage !== "failed" && <button className="btn primary big-btn" disabled={!file || busy} onClick={send}>{s("send", lang)}</button>}
    </div>
  );
}

function DetailTab({ row, lang, token, setToken, onBack }: { row: DrainRow; lang: Lang; token: string; setToken: (v: string) => void; onBack: () => void }) {
  const [d, setD] = useState<DrainRow>(row);
  const [worker, setWorker] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState("");
  const refresh = () => api.drain(row.groupId).then(setD).catch((e) => setMsg({ text: String(e.message ?? e), bad: true }));
  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const sev = SEV[d.severity ?? "partial"];

  async function run(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setMsg(null);
    try {
      const text = await fn();
      if (text) setMsg({ text });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), bad: true });
    } finally {
      setBusy("");
      refresh();
    }
  }

  const assign = () => run("assign", async () => { await api.assignDrain(d.groupId, worker.trim(), token); return lang === "hi" ? "सौंप दिया" : "Assigned"; });
  const decide = (decision: "clear" | "reject") => run(decision, async () => {
    await api.confirmDrain(d.groupId, decision, token);
    return decision === "clear" ? (lang === "hi" ? "साफ़ दर्ज किया (डिस्पैचर द्वारा)" : "Marked clear (confirmed by dispatcher)") : (lang === "hi" ? "फ़ोटो अस्वीकार" : "After-photo rejected");
  });
  const afterPhoto = (f?: File) => f && run("after", async () => {
    setMsg({ text: lang === "hi" ? "फ़ोटो भेज रहे हैं…" : "Uploading the after-photo…" });
    const up = await api.afterUrl(d.groupId, token);
    await api.uploadPhoto(up.uploadUrl, up.fields, await resizeImage(f));
    setMsg({ text: lang === "hi" ? "जाँच हो रही है…" : "Checking the after-photo…" });
    for (let i = 0; i < 30; i++) {
      await sleep(1800);
      const x = await api.drain(d.groupId);
      if (x.status === "cleared") { setD(x); return lang === "hi" ? "AI से साफ़ होने की पुष्टि" : "Verified clear by AI"; }
      if (x.afterNote && x.afterNote !== d.afterNote) { setD(x); return x.afterNote; }
    }
    throw new Error(lang === "hi" ? "जाँच पूरी नहीं हुई। थोड़ी देर में ताज़ा करें।" : "The check did not finish. Refresh in a moment.");
  });

  return (
    <div className="result">
      <button className="link row gap" onClick={onBack}><ArrowLeft size={16} aria-hidden /> {s("list", lang)}</button>
      <div className={`big ${sev.cls}`}>
        <div className="bigline"><span>{sev[lang]}</span><span className="bigglyph">{sev.glyph}</span></div>
        <p className="bigwhy">{d.reasons.join(" · ")}</p>
      </div>
      <FallbackNote d={d} lang={lang} />
      {d.photoUrl && <img className="photo" src={d.photoUrl} alt="Reported drain" />}
      {d.afterUrl && (
        <>
          <p className="small muted">{lang === "hi" ? "बाद की फ़ोटो" : "After"}
            {d.status === "cleared" && <> · <CircleCheck size={13} aria-hidden /> {d.clearedBy === "ai" ? (lang === "hi" ? "AI से सत्यापित" : "AI-verified clear") : (lang === "hi" ? "डिस्पैचर ने पुष्टि की" : "confirmed by a dispatcher (manual)")}</>}
          </p>
          <img className="photo" src={d.afterUrl} alt="After clearance" />
        </>
      )}
      {d.afterNote && d.status !== "cleared" && <p className={`small ${d.awaitingReview ? "" : "muted"}`} role="status">{d.afterNote}</p>}
      {(lang === "hi" ? d.reasoning_hi : d.reasoning) && <p className="reasoning">“{lang === "hi" ? d.reasoning_hi : d.reasoning}”</p>}
      <p className="small">{d.status === "assigned" ? <><HardHat size={14} aria-label="assigned to" /> {d.assignedTo}</> : s(d.status === "cleared" ? "cleared" : "open", lang)} · {rc(d.reportCount, lang)}</p>
      <a className="btn" target="_blank" rel="noreferrer" href={`https://www.google.com/maps?q=${d.lat},${d.lon}`}><MapIcon size={18} aria-hidden /> {lang === "hi" ? "मैप में खोलें" : "Open in Maps"}</a>

      {d.status !== "cleared" && (
        <details className="watch" open={!!token}>
          <summary><HardHat size={16} aria-hidden /> {lang === "hi" ? "डिस्पैचर" : "Dispatcher"}</summary>
          <input className="input" type="password" value={token} placeholder={s("code", lang)} onChange={(e) => setToken(e.target.value)} />
          <div className="row gap" style={{ marginTop: 8 }}>
            <input className="input" value={worker} placeholder={s("worker", lang)} onChange={(e) => setWorker(e.target.value)} />
            <button className="btn" disabled={!worker.trim() || !token || !!busy} onClick={assign}>{busy === "assign" ? "…" : s("assign", lang)}</button>
          </div>
          <label className="btn" style={{ marginTop: 8 }} aria-disabled={!token || !!busy}>
            <Camera size={18} aria-hidden /> {s("after", lang)}
            <input type="file" accept="image/*" capture="environment" hidden disabled={!token || !!busy} onChange={(e) => afterPhoto(e.target.files?.[0])} />
          </label>
          <p className="small muted">{lang === "hi" ? "नाला तभी साफ़ माना जाएगा जब बाद की फ़ोटो में साफ़ दिखे।" : "The drain is only marked cleared when the after-photo shows it clear."}</p>
          {d.awaitingReview && (
            <div className="row gap" style={{ marginTop: 8 }}>
              <button className="btn primary" disabled={!token || !!busy} onClick={() => decide("clear")}><CircleCheck size={16} aria-hidden /> {s("confirmClear", lang)}</button>
              <button className="btn" disabled={!token || !!busy} onClick={() => decide("reject")}>{s("rejectPhoto", lang)}</button>
            </div>
          )}
        </details>
      )}
      {msg && <p className={msg.bad ? "error-box" : "small"} role={msg.bad ? "alert" : "status"}>{msg.text}</p>}
    </div>
  );
}
