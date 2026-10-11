import { categoryUI, t, VEHICLES, type Lang } from "../i18n";
import { VehicleIcon, VerdictIcon } from "../icons";
import type { Vehicle, Verdict } from "../types";

/** Row of every vehicle with its category: colour + icon + word, never colour alone.
 *  `inspect`: the estimate is unreliable, so a GO is shown as "?" (requires inspection). */
export function VerdictGrid({ verdicts, selected, lang, inspect = false }: { verdicts: Record<Vehicle, Verdict>; selected: Vehicle; lang: Lang; inspect?: boolean }) {
  return (
    <ul className="vgrid" aria-label="Verdict for each vehicle">
      {VEHICLES.map((v) => {
        const ui = categoryUI(verdicts[v.id], inspect, v.id);
        const short = v.id === "ev_scooter" && verdicts[v.id] === "GO" && !inspect
          ? t("evCaution", lang)
          : ui.glyph === "?" ? (lang === "hi" ? "जाँचें" : "Check") : ui.glyph === "✓" ? (lang === "hi" ? "ठीक" : "OK") : ui.glyph === "!" ? (lang === "hi" ? "जोखिम" : "Risky") : (lang === "hi" ? "नहीं" : "No");
        return (
          <li key={v.id} className={`vcell ${ui.cls}${v.id === selected ? " sel" : ""}`}>
            <VehicleIcon v={v.id} size={20} className="vicon" />
            <span className="vname">{v[lang]}</span>
            <span className="vverdict">
              <VerdictIcon cls={ui.cls} glyph={ui.glyph} size={13} /> {short}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Big category for the selected vehicle. */
export function BigVerdict({ verdict, vehicle, why, lang, inspect = false }: { verdict: Verdict; vehicle: Vehicle; why?: string; lang: Lang; inspect?: boolean }) {
  const ui = categoryUI(verdict, inspect, vehicle);
  const v = VEHICLES.find((x) => x.id === vehicle)!;
  return (
    <div className={`big ${ui.cls}`} role="status">
      <div className="bigline">
        <span className="bigicon"><VehicleIcon v={vehicle} size={24} /></span>
        <span>
          {v[lang]}: <strong>{ui[lang]}</strong>
        </span>
        <span className="bigglyph"><VerdictIcon cls={ui.cls} glyph={ui.glyph} size={24} /></span>
      </div>
      {why && <p className="bigwhy">{why}</p>}
    </div>
  );
}
