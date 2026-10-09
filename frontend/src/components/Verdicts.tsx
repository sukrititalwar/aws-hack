import { VEHICLES, VERDICT_UI, type Lang } from "../i18n";
import type { Vehicle, Verdict } from "../types";

/** Row of every vehicle with its verdict: colour + glyph + word, never colour alone. */
export function VerdictGrid({ verdicts, selected, lang }: { verdicts: Record<Vehicle, Verdict>; selected: Vehicle; lang: Lang }) {
  return (
    <ul className="vgrid" aria-label="Verdict for each vehicle">
      {VEHICLES.map((v) => {
        const ui = VERDICT_UI[verdicts[v.id]];
        return (
          <li key={v.id} className={`vcell ${ui.cls}${v.id === selected ? " sel" : ""}`}>
            <span className="vicon" aria-hidden>{v.icon}</span>
            <span className="vname">{v[lang]}</span>
            <span className="vverdict">
              <span aria-hidden>{ui.glyph}</span> {ui[lang]}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Big verdict for the selected vehicle. */
export function BigVerdict({ verdict, vehicle, why, lang }: { verdict: Verdict; vehicle: Vehicle; why?: string; lang: Lang }) {
  const ui = VERDICT_UI[verdict];
  const v = VEHICLES.find((x) => x.id === vehicle)!;
  const word = { GO: { en: "YES, with care", hi: "हाँ, ध्यान से" }, RISKY: { en: "RISKY", hi: "जोखिम" }, NO_GO: { en: "NO", hi: "नहीं" } }[verdict];
  return (
    <div className={`big ${ui.cls}`} role="status">
      <div className="bigline">
        <span className="bigicon" aria-hidden>{v.icon}</span>
        <span>
          {v[lang]}: <strong>{word[lang]}</strong>
        </span>
        <span className="bigglyph" aria-hidden>{ui.glyph}</span>
      </div>
      {why && <p className="bigwhy">{why}</p>}
    </div>
  );
}
