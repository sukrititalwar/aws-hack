import { Camera, MessageCircle, TriangleAlert, X } from "lucide-react";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { api, mapStyle, WHATSAPP_JOIN, WHATSAPP_NUMBER } from "../api";
import { t, type Lang } from "../i18n";
import type { LonLat, Report, Vehicle } from "../types";
import { deviceId, frameFromVideo, getPosition, photoTime, resizeImage, sleep } from "../util";
import ResultCard from "./ResultCard";

const PROGRESS = {
  en: ["Uploading photo…", "Checking the photo is safe…", "Finding kerbs, tyres, people…", "Measuring the water against them…", "Working out a verdict for each vehicle…"],
  hi: ["फ़ोटो भेज रहे हैं…", "फ़ोटो की जाँच…", "फ़ुटपाथ, टायर, लोग खोज रहे हैं…", "पानी की ऊँचाई माप रहे हैं…", "हर गाड़ी के लिए फ़ैसला…"],
};

interface Props {
  fallbackCenter: LonLat;
  vehicle: Vehicle;
  lang: Lang;
  setLang: (l: Lang) => void;
  onClose: () => void;
  onDone: (r: Report) => void;
  onRoute: (to: LonLat) => void;
}

export default function ReportFlow(p: Props) {
  const [step, setStep] = useState<"pick" | "confirm" | "analysing" | "result" | "error">("pick");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [pos, setPos] = useState<LonLat>(p.fallbackCenter);
  const [place, setPlace] = useState("");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const miniEl = useRef<HTMLDivElement>(null);

  // GPS as soon as the flow opens, so it is ready by the time the photo is picked.
  useEffect(() => {
    getPosition().then(setPos).catch(() => undefined);
  }, []);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  // Mini map with a draggable pin to confirm location.
  useEffect(() => {
    if (step !== "confirm" || !miniEl.current) return;
    const m = new maplibregl.Map({ container: miniEl.current, style: mapStyle(false), center: pos, zoom: 16, attributionControl: false });
    const mk = new maplibregl.Marker({ draggable: true, color: "#d92d20" }).setLngLat(pos).addTo(m);
    mk.on("dragend", () => {
      const l = mk.getLngLat();
      setPos([l.lng, l.lat]);
    });
    m.on("click", (e) => {
      mk.setLngLat(e.lngLat);
      setPos([e.lngLat.lng, e.lngLat.lat]);
    });
    return () => m.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  async function onFile(f: File | undefined) {
    if (!f) return;
    try {
      // A phone video is reduced to one still frame and goes through the same photo pipeline.
      if (f.type.startsWith("video/")) f = await frameFromVideo(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return setStep("error");
    }
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setStep("confirm");
  }

  async function submit() {
    if (!file) return;
    setStep("analysing");
    setProgress(0);
    const ticker = setInterval(() => setProgress((x) => Math.min(x + 1, PROGRESS.en.length - 1)), 2200);
    try {
      const [blob, exifTime] = await Promise.all([resizeImage(file), photoTime(file)]);
      const up = await api.uploadUrl({ lat: pos[1], lon: pos[0], place: place.trim() || undefined, deviceId: deviceId(), exifTime });
      await api.uploadPhoto(up.uploadUrl, up.fields, blob);
      // Poll until the analyze Lambda has finished (usually 5-12 s).
      for (let i = 0; i < 45; i++) {
        await sleep(i < 4 ? 2000 : 1500);
        const r = await api.report(up.reportId).catch(() => null);
        if (r && r.status !== "analysing") {
          clearInterval(ticker);
          if (r.status === "live") {
            setReport(r);
            setStep("result");
            p.onDone(r);
          } else {
            setError(r.rejection_reason || "The photo could not be analysed.");
            setStep("error");
          }
          return;
        }
      }
      throw new Error("Analysis is taking too long. Please try again.");
    } catch (e) {
      clearInterval(ticker);
      setError(e instanceof Error ? e.message : String(e));
      setStep("error");
    }
  }

  const L = p.lang;
  return (
    <div className="sheet full" role="dialog" aria-label={t("report", L)}>
      <header className="sheet-head">
        <h2 className="row gap"><Camera size={22} aria-hidden /> {t("report", L)}</h2>
        <button className="icon-btn" onClick={p.onClose} aria-label={t("close", L)}><X size={20} /></button>
      </header>

      {step === "pick" && (
        <div className="pick">
          <label className="camera">
            <input type="file" accept="image/*,video/*" capture="environment" onChange={(e) => onFile(e.target.files?.[0])} />
            <span className="camera-icon" aria-hidden><Camera size={44} strokeWidth={1.5} /></span>
            <span>{t("photoOrVideo", L)}</span>
          </label>
          <p className="muted">{t("photoTip", L)}</p>
          {WHATSAPP_NUMBER && (
            <a className="btn wa big-btn" target="_blank" rel="noreferrer"
              href={`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(WHATSAPP_JOIN || "hi")}`}>
              <MessageCircle size={18} aria-hidden /> {L === "hi" ? "WhatsApp से रिपोर्ट करें (ऐप की ज़रूरत नहीं)" : "Report on WhatsApp instead (no app needed)"}
            </a>
          )}
        </div>
      )}

      {step === "confirm" && (
        <div className="confirm">
          <img className="thumb" src={preview} alt="" />
          <label className="field-label">{t("location", L)} · <span className="muted">{t("dragPin", L)}</span></label>
          <div ref={miniEl} className="minimap" />
          <label className="field-label" htmlFor="place">{t("placeName", L)}</label>
          <input id="place" className="input" value={place} maxLength={120} placeholder={t("placeHint", L)} onChange={(e) => setPlace(e.target.value)} />
          <div className="actions">
            <button className="btn" onClick={() => setStep("pick")}>{t("cancel", L)}</button>
            <button className="btn primary big-btn" onClick={submit}>{t("send", L)}</button>
          </div>
        </div>
      )}

      {step === "analysing" && (
        <div className="analysing" aria-live="polite">
          <img className="thumb scan" src={preview} alt="" />
          <div className="spinner" aria-hidden />
          <p className="progress">{PROGRESS[L][progress]}</p>
        </div>
      )}

      {step === "result" && report && (
        <ResultCard report={report} vehicle={p.vehicle} lang={L} setLang={p.setLang} onRoute={() => p.onRoute([report.lon, report.lat])} />
      )}

      {step === "error" && (
        <div className="error-box" role="alert">
          <p className="row gap"><TriangleAlert size={18} aria-hidden /> {error}</p>
          <button className="btn primary" onClick={() => setStep("pick")}>{L === "hi" ? "फिर से कोशिश करें" : "Try another photo"}</button>
        </div>
      )}
    </div>
  );
}
