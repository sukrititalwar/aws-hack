"""Merge individual reports into "spots" (one flooded place), pure functions.

A report is a plain dict:
  reportId, lat, lon, ts (epoch s: createdAt, or the replay time in demo mode),
  depth_low, depth_high, confidence, image_quality, flowing_water, hazards,
  votes {still, cleared, wrong}, lastStillTs, source_type, place
"""
from . import config, geo, rules

_CONF_ORDER = ["low", "medium", "high"]
_QUAL_ORDER = ["poor", "ok", "good"]


def report_weight(r: dict) -> float:
    w = config.CONFIDENCE_WEIGHT.get(r.get("confidence"), 0.4)
    w *= config.SOURCE_WEIGHT.get(r.get("source_type", "photo"), 1.0)
    wrong = int((r.get("votes") or {}).get("wrong", 0))
    w *= (1 - config.WRONG_VOTE_PENALTY) ** wrong
    return max(w, config.MIN_REPORT_WEIGHT)


def weighted_median(pairs) -> float:
    """pairs: [(value, weight)]"""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def last_activity(r: dict) -> float:
    return max(float(r["ts"]), float(r.get("lastStillTs") or 0))


def cluster(reports: list[dict]) -> list[list[dict]]:
    """Greedy clustering by time: a report joins a spot if it is within SPOT_RADIUS_M of the
    spot centre and within SPOT_WINDOW_MIN of the spot's latest photo."""
    groups: list[dict] = []
    for r in sorted(reports, key=lambda x: float(x["ts"])):
        best = None
        for g in groups:
            d = geo.haversine_m(g["lon"], g["lat"], float(r["lon"]), float(r["lat"]))
            if d <= config.SPOT_RADIUS_M and float(r["ts"]) - g["last_ts"] <= config.SPOT_WINDOW_MIN * 60:
                if best is None or d < best[0]:
                    best = (d, g)
        if best is None:
            groups.append({"lat": float(r["lat"]), "lon": float(r["lon"]), "last_ts": float(r["ts"]),
                           "members": [r], "wsum": report_weight(r)})
        else:
            g = best[1]
            w = report_weight(r)
            # running weighted centroid
            g["lat"] = (g["lat"] * g["wsum"] + float(r["lat"]) * w) / (g["wsum"] + w)
            g["lon"] = (g["lon"] * g["wsum"] + float(r["lon"]) * w) / (g["wsum"] + w)
            g["wsum"] += w
            g["last_ts"] = float(r["ts"])
            g["members"].append(r)
    return [g["members"] for g in groups]


def summarise(members: list[dict], now: float) -> dict:
    weights = [report_weight(r) for r in members]
    depth_high = weighted_median([(float(r["depth_high"]), w) for r, w in zip(members, weights)])
    depth_low = weighted_median([(float(r["depth_low"]), w) for r, w in zip(members, weights)])
    depth_low = min(depth_low, depth_high)
    confidence = max((r.get("confidence", "low") for r in members), key=_CONF_ORDER.index)
    quality = max((r.get("image_quality", "ok") for r in members), key=_QUAL_ORDER.index)
    flow_w = sum(w for r, w in zip(members, weights) if r.get("flowing_water"))
    hazards = sorted({h for r in members for h in (r.get("hazards") or []) if h != "none"})
    official_closure = any(r.get("closure") and r.get("source_type") == "official" for r in members)

    assessment = {"depth_cm_high": depth_high, "confidence": confidence, "image_quality": quality,
                  "flowing_water": flow_w > sum(weights) / 2, "hazards": hazards}
    result = rules.verdicts_for(assessment)
    verdicts = {v: x["verdict"] for v, x in result["verdicts"].items()}
    if official_closure:
        verdicts = {v: "NO_GO" for v in verdicts}

    last_photo = max(float(r["ts"]) for r in members)
    last_act = max(last_activity(r) for r in members)
    clears = sum(int((r.get("votes") or {}).get("cleared", 0)) for r in members)
    cleared = clears >= config.CLEARED_VOTES_NEEDED and now - last_photo >= config.CLEARED_QUIET_MIN * 60
    lat = sum(float(r["lat"]) * w for r, w in zip(members, weights)) / sum(weights)
    lon = sum(float(r["lon"]) * w for r, w in zip(members, weights)) / sum(weights)
    places = [r.get("place") for r in members if r.get("place")]

    return {
        "spotId": min(members, key=lambda r: float(r["ts"]))["reportId"],
        "lat": round(lat, 6), "lon": round(lon, 6),
        "place": places[-1] if places else None,
        "depth_low": round(depth_low), "depth_high": round(depth_high),
        "confidence": confidence,
        "hazards": hazards,
        "danger": result["danger"],
        "verdicts": verdicts,
        "reportCount": len(members),
        "reportIds": [r["reportId"] for r in members],
        "sources": sorted({r.get("source_type", "photo") for r in members}),
        "firstReported": min(float(r["ts"]) for r in members),
        "lastUpdated": last_act,
        "ageMin": round((now - last_act) / 60),
        "faded": now - last_act > config.FADE_AFTER_H * 3600,
        "status": "cleared" if cleared else "live",
        "source_urls": [r["source_url"] for r in members if r.get("source_url")][-3:],
    }


