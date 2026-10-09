import { useEffect } from "react";
import { t, type Lang } from "../i18n";
import { fmtTime } from "../util";

interface Props {
  start: number;
  end: number;
  at: number;
  setAt: (n: number) => void;
  playing: boolean;
  setPlaying: (b: boolean) => void;
  lang: Lang;
  count: number;
}

const STEP_S = 5 * 60; // each tick advances 5 minutes of the archived evening

export default function DemoBar({ start, end, at, setAt, playing, setPlaying, lang, count }: Props) {
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setAt(Math.min(at + STEP_S, end));
      if (at + STEP_S >= end) setPlaying(false);
    }, 450);
    return () => clearInterval(id);
  }, [playing, at, end, setAt, setPlaying]);

  return (
    <div className="demobar" role="group" aria-label={t("demo", lang)}>
      <button className="icon-btn play" onClick={() => { if (at >= end) setAt(start); setPlaying(!playing); }}
        aria-label={playing ? t("pause", lang) : t("play", lang)}>
        {playing ? "⏸" : "▶"}
      </button>
      <div className="demo-main">
        <div className="demo-time">
          <strong>{fmtTime(at)}</strong> <span className="muted small">· {count} {lang === "hi" ? "जगहें" : "spots"}</span>
        </div>
        <input type="range" min={start} max={end} step={60} value={at} aria-label="Replay time"
          onChange={(e) => { setPlaying(false); setAt(Number(e.target.value)); }} />
      </div>
    </div>
  );
}
