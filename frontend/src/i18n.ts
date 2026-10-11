import type { Vehicle, Verdict } from "./types";

export type Lang = "en" | "hi";
export const EV_SCOOTER_WARNING_CM = 12;

export const VEHICLES: { id: Vehicle; en: string; hi: string }[] = [
  { id: "pedestrian", en: "Walking", hi: "पैदल" },
  { id: "bicycle", en: "Bicycle", hi: "साइकिल" },
  { id: "scooter", en: "Scooter", hi: "स्कूटर" },
  { id: "ev_scooter", en: "EV Scooter", hi: "ई-स्कूटर" },
  { id: "auto", en: "Auto", hi: "ऑटो" },
  { id: "car", en: "Car", hi: "कार" },
  { id: "suv", en: "SUV", hi: "एसयूवी" },
  { id: "bus", en: "Bus", hi: "बस" },
  { id: "ambulance", en: "Ambulance", hi: "एम्बुलेंस" },
];
export const vehicleInfo = (v: Vehicle) => VEHICLES.find((x) => x.id === v)!;

export const VERDICT_UI: Record<Verdict, { glyph: string; en: string; hi: string; cls: string }> = {
  GO: { glyph: "✓", en: "OK", hi: "ठीक", cls: "go" },
  RISKY: { glyph: "!", en: "Risky", hi: "जोखिम", cls: "risky" },
  NO_GO: { glyph: "✕", en: "No", hi: "नहीं", cls: "nogo" },
};