def build_spots(reports: list[dict], now: float, include_cleared: bool = False) -> list[dict]:
    """Active spots at time `now` (works for live mode and for demo replay at any time)."""
    active = [r for r in reports
              if float(r["ts"]) <= now
              and now - last_activity(r) <= config.EXPIRE_AFTER_H * 3600
              and r.get("depth_high") is not None]
    spots = [summarise(m, now) for m in cluster(active)]
    for s in spots:
        s["verification"] = verification(s)
    if not include_cleared:
        spots = [s for s in spots if s["status"] != "cleared"]
    return spots


def predicted_depth(kind: str, rain_past3h: float, rain_now: float) -> tuple[float, float]:
    """Rough depth range for a chronic hotspot from observed rain. Deliberately coarse, always
    marked low-confidence so the rules engine escalates (conservative)."""
    intensity = max(rain_past3h, rain_now * 3)
    base = 35 if kind == "underpass" else 20
    if intensity >= 50:
        hi = base * 1.6
    elif intensity >= config.RAIN_PAST3H_FLOOD_MM:
        hi = base
    else:
        hi = base * 0.6
    return round(hi * 0.5), round(hi)


def predicted_spots(hotspots: list[dict], real_spots: list[dict], now: float) -> list[dict]:
    """Virtual spots at chronic hotspots while it is raining hard and nobody has reported yet."""
    out = []
    for h in hotspots:
        if h.get("risk") != "flooding_likely_now":
            continue
        if any(geo.haversine_m(h["lon"], h["lat"], s["lon"], s["lat"]) <= config.PREDICTED_SUPPRESS_M
               for s in real_spots):
            continue
        lo, hi = predicted_depth(h.get("kind", "other"), float(h.get("rainPast3h") or 0), float(h.get("rainNow") or 0))
        r = rules.verdicts_for({"depth_cm_high": hi, "confidence": "low", "image_quality": "ok"})
        out.append({
            "spotId": f"pred-{h['hotspotId']}", "lat": h["lat"], "lon": h["lon"], "place": h.get("name"),
            "depth_low": lo, "depth_high": hi, "confidence": "low", "hazards": [], "danger": False,
            "verdicts": {v: x["verdict"] for v, x in r["verdicts"].items()},
            "reportCount": 0, "reportIds": [], "sources": ["predicted"], "predicted": True,
            "rainPast3h": h.get("rainPast3h"), "rainNow": h.get("rainNow"), "source_url": h.get("source_url"),
            "firstReported": now, "lastUpdated": float(h.get("riskUpdatedAt") or now), "ageMin": 0,
            "faded": False, "status": "predicted",
        })
    return out


def verification(spot: dict) -> str:
    """Ground-truth level shown to users: predicted < ai_estimate < confirmed < official."""
    if spot.get("predicted"):
        return "predicted"
    if "official" in spot.get("sources", []):
        return "official"
    if spot.get("reportCount", 0) >= 2 or len(set(spot.get("sources", [])) - {"predicted"}) >= 2:
        return "confirmed"
    return "single_report"
