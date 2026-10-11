import { FlaskConical, X } from "lucide-react";
import { ago, t, type Lang } from "../i18n";
import type { SimPayload, Vehicle } from "../types";
import { VEHICLES } from "../i18n";

const S = {
  title: { en: "Delhi storm simulation", hi: "दिल्ली का तूफ़ान सिम्युलेशन" },
  rain: { en: "Rain", hi: "बारिश" },
  now: { en: "now", hi: "अभी" },
  next3: { en: "next 3 h", hi: "अगले 3 घं" },
  verdicts: { en: "Spots for your vehicle", hi: "आपकी सवारी के लिए जगहें" },
  go: { en: "Passable", hi: "पार कर सकते हैं" },
  risky: { en: "Potentially unsafe", hi: "जोखिम भरा" },
  nogo: { en: "Unsafe", hi: "असुरक्षित" },
  posts: { en: "Community posts", hi: "सामुदायिक पोस्ट" },
  noPosts: { en: "No posts yet at this time of the storm.", hi: "तूफ़ान के इस समय तक कोई पोस्ट नहीं।" },
  drains: { en: "Blocked drains", hi: "जाम नालियाँ" },
  open: { en: "open", hi: "खुला" },
  assigned: { en: "assigned", hi: "सौंपा गया" },
} as const;
const s = (k: keyof typeof S, l: Lang) => S[k][l];

interface Props {
  lang: Lang;
  data: SimPayload | null;
  vehicle: Vehicle;
  at: number;
  onClose: () => void;
}

/** The DEMO storm summary. DEMO tags mark every item. */
export default function SimPanel({ lang, data, vehicle, at, onClose }: Props) {
  const counts = { GO: 0, RISKY: 0, NO_GO: 0 };
  data?.spots.forEach((sp) => { counts[sp.verdicts[vehicle]] += 1; });
  const veh = VEHICLES.find((v) => v.id === vehicle)?.[lang] ?? vehicle;
  return (
    <div className="sheet" role="dialog" aria-label={s("title", lang)}>
      <header className="sheet-head">
        <div>
          <p className="eyebrow"><FlaskConical size={13} aria-hidden /> {lang === "hi" ? "सिम्युलेशन" : "SIMULATION"}</p>
          <h2>{s("title", lang)}</h2>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label={t("close", lang)}><X size={20} /></button>
      </header>
      {data && (
        <>
          <p className="muted small">{data.scenario.area}</p>
          <div className="rainstats">
            <div><b>{data.weather.rainNow.toFixed(1)}</b><span>mm/h {s("now", lang)}</span></div>
            <div><b>{data.weather.rainNext3h.toFixed(0)}</b><span>mm {s("next3", lang)}</span></div>
            <div><b>{data.spots.length}</b><span>{lang === "hi" ? "जगहें" : "spots"}</span></div>
          </div>
          <h3 className="sec-title">{s("verdicts", lang)} · {veh}</h3>
          <div className="rainstats">
            <div><b>{counts.GO}</b><span>{s("go", lang)}</span></div>
            <div><b>{counts.RISKY}</b><span>{s("risky", lang)}</span></div>
            <div><b>{counts.NO_GO}</b><span>{s("nogo", lang)}</span></div>
          </div>
          <h3 className="sec-title">{s("posts", lang)}</h3>
          {data.posts.length === 0 && <p className="muted small">{s("noPosts", lang)}</p>}
          <ul className="buslist">
            {data.posts.slice(0, 6).map((p) => (
              <li key={p.id}>
                <span className="small muted">{p.author} · {ago(at - p.ts, lang)}</span>
                <p>{p.text}</p>
              </li>
            ))}
          </ul>
          {data.drains.length > 0 && (
            <>
              <h3 className="sec-title">{s("drains", lang)}</h3>
              <ul className="buslist">
                {data.drains.map((d) => (
                  <li key={d.groupId} className="simdrain">
                    <span>{d.note ?? d.groupId}</span>
                    <span className="small muted">{d.severity} · {d.reportCount} · {d.assignedTo ? `${s("assigned", lang)}: ${d.assignedTo}` : s("open", lang)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