const STR = {
  imOn: { en: "I'm on", hi: "मेरी सवारी" },
  report: { en: "Report flooding", hi: "पानी भराव बताएँ" },
  safeRoute: { en: "Safe route", hi: "सुरक्षित रास्ता" },
  demo: { en: "Demo", hi: "डेमो" },
  live: { en: "Live", hi: "लाइव" },
  disclaimer: {
    en: "Estimate from a photo. Depth can be wrong. If unsure, don't cross. Emergency: call 112.",
    hi: "यह फ़ोटो से अनुमान है, गलत हो सकता है। शक हो तो पार न करें। आपात स्थिति में 112 पर कॉल करें।",
  },
  takePhoto: { en: "Take or choose a photo of the water", hi: "पानी की फ़ोटो लें या चुनें" },
  photoTip: {
    en: "Include something for scale: a kerb, a tyre, a person's legs.",
    hi: "फ़ोटो में फ़ुटपाथ, टायर या किसी के पैर दिखें तो बेहतर।",
  },
  location: { en: "Location", hi: "जगह" },
  dragPin: { en: "Drag the pin to the flooded spot", hi: "पिन को पानी वाली जगह पर रखें" },
  placeName: { en: "Place name (optional)", hi: "जगह का नाम (वैकल्पिक)" },
  placeHint: { en: "e.g. Andheri subway", hi: "जैसे अंधेरी सबवे" },
  send: { en: "Check depth", hi: "गहराई जाँचें" },
  cancel: { en: "Cancel", hi: "रद्द करें" },
  close: { en: "Close", hi: "बंद करें" },
  analysing: { en: "Analysing photo", hi: "फ़ोटो जाँच रहे हैं" },
  depth: { en: "Water depth", hi: "पानी की गहराई" },
  confidence: { en: "confidence", hi: "भरोसा" },
  conf_low: { en: "Low", hi: "कम" },
  conf_medium: { en: "Medium", hi: "मध्यम" },
  conf_high: { en: "High", hi: "ज़्यादा" },
  usedRefs: { en: "What the AI looked at", hi: "AI ने क्या देखा" },
  danger: { en: "DANGER: electric wire or pole in the water. Stay away.", hi: "ख़तरा: पानी में बिजली का तार/खंभा। दूर रहें।" },
  hazard: { en: "Hazards", hi: "ख़तरे" },
  share: { en: "Share on WhatsApp", hi: "WhatsApp पर भेजें" },
  speak: { en: "Read aloud", hi: "सुनें" },
  routeFromHere: { en: "Find a safe route", hi: "सुरक्षित रास्ता खोजें" },
  stillFlooded: { en: "Still flooded", hi: "अभी भी पानी है" },
  cleared: { en: "Cleared", hi: "पानी उतर गया" },
  wrong: { en: "Wrong", hi: "गलत" },
  voted: { en: "Thanks, vote recorded", hi: "धन्यवाद, वोट दर्ज हुआ" },
  reports: { en: "reports", hi: "रिपोर्ट" },
  ago: { en: "ago", hi: "पहले" },
  from: { en: "From", hi: "कहाँ से" },
  to: { en: "To", hi: "कहाँ तक" },
  myLocation: { en: "My location", hi: "मेरी जगह" },
  tapMap: { en: "Tap the map", hi: "मैप पर टैप करें" },
  search: { en: "Search a place", hi: "जगह खोजें" },
  findRoute: { en: "Find route", hi: "रास्ता खोजें" },
  normalRoute: { en: "Usual route", hi: "सामान्य रास्ता" },
  safeRouteFor: { en: "Safe route for", hi: "सुरक्षित रास्ता:" },
  watchRoute: { en: "Alert me if this route floods", hi: "रास्ते पर पानी भरे तो बताएँ" },
  contact: { en: "Email or phone (+91…)", hi: "ईमेल या फ़ोन (+91…)" },
  subscribe: { en: "Save", hi: "सेव करें" },
  hotspot: { en: "Usually floods in heavy rain", hi: "भारी बारिश में अक्सर पानी भरता है" },
  rainSoon: { en: "Heavy rain expected: likely to flood soon", hi: "भारी बारिश संभव: जल्द पानी भर सकता है" },
  offline: { en: "Offline. Showing last saved reports.", hi: "ऑफ़लाइन। पिछली रिपोर्ट दिखा रहे हैं।" },
  noApi: { en: "Backend not configured", hi: "बैकएंड सेट नहीं है" },
  play: { en: "Play", hi: "चलाएँ" },
  pause: { en: "Pause", hi: "रोकें" },
  legend: { en: "for your vehicle", hi: "आपकी सवारी के लिए" },
  synthetic: { en: "Synthetic test point", hi: "परीक्षण बिंदु" },
  source: { en: "Source", hi: "स्रोत" },
  inspect: { en: "Requires inspection", hi: "जाँच ज़रूरी" },
  inspectWhy: {
    en: "A photo can't measure depth reliably (angle, reflections, unknown road shape). Treat this as unsafe until someone checks it.",
    hi: "फ़ोटो से गहराई सही नहीं मापी जा सकती (कोण, परछाईं, सड़क का आकार)। जाँच होने तक असुरक्षित मानें।",
  },
  roughDepth: { en: "Rough depth", hi: "मोटा अंदाज़ा" },
  drains: { en: "Blocked drains", hi: "बंद नाले" },
  photoOrVideo: { en: "Take a photo or short video", hi: "फ़ोटो या छोटा वीडियो लें" },
  evDepthWarning: {
    en: "The upper end of this rough depth estimate is at or above this app's EV Scooter caution threshold. This is a precaution, not a prediction of damage or a safety guarantee. Avoid crossing if unsure.",
    hi: "गहराई के इस मोटे अनुमान की ऊपरी सीमा इस ऐप की ई-स्कूटर सावधानी सीमा तक या उससे ऊपर है। यह एहतियात है, नुकसान का अनुमान या सुरक्षा की गारंटी नहीं। शक हो तो पार न करें।",
  },
  evBelowThreshold: {
    en: "Below app caution threshold; safety is not established",
    hi: "ऐप की सावधानी सीमा से कम; सुरक्षा निश्चित नहीं",
  },
  evCaution: { en: "Caution", hi: "सावधानी" },
} as const;

