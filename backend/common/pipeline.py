"""Photo -> fields to store on the report. Used by the analyze Lambda and seed/eval scripts."""
from . import depth, rules


def assess(image_bytes: bytes, city: str, place: str | None) -> tuple[dict, dict]:
    """Run Bedrock + rules. Returns (report fields, metrics)."""
    a, metrics = depth.estimate_depth(image_bytes, city, place)
    return fields_from_assessment(a), metrics


def fields_from_assessment(a: dict) -> dict:
    if not a["is_flooded_road_photo"]:
        return {"status": "rejected",
                "rejection_reason": a.get("rejection_reason") or "This does not look like a flooded road.",
                "model_json": a}
    r = rules.verdicts_for(a)
    return {
        "status": "live",
        "model_json": a,
        "depth_low": a["depth_cm_low"],
        "depth_high": a["depth_cm_high"],
        "confidence": a["confidence"],
        "image_quality": a["image_quality"],
        "flowing_water": a["flowing_water"],
        "hazards": a["hazards"],
        "reasoning": a["reasoning"],
        "reasoning_hi": a["reasoning_hi"],
        "reference_objects": a["reference_objects"],
        "location_type": a["location_type"],
        "verdicts": r["verdicts"],
        "danger": r["danger"],
        "needs_inspection": r["needs_inspection"],
        "inspection_reasons": r["inspection_reasons"],
    }
