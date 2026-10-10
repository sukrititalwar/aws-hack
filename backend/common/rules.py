"""Deterministic rules engine: the AI estimates depth, this code decides the verdict.

Input is the model's assessment dict (see prompts/depth_prompt.txt). Output is one verdict
per vehicle. Pure functions, no AWS calls, fully unit-tested in tests/test_rules.py.
"""
from . import config

LEVELS = ["GO", "RISKY", "NO_GO"]

VEHICLE_LABELS = {
    "pedestrian": ("Walking", "पैदल"),
    "bicycle": ("Bicycle", "साइकिल"),
    "scooter": ("Scooter / bike", "स्कूटर / बाइक"),
    "ev_scooter": ("EV Scooter", "ई-स्कूटर"),
    "auto": ("Auto / e-rickshaw", "ऑटो / ई-रिक्शा"),
    "car": ("Car", "कार"),
    "suv": ("SUV", "एसयूवी"),
    "bus": ("Bus / truck", "बस / ट्रक"),
    "ambulance": ("Ambulance", "एम्बुलेंस"),
}

VERDICT_LABELS = {
    "GO": ("OK to cross", "जा सकते हैं"),
    "RISKY": ("Risky", "जोखिम है"),
    "NO_GO": ("Do not cross", "मत जाइए"),
}

# Why a given vehicle is at risk, in plain words.
RISK_REASON = {
    "pedestrian": ("water can hide open drains and knock you off your feet",
                   "पानी में खुले नाले छिपे हो सकते हैं और आप गिर सकते हैं"),
    "bicycle": ("you can lose balance and cannot see potholes",
                "संतुलन बिगड़ सकता है और गड्ढे नहीं दिखते"),
    "scooter": ("water can enter the exhaust and stall the engine",
                "पानी साइलेंसर में जाकर इंजन बंद कर सकता है"),
    "ev_scooter": ("estimated depth and water resistance vary by model; this app's threshold is a precaution, not a damage prediction or safety guarantee",
                   "अनुमानित गहराई और पानी से बचाव मॉडल के अनुसार अलग हो सकते हैं; ऐप की सीमा एहतियात है, नुकसान का अनुमान या सुरक्षा की गारंटी नहीं"),
    "auto": ("water can reach the engine and floor",
             "पानी इंजन और फ़र्श तक पहुँच सकता है"),
    "car": ("water can enter the air intake and the car can float",
            "पानी एयर इनटेक में जा सकता है और कार तैर सकती है"),
    "suv": ("deep water can still stall the engine",
            "गहरा पानी इंजन बंद कर सकता है"),
    "bus": ("very deep water can stall even large vehicles",
            "बहुत गहरे पानी में बड़ी गाड़ियाँ भी बंद हो सकती हैं"),
    "ambulance": ("a stalled ambulance cannot reach the patient",
                  "बंद एम्बुलेंस मरीज़ तक नहीं पहुँच पाएगी"),
}


def base_verdict(vehicle: str, depth_cm: float) -> str:
    """Threshold-only verdict for one vehicle."""
    t = config.THRESHOLDS[vehicle]
    if depth_cm < t["go"]:
        return "GO"
    if depth_cm < t["no_go"]:
        return "RISKY"
    return "NO_GO"


def escalation_steps(assessment: dict) -> tuple[int, list[str]]:
    """How many levels to worsen every verdict, plus human-readable reasons."""
    steps, reasons = 0, []
    if assessment.get("confidence") == "low" or assessment.get("image_quality") == "poor":
        steps += 1
        reasons.append("unclear photo")
    if assessment.get("flowing_water"):
        steps += 1
        reasons.append("water is flowing")
    hazards = set(assessment.get("hazards") or [])
    if hazards & config.ESCALATING_HAZARDS:
        steps += 1
        reasons.append("hazard in the water")
    return steps, reasons


def worsen(level: str, steps: int) -> str:
    return LEVELS[min(LEVELS.index(level) + steps, len(LEVELS) - 1)]


