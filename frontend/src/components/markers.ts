/** DOM pins shared by both map engines (MapLibre and Google Maps), so they look identical. */
import { VERDICT_UI, vehicleInfo, type Lang } from "../i18n";
import type { Hotspot, RainCity, Spot, Vehicle } from "../types";

// Lucide paths (check, x, cloud-rain, shield, message-circle) as strings, because markers are plain DOM.
const svg = (body: string, size = 16) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const PIN_GLYPH: Record<string, string> = {
  go: svg('<path d="M20 6 9 17l-5-5"/>'),
  nogo: svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
  risky: "!",
  inspect: "?",
};
const BADGE = {
  rain: svg('<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6"/><path d="M8 14v6"/><path d="M12 16v6"/>', 11),
  official: svg('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>', 11),
  sim: '',
  social: svg('<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>', 11),
};

/** Google Maps-style live user location pulsing puck marker. */
export function userLocationElement(heading?: number | null): HTMLDivElement {
  const d = document.createElement("div");
  d.className = "me-puck";
  d.innerHTML = `
    <div class="me-puck-pulse"></div>
    ${heading != null && !isNaN(heading) ? `<div class="me-puck-heading" style="transform: rotate(${heading}deg)"></div>` : ""}
    <div class="me-puck-dot"></div>
  `;
  return d;
}

/** Colour + glyph + label pin for one flooded spot, recoloured for the selected vehicle. */
export function spotElement(s: Spot, vehicle: Vehicle, onClick: (s: Spot) => void): HTMLButtonElement {
  const v = s.verdicts[vehicle];
  // A GO we are not sure about is drawn as "?" (requires inspection), never as a green tick.
  const unsure = v === "GO" && !!s.needs_inspection;
  const ui = unsure ? { cls: "risky", glyph: "?", en: "Requires inspection", hi: "" } : VERDICT_UI[v];
  const size = Math.min(30 + (s.reportCount - 1) * 6, 54);
  const btn = document.createElement("button");
  btn.className = `pin ${ui.cls}${s.faded ? " faded" : ""}${s.danger ? " danger" : ""}${s.predicted ? " predicted" : ""}${s.simulated ? " sim" : ""}`;
  btn.style.width = btn.style.height = `${size}px`;
  const badge = s.simulated ? BADGE.sim : s.predicted ? BADGE.rain : s.sources.includes("official") ? BADGE.official : s.sources.includes("social") ? BADGE.social : "";
  btn.innerHTML = `<span>${unsure ? PIN_GLYPH.inspect : PIN_GLYPH[ui.cls]}</span>${s.reportCount > 1 ? `<b>${s.reportCount}</b>` : ""}${badge ? `<i>${badge}</i>` : ""}`;
  const veh = vehicleInfo(vehicle);
  btn.setAttribute("aria-label", `${s.place ?? "Flooded spot"}: ${s.predicted ? "predicted from rain, " : ""}about ${s.depth_high} cm. ${veh.en}: ${ui.en}.`);
  btn.onclick = (e) => {
    e.stopPropagation();
    onClick(s);
  };
  return btn;
}

/** Hollow ring for a chronic flood hotspot. */
export function hotspotElement(h: Hotspot, lang: Lang, onClick: (h: Hotspot) => void): HTMLButtonElement {
  const d = document.createElement("button");
  d.className = `ring${h.risk === "likely_flooded_soon" ? " soon" : h.risk === "flooding_likely_now" ? " now" : ""}`;
  d.setAttribute("aria-label", `${h.name}: usually floods in heavy rain${h.risk !== "normal" ? " (rain warning)" : ""}`);
  d.title = lang === "hi" ? h.name_hi ?? h.name : h.name;
  d.onclick = (e) => {
    e.stopPropagation();
    onClick(h);
  };
  return d;
}

/** The A / B route end markers. */
export function endpointElement(kind: "from" | "to"): HTMLDivElement {
  const d = document.createElement("div");
  d.className = `endpoint ${kind}`;
  d.textContent = kind === "from" ? "A" : "B";
  return d;
}

const RAIN_SIZE: Record<RainCity["level"], number> = { dry: 12, light: 26, moderate: 34, heavy: 44, extreme: 52 };

/** One city on the "where is it raining" map: size + colour + the mm/h number (never colour alone). */
export function rainElement(c: RainCity, onClick: (c: RainCity) => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.className = `raindot ${c.level}${c.supported ? " live" : ""}`;
  b.style.width = b.style.height = `${RAIN_SIZE[c.level]}px`;
  b.innerHTML = c.level === "dry" ? "" : `<span>${c.now >= 10 ? Math.round(c.now) : c.now.toFixed(1)}</span>`;
  b.title = `${c.name}: ${c.now.toFixed(1)} mm/h now, ${c.past3h.toFixed(1)} mm in the last 3 h`;
  b.setAttribute("aria-label", `${c.name}: ${c.level === "dry" ? "no rain" : `${c.level} rain, ${c.now.toFixed(1)} millimetres per hour`}`);
  b.onclick = (e) => {
    e.stopPropagation();
    onClick(c);
  };
  return b;
}
