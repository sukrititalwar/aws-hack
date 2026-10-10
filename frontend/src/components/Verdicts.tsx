import { categoryUI, VEHICLES, type Lang } from "../i18n";
import type { Vehicle, Verdict } from "../types";

/** Row of every vehicle with its category: colour + glyph + word, never colour alone.
 *  `inspect`: the estimate is unreliable, so a GO is shown as "?" (requires inspection). */
export function VerdictGrid({ verdicts, selected, lang, inspect = false }: { verdicts: Record<Vehicle, Verdict>; selected: Vehicle; lang: Lang; inspect?: boolean }) {
  return (
    <ul className="vgrid" aria-label="Verdict for each vehicle">
      {VEHICLES.map((v) => {
        const ui = categoryUI(verdicts[v.id], inspect);
        const short = ui.glyph === "?" ? (lang === "hi" ? "जाँचें" : "Check") : ui.glyph === "✓" ? (lang === "hi" ? "ठीक" : "OK") : ui.glyph === "!" ? (lang === "hi" ? "जोखिम" : "Risky") : (lang === "hi" ? "नहीं" : "No");
        return (
          <li key={v.id} className={`vcell ${ui.cls}${v.id === selected ? " sel" : ""}`}>
            <span className="vicon" aria-hidden>{v.icon}</span>
            <span className="vname">{v[lang]}</span>
            <span className="vverdict">
              <span aria-hidden>{ui.glyph}</span> {short}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Big category for the selected vehicle. */
export function BigVerdict({ verdict, vehicle, why, lang, inspect = false }: { verdict: Verdict; vehicle: Vehicle; why?: string; lang: Lang; inspect?: boolean }) {
  const ui = categoryUI(verdict, inspect);
  const v = VEHICLES.find((x) => x.id === vehicle)!;
  return (
    <div className={`big ${ui.cls}`} role="status">
      <div className="bigline">
        <span className="bigicon" aria-hidden>{v.icon}</span>
        <span>
          {v[lang]}: <strong>{ui[lang]}</strong>
        </span>
        <span className="bigglyph" aria-hidden>{ui.glyph}</span>
      </div>
      {why && <p className="bigwhy">{why}</p>}
    </div>
  );
}