def inspection_flags(assessment: dict) -> list[str]:
    """Reasons a depth number should not be trusted. One photo (or a video frame) cannot give
    reliable metric depth: perspective, reflections and unknown road geometry get in the way.
    When any of these hold we say "requires inspection" instead of "passable"."""
    reasons = []
    if assessment.get("confidence") == "low":
        reasons.append("low confidence")
    if assessment.get("image_quality") == "poor":
        reasons.append("poor image")
    if "reference_objects" in assessment and not assessment["reference_objects"]:
        reasons.append("no reference object visible")
    lo, hi = assessment.get("depth_cm_low"), assessment.get("depth_cm_high")
    if lo is not None and hi is not None and float(hi) - float(lo) > 30:
        reasons.append("very wide depth range")
    return reasons


# User-facing categories (never a fabricated centimetre figure on their own).
CATEGORY_LABELS = {
    "passable": ("Passable", "पार कर सकते हैं"),
    "potentially_unsafe": ("Potentially unsafe", "जोखिम भरा"),
    "unsafe": ("Unsafe", "असुरक्षित"),
    "requires_inspection": ("Requires inspection", "जाँच ज़रूरी"),
}


def category_of(verdict: str, needs_inspection: bool, vehicle: str | None = None) -> str:
    if verdict == "GO":
        if vehicle == "ev_scooter" and not needs_inspection:
            return "potentially_unsafe"
        return "requires_inspection" if needs_inspection else "passable"
    return "potentially_unsafe" if verdict == "RISKY" else "unsafe"


def verdicts_for(assessment: dict) -> dict:
    """Return {vehicle: {verdict, label_en, label_hi, why, why_hi}} plus a danger flag.

    Uses depth_cm_high (the worst case) on purpose: a too-optimistic GO is the dangerous error.
    """
    depth = float(assessment.get("depth_cm_high") or 0)
    hazards = set(assessment.get("hazards") or [])
    fatal = config.FATAL_HAZARD in hazards
    steps, reasons = escalation_steps(assessment)
    inspect = inspection_flags(assessment)
    if "no reference object visible" in inspect and "unclear photo" not in reasons:
        steps += 1
        reasons.append("no reference object visible")
    d = round(depth)

    out = {}
    for v in config.VEHICLES:
        verdict = "NO_GO" if fatal else worsen(base_verdict(v, depth), steps)
        name_en, name_hi = VEHICLE_LABELS[v]
        lab_en, lab_hi = VERDICT_LABELS[verdict]
        if fatal:
            why = "Electric wire or pole in the water. Danger of electrocution. Stay away."
            why_hi = "पानी में बिजली का तार या खंभा है। करंट का ख़तरा। दूर रहें।"
        elif verdict == "GO":
            if v == "ev_scooter":
                why = ("Estimated depth is below this app's EV Scooter caution threshold; "
                       "this is not a safety guarantee. Avoid crossing if unsure.")
                why_hi = ("अनुमानित गहराई इस ऐप की ई-स्कूटर सावधानी सीमा से कम है; "
                          "इससे सुरक्षा की गारंटी नहीं मिलती। शक हो तो पार न करें।")
            else:
                why = f"Water about {d} cm. Usually OK for this vehicle, go slowly."
                why_hi = f"पानी लगभग {d} सेमी। आमतौर पर ठीक है, धीरे चलें।"
        else:
            r_en, r_hi = RISK_REASON[v]
            why = f"Water about {d} cm: {r_en}."
            why_hi = f"पानी लगभग {d} सेमी: {r_hi}।"
            if reasons:
                why += " Also: " + ", ".join(reasons) + "."
        if v == "ev_scooter" and verdict == "GO":
            lab_en, lab_hi = "Below app caution threshold", "ऐप की सावधानी सीमा से कम"
        out[v] = {
            "vehicle": v,
            "verdict": verdict,
            "category": category_of(verdict, bool(inspect), v),
            "label_en": f"{name_en}: {lab_en}",
            "label_hi": f"{name_hi}: {lab_hi}",
            "why": why,
            "why_hi": why_hi,
        }
    return {"verdicts": out, "danger": fatal, "escalations": reasons,
            "needs_inspection": bool(inspect), "inspection_reasons": inspect}


def worst(levels) -> str:
    """Worst of several verdicts (used when merging)."""
    idx = max((LEVELS.index(l) for l in levels), default=0)
    return LEVELS[idx]