/** Verdict + "are we sure?" -> the user-facing category. A GO we are unsure about is never "passable". */
export function categoryUI(verdict: Verdict, inspect: boolean, vehicle?: Vehicle): { cls: string; glyph: string; en: string; hi: string } {
  if (verdict === "GO" && inspect) return { cls: "risky", glyph: "?", en: "Requires inspection", hi: "जाँच ज़रूरी" };
  if (verdict === "GO" && vehicle === "ev_scooter") {
    return { cls: "risky", glyph: "!", en: STR.evBelowThreshold.en, hi: STR.evBelowThreshold.hi };
  }
  if (verdict === "GO") return { cls: "go", glyph: "✓", en: "Passable", hi: "पार कर सकते हैं" };
  if (verdict === "RISKY") return { cls: "risky", glyph: "!", en: "Potentially unsafe", hi: "जोखिम भरा" };
  return { cls: "nogo", glyph: "✕", en: "Unsafe", hi: "असुरक्षित" };
}

/** Never show false precision: round the range outwards to 5 cm. */
export function depthBand(lo?: number, hi?: number): string {
  if (lo == null || hi == null) return "";
  const a = Math.floor(lo / 5) * 5, b = Math.ceil(hi / 5) * 5;
  return a === b ? `~${a}` : `${a}–${b}`;
}

export type Key = keyof typeof STR;
export const t = (k: Key, lang: Lang) => STR[k][lang];

export const PREDICTIVE_UI = {
  button: { en: "Next-hour outlook", hi: "अगले घंटे का अनुमान" },
  loading: { en: "Estimating route risk…", hi: "रास्ते का जोखिम आँका जा रहा है…" },
  title: { en: "Predictive mobility outlook", hi: "आवागमन का अनुमान" },
  disclaimer: {
    en: "A prototype index from hourly weather forecasts and current reports. It is not a probability, water-depth estimate, or safety guarantee.",
    hi: "यह घंटेवार मौसम पूर्वानुमान और मौजूदा रिपोर्ट पर आधारित शुरुआती सूचकांक है। यह संभावना, पानी की गहराई का अनुमान या सुरक्षा की गारंटी नहीं है।",
  },
  unknown: { en: "Not enough current data", hi: "मौजूदा डेटा पर्याप्त नहीं" },
  lower: { en: "Lower relative concern", hi: "तुलनात्मक रूप से कम चिंता" },
  watch: { en: "Watch conditions", hi: "सावधानी रखें" },
  elevated: { en: "Elevated concern", hi: "ज़्यादा चिंता" },
  score: { en: "Prototype index", hi: "शुरुआती सूचकांक" },
  weatherMissing: {
    en: "Weather forecast unavailable; results may use reports only.",
    hi: "मौसम पूर्वानुमान उपलब्ध नहीं; परिणाम केवल रिपोर्ट पर आधारित हो सकते हैं।",
  },
  reportsMissing: {
    en: "Community reports or hotspot data are unavailable; comparisons are incomplete.",
    hi: "सामुदायिक रिपोर्ट या जलभराव स्थल का डेटा उपलब्ध नहीं; तुलना अधूरी है।",
  },
  vehicles: { en: "Vehicle options", hi: "गाड़ी के विकल्प" },
  departures: { en: "Departure alternatives", hi: "रवाना होने के विकल्प" },
  now: { en: "Now", hi: "अभी" },
  after: { en: "min later", hi: "मिनट बाद" },
  recommended: { en: "Lower prototype index", hi: "कम शुरुआती सूचकांक" },
  noRoute: { en: "No route available under current vehicle constraints.", hi: "मौजूदा वाहन सीमाओं में रास्ता उपलब्ध नहीं।" },
  noComparable: {
    en: "No comparable full-coverage recommendation is available; review the coverage and route notes.",
    hi: "पूरे कवरेज के साथ तुलना योग्य सुझाव उपलब्ध नहीं; कवरेज और रास्ते की जानकारी देखें।",
  },
  reports: { en: "active reports", hi: "मौजूदा रिपोर्ट" },
  coverage: { en: "forecast coverage", hi: "पूर्वानुमान कवरेज" },
  noInputs: { en: "No route-level risk inputs are available.", hi: "रास्ते के जोखिम का डेटा उपलब्ध नहीं है।" },
} as const;

