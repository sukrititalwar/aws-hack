import { HAZARD_LABEL, t, vehicleInfo, type Lang } from "../i18n";
import type { Report, Vehicle, Verdict } from "../types";
import { speak } from "../util";
import { BigVerdict, VerdictGrid } from "./Verdicts";

interface Props {
  report: Report;
  vehicle: Vehicle;
  lang: Lang;
  setLang: (l: Lang) => void;
  onRoute?: () => void;
  footer?: React.ReactNode;
}

export default function ResultCard({ report: r, vehicle, lang, setLang, onRoute, footer }: Props) {
  if (!r.verdicts) return null;
  const levels = Object.fromEntries(Object.entries(r.verdicts).map(([k, v]) => [k, v.verdict])) as Record<Vehicle, Verdict>;
  const mine = r.verdicts[vehicle];
  const reasoning = lang === "hi" ? r.reasoning_hi || r.reasoning : r.reasoning;
  const why = lang === "hi" ? mine.why_hi : mine.why;
  const hazards = (r.hazards ?? []).filter((h) => HAZARD_LABEL[h]);

  const shareText =
    `🌊 ${r.place ?? "Flooded road"}: about ${r.depth_low}-${r.depth_high} cm of water. ` +
    `${vehicleInfo(vehicle).en}: ${mine.label_en.split(": ")[1]}. ` +
    `https://www.google.com/maps?q=${r.lat},${r.lon} (via Can My Scooter Cross?)`;

  return (
    <div className="result">
      {r.danger && <div className="danger-banner" role="alert">⚡ {t("danger", lang)}</div>}
      {r.source_label === "synthetic" && <div className="chip warn">{t("synthetic", lang)}</div>}

      <div className="depthrow">
        <div>
          <div className="muted small">{t("depth", lang)}</div>
          <div className="depth">
            {r.depth_low}–{r.depth_high} <small>cm</small>
          </div>
        </div>
        <div className={`conf conf-${r.confidence}`}>
          {t(`conf_${r.confidence ?? "low"}` as "conf_low", lang)} {t("confidence", lang)}
        </div>
      </div>

      {r.photoUrl && <img className="photo" src={r.photoUrl} alt="Reported flooded road" loading="lazy" />}

      <BigVerdict verdict={mine.verdict} vehicle={vehicle} why={why} lang={lang} />

      {reasoning && (
        <p className="reasoning">
          “{reasoning}”
          <button className="link" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
            {lang === "en" ? "हिंदी" : "English"}
          </button>
        </p>
      )}

      {hazards.length > 0 && (
        <div className="hazards">
          <strong>{t("hazard", lang)}:</strong> {hazards.map((h) => HAZARD_LABEL[h][lang]).join(", ")}
          {r.flowing_water && <> · {lang === "hi" ? "बहता पानी" : "Flowing water"}</>}
        </div>
      )}

      <VerdictGrid verdicts={levels} selected={vehicle} lang={lang} />

      {!!r.reference_objects?.length && (
        <details className="refs">
          <summary>{t("usedRefs", lang)}</summary>
          <ul>
            {r.reference_objects.map((o, i) => (
              <li key={i}>
                <strong>{o.object}</strong>: {o.observation} (~{o.implied_depth_cm} cm)
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="actions">
        <button className="btn" onClick={() => speak(`${reasoning ?? ""} ${why}`, lang)}>🔊 {t("speak", lang)}</button>
        <a className="btn" href={`https://wa.me/?text=${encodeURIComponent(shareText)}`} target="_blank" rel="noreferrer">
          💬 {t("share", lang)}
        </a>
        {onRoute && <button className="btn primary" onClick={onRoute}>🧭 {t("routeFromHere", lang)}</button>}
      </div>
      {r.source_url && (
        <p className="small muted">
          {t("source", lang)}: <a href={r.source_url} target="_blank" rel="noreferrer">{r.source_label || r.source_url}</a>
        </p>
      )}
      {footer}
      <p className="disclaimer">⚠️ {t("disclaimer", lang)}</p>
    </div>
  );
}
