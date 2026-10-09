import { useEffect, useState } from "react";
import { api } from "../api";
import { ago, t, type Lang } from "../i18n";
import type { LonLat, Mode, Report, Spot, Vehicle } from "../types";
import { deviceId } from "../util";
import ResultCard from "./ResultCard";
import { BigVerdict, VerdictGrid } from "./Verdicts";

const VERIFY = {
  predicted: { en: "🌧 Predicted from rain", hi: "🌧 बारिश से अनुमान" },
  single_report: { en: "📷 AI estimate, 1 report", hi: "📷 AI अनुमान, 1 रिपोर्ट" },
  confirmed: { en: "✔ Confirmed by several reports", hi: "✔ कई रिपोर्ट से पुष्टि" },
  official: { en: "🛡 Official source", hi: "🛡 आधिकारिक स्रोत" },
} as const;

function VerifyBadge({ spot, lang }: { spot: Spot; lang: Lang }) {
  const v = spot.verification ?? (spot.predicted ? "predicted" : "single_report");
  return <span className={`badge ${v}`}>{VERIFY[v][lang]}</span>;
}

interface Props {
  spot: Spot;
  mode: Mode;
  known: Map<string, Report>;
  vehicle: Vehicle;
  lang: Lang;
  setLang: (l: Lang) => void;
  onClose: () => void;
  onRoute: (to: LonLat) => void;
}

export default function SpotSheet({ spot, mode, known, vehicle, lang, setLang, onClose, onRoute }: Props) {
  const latestId = spot.reportIds[spot.reportIds.length - 1];
  const [report, setReport] = useState<Report | null>(known.get(latestId) ?? null);
  const [voteMsg, setVoteMsg] = useState("");

  useEffect(() => {
    setVoteMsg("");
    if (!latestId) return setReport(null); // predicted spot: no report yet
    const k = known.get(latestId);
    if (k) return setReport(k);
    setReport(null);
    api.report(latestId).then(setReport).catch(() => setReport(null));
  }, [latestId, known]);

  async function vote(type: "still_flooded" | "cleared" | "wrong") {
    try {
      await api.vote(latestId, type, deviceId());
      setVoteMsg(t("voted", lang));
    } catch (e) {
      setVoteMsg(e instanceof Error ? e.message : "Vote failed");
    }
  }

  const header = (
    <header className="sheet-head">
      <div>
        <h2>{spot.place ?? (lang === "hi" ? "पानी भराव" : "Flooded spot")}</h2>
        <p className="muted small">
          <VerifyBadge spot={spot} lang={lang} />{" "}
          {spot.predicted ? "" : `${spot.reportCount} ${t("reports", lang)} · ${ago(spot.ageMin * 60, lang)}`}
        </p>
      </div>
      <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}>✕</button>
    </header>
  );

  const votes = (
    <div className="votes">
      <button className="btn" onClick={() => vote("still_flooded")}>🌊 {t("stillFlooded", lang)}</button>
      <button className="btn" onClick={() => vote("cleared")}>☀️ {t("cleared", lang)}</button>
      <button className="btn" onClick={() => vote("wrong")}>🚫 {t("wrong", lang)}</button>
      {voteMsg && <p className="small muted" role="status">{voteMsg}</p>}
    </div>
  );

  const sources = (spot.source_urls ?? []).length > 0 && (
    <p className="small">
      {t("source", lang)}:{" "}
      {spot.source_urls!.map((u, i) => (
        <a key={u} href={u} target="_blank" rel="noreferrer">{i ? ", " : ""}{new URL(u).hostname.replace("www.", "")}</a>
      ))}
    </p>
  );

  if (spot.predicted) {
    return (
      <div className="sheet" role="dialog" aria-label="Predicted flooding">
        {header}
        <div className="banner warn">
          🌧️ {lang === "hi"
            ? `पिछले 3 घंटे में ${Math.round(spot.rainPast3h ?? 0)} मिमी बारिश। यह जगह अक्सर भरती है, अभी तक किसी ने रिपोर्ट नहीं किया।`
            : `${Math.round(spot.rainPast3h ?? 0)} mm of rain in the last 3 h. This spot usually floods; nobody has reported it yet.`}
        </div>
        <p className="small">{lang === "hi" ? "अनुमानित" : "Estimated"}: <strong>{spot.depth_low}–{spot.depth_high} cm</strong> ({lang === "hi" ? "कम भरोसा" : "low confidence, so verdicts are stricter"})</p>
        <BigVerdict verdict={spot.verdicts[vehicle]} vehicle={vehicle} lang={lang} />
        <VerdictGrid verdicts={spot.verdicts} selected={vehicle} lang={lang} />
        {spot.source_url && <p className="small">{lang === "hi" ? "पुराना स्रोत" : "Why this is a known spot"}: <a href={spot.source_url} target="_blank" rel="noreferrer">{new URL(spot.source_url).hostname.replace("www.", "")}</a></p>}
        <div className="actions"><button className="btn primary" onClick={() => onRoute([spot.lon, spot.lat])}>🧭 {t("routeFromHere", lang)}</button></div>
        <p className="disclaimer">⚠️ {lang === "hi" ? "यह बारिश से अनुमान है, फ़ोटो से नहीं। वहाँ हों तो फ़ोटो भेजें।" : "This is a prediction from rainfall, not a photo. If you're there, report it with a photo."}</p>
      </div>
    );
  }

  return (
    <div className="sheet" role="dialog" aria-label="Flooded spot details">
      {header}
      {sources}
      {spot.reportCount > 1 && (
        <p className="small">
          {lang === "hi" ? "सभी रिपोर्ट मिलाकर" : "Combined from all reports"}: <strong>{spot.depth_low}–{spot.depth_high} cm</strong>
        </p>
      )}
      {report?.verdicts ? (
        <ResultCard report={{ ...report, depth_low: spot.depth_low, depth_high: spot.depth_high,
            verdicts: Object.fromEntries(Object.entries(report.verdicts).map(([k, v]) => [k, { ...v, verdict: spot.verdicts[k as Vehicle] }])) as Report["verdicts"] }}
          vehicle={vehicle} lang={lang} setLang={setLang} onRoute={() => onRoute([spot.lon, spot.lat])}
          footer={votes} />
      ) : (
        <>
          <BigVerdict verdict={spot.verdicts[vehicle]} vehicle={vehicle} lang={lang} />
          <VerdictGrid verdicts={spot.verdicts} selected={vehicle} lang={lang} />
          {mode === "live" && votes}
          <p className="disclaimer">⚠️ {t("disclaimer", lang)}</p>
        </>
      )}
    </div>
  );
}