const PREDICTIVE_REASONS = {
  rain_expected: { en: "Rain is forecast along part of this route.", hi: "इस रास्ते के कुछ हिस्सों में बारिश का पूर्वानुमान है।" },
  active_report_near_route: { en: "A current waterlogging report is near this route.", hi: "इस रास्ते के पास पानी भराव की मौजूदा रिपोर्ट है।" },
  official_closure: { en: "An active official closure is near this route.", hi: "इस रास्ते के पास आधिकारिक बंदी की मौजूदा सूचना है।" },
  chronic_hotspot_risk: { en: "A known flood hotspot has an active rain-risk status nearby.", hi: "पास के ज्ञात जलभराव स्थल पर बारिश से जुड़ा जोखिम दर्ज है।" },
  stale_observations: { en: "Some nearby observations are older and weighted less.", hi: "पास की कुछ पुरानी रिपोर्टों का महत्व कम किया गया है।" },
  conflicting_reports: { en: "Nearby reports disagree about vehicle risk.", hi: "पास की रिपोर्टों में वाहन जोखिम को लेकर मतभेद है।" },
  no_recent_reports: { en: "No active community report was found; that does not mean the road is dry.", hi: "कोई सक्रिय सामुदायिक रिपोर्ट नहीं मिली; इसका मतलब सड़क सूखी होना नहीं है।" },
  weather_unavailable: { en: "Weather forecast data could not be loaded.", hi: "मौसम पूर्वानुमान डेटा नहीं मिल सका।" },
  reports_unavailable: { en: "Community report data could not be loaded.", hi: "सामुदायिक रिपोर्ट डेटा नहीं मिल सका।" },
  hotspots_unavailable: { en: "Flood hotspot data could not be loaded.", hi: "जलभराव स्थल का डेटा नहीं मिल सका।" },
  weather_partial: { en: "Weather forecast coverage is incomplete for this route.", hi: "इस रास्ते के लिए मौसम पूर्वानुमान अधूरा है।" },
  route_horizon_partial: { en: "Only route segments arriving within the first hour are scored.", hi: "केवल पहले घंटे में पहुँचने वाले रास्ते के हिस्सों का आकलन है।" },
  route_blocked: { en: "Current vehicle-specific constraints block a route.", hi: "मौजूदा वाहन-विशिष्ट सीमाएँ रास्ता रोकती हैं।" },
  no_feasible_route: { en: "No feasible route was found for this vehicle.", hi: "इस वाहन के लिए कोई चलने योग्य रास्ता नहीं मिला।" },
  no_route_risk_inputs: { en: "There is not enough data to score this route.", hi: "इस रास्ते का जोखिम आँकने के लिए पर्याप्त डेटा नहीं है।" },
} as const;

export function predictiveReason(code: string, lang: Lang): string {
  return code in PREDICTIVE_REASONS
    ? PREDICTIVE_REASONS[code as keyof typeof PREDICTIVE_REASONS][lang]
    : PREDICTIVE_UI.noInputs[lang];
}

export function ago(seconds: number, lang: Lang) {
  const m = Math.max(0, Math.round(seconds / 60));
  const s = m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  return lang === "hi" ? `${s} ${t("ago", lang)}` : `${s} ${t("ago", lang)}`;
}

export const HAZARD_LABEL: Record<string, { en: string; hi: string }> = {
  open_drain_or_manhole_risk: { en: "Open drain / manhole risk", hi: "खुला नाला / मैनहोल" },
  strong_current: { en: "Strong current", hi: "तेज़ बहाव" },
  submerged_vehicle: { en: "Vehicle stuck in water", hi: "पानी में फँसी गाड़ी" },
  electric_pole_or_wire_in_water: { en: "Electric wire / pole in water", hi: "पानी में बिजली का तार" },
  debris: { en: "Debris", hi: "मलबा" },
  poor_visibility_night: { en: "Poor visibility", hi: "कम रोशनी" },
};
