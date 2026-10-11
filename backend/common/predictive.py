"""Deterministic prototype risk scoring for a route and expected arrival times."""
import math

from . import config, geo, rules
from .weather_forecast import at_time


def _point_at(coords, fraction):
    lengths = [geo.haversine_m(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1)]
    total = sum(lengths)
    if total <= 0:
        return {"lon": coords[0][0], "lat": coords[0][1], "fraction": 0}
    target = total * fraction
    passed = 0.0
    for index, length in enumerate(lengths):
        if passed + length >= target or index == len(lengths) - 1:
            part = 0 if length == 0 else max(0, min(1, (target - passed) / length))
            a, b = coords[index], coords[index + 1]
            return {"lon": a[0] + (b[0] - a[0]) * part,
                    "lat": a[1] + (b[1] - a[1]) * part,
                    "fraction": fraction}
        passed += length
    return {"lon": coords[-1][0], "lat": coords[-1][1], "fraction": 1}


def _project(point, coords):
    lengths = [geo.haversine_m(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1)]
    total = sum(lengths)
    if total <= 0:
        return geo.haversine_m(*point, *coords[0]), 0
    passed, closest = 0.0, (float("inf"), 0.0)
    k = math.cos(math.radians(point[1]))
    scale = math.pi / 180 * geo.EARTH_R
    for index, length in enumerate(lengths):
        a, b = coords[index], coords[index + 1]
        ax, ay = (a[0] - point[0]) * k * scale, (a[1] - point[1]) * scale
        bx, by = (b[0] - point[0]) * k * scale, (b[1] - point[1]) * scale
        dx, dy = bx - ax, by - ay
        squared = dx * dx + dy * dy
        part = 0 if squared == 0 else max(0, min(1, -(ax * dx + ay * dy) / squared))
        distance = math.hypot(ax + part * dx, ay + part * dy)
        if distance < closest[0]:
            closest = (distance, (passed + part * length) / total)
        passed += length
    return closest


def route_points(leg, spots, hotspots):
    """Sample the line and add locations of reports/hotspots close to it for risk matching."""
    coords = leg["geometry"]["coordinates"]
    if not coords:
        return []
    lengths = [geo.haversine_m(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1)]
    total = sum(lengths)
    count = max(1, math.ceil(total / config.PREDICTIVE_SAMPLE_SPACING_M))
    points = [_point_at(coords, index / count) for index in range(count + 1)]
    events = list(spots) + [h for h in hotspots if not str(h.get("hotspotId", "")).startswith("#")]
    for item in events:
        if not geo.valid_lonlat(item.get("lon"), item.get("lat")):
            continue
        distance, fraction = _project((float(item["lon"]), float(item["lat"])), coords)
        if distance <= config.PREDICTIVE_EVENT_RADIUS_M:
            points.append({"lon": float(item["lon"]), "lat": float(item["lat"]), "fraction": fraction})
    unique = {}
    for point in points:
        key = (round(point["lat"], 5), round(point["lon"], 5))
        unique.setdefault(key, point)
    return list(unique.values())


def closure_is_cleared(report, active_report_ids, now):
    if report.get("reportId") in active_report_ids:
        return False
    votes = report.get("votes") or {}
    return (int(votes.get("cleared", 0)) >= config.CLEARED_VOTES_NEEDED
            and now - float(report.get("ts") or 0) >= config.CLEARED_QUIET_MIN * 60)


def report_evidence(reports, active_spots, now):
    """Recreate active individual-report evidence so merged spots cannot hide disagreement."""
    active_ids = {
        report_id
        for spot in active_spots if not spot.get("predicted")
        for report_id in spot.get("reportIds", [])
    }
    inherited_verification = {
        report_id: spot.get("verification", "single_report")
        for spot in active_spots if not spot.get("predicted")
        for report_id in spot.get("reportIds", [])
    }
    evidence = []
    for report in reports:
        source = report.get("source_type", "photo")
        official_closure = bool(report.get("closure") and source == "official")
        report_id = report.get("reportId")
        activity = max(float(report.get("ts") or 0), float(report.get("lastStillTs") or 0))
        closure_cleared = official_closure and closure_is_cleared(report, active_ids, now)
        if (report.get("status") != "live" or not report_id
                or activity > now or now - activity > config.EXPIRE_AFTER_H * 3600
                or (report_id not in active_ids and not official_closure)
                or closure_cleared
                or not geo.valid_lonlat(report.get("lon"), report.get("lat"))
                or (report.get("depth_high") is None and not official_closure)):
            continue
        if official_closure:
            verdicts = {vehicle: "NO_GO" for vehicle in config.VEHICLES}
        else:
            result = rules.verdicts_for({
                "depth_cm_high": float(report["depth_high"]),
                "confidence": report.get("confidence", "low"),
                "image_quality": report.get("image_quality", "poor"),
                "flowing_water": report.get("flowing_water", False),
                "hazards": report.get("hazards") or [],
            })
            verdicts = {vehicle: item["verdict"] for vehicle, item in result["verdicts"].items()}
        evidence.append({
            "spotId": report_id, "lat": float(report["lat"]), "lon": float(report["lon"]),
            "place": report.get("place"), "depth_high": report.get("depth_high"),
            "confidence": report.get("confidence", "low"), "closure": official_closure,
            "source_type": source,
            "verification": "official" if source == "official" else inherited_verification.get(report_id, "single_report"),
            "reportCount": 1, "sources": [source], "lastUpdated": activity, "ts": activity,
            "verdicts": verdicts,
        })
    return evidence


def _weather_score(forecast):
    if forecast is None:
        return None
    rain = forecast.get("rain")
    if rain is None:
        rain = forecast.get("precipitation")
    probability = forecast.get("precipitation_probability")
    components = []
    if rain is not None:
        components.append((min(100.0, rain * config.PREDICTIVE_RAIN_SCORE_PER_MM),
                           config.PREDICTIVE_WEATHER_SIGNAL_WEIGHTS["rain"]))
    if probability is not None:
        components.append((probability, config.PREDICTIVE_WEATHER_SIGNAL_WEIGHTS["probability"]))
    code = forecast.get("weather_code")
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        components.append((45.0, config.PREDICTIVE_WEATHER_SIGNAL_WEIGHTS["weather_code"]))
    elif code in (95, 96, 99):
        components.append((75.0, config.PREDICTIVE_WEATHER_SIGNAL_WEIGHTS["weather_code"]))
    if not components:
        return None
    return sum(value * weight for value, weight in components) / sum(weight for _, weight in components)


def _event_quality(item, arrival_at):
    updated = float(item.get("lastUpdated") or item.get("riskUpdatedAt") or item.get("ts") or arrival_at)
    age_min = max(0.0, (arrival_at - updated) / 60)
    fresh = max(0.0, 1 - age_min / (config.EXPIRE_AFTER_H * 60))
    if "verdicts" in item:
        verification_weight = {
            "official": 1.0, "confirmed": 0.85, "single_report": 0.65, "predicted": 0.4,
        }.get(item.get("verification"), 0.55)
        confidence_weight = {"high": 1.0, "medium": 0.75, "low": 0.5}.get(item.get("confidence"), 0.5)
        return fresh * verification_weight * confidence_weight, age_min
    risk_weight = {"flooding_likely_now": 1.0, "likely_flooded_soon": 0.7, "normal": 0.0}.get(item.get("risk"), 0.0)
    updated = float(item.get("riskUpdatedAt") or item.get("updatedAt") or arrival_at)
    age_min = max(0.0, (arrival_at - updated) / 60)
    freshness = max(0.0, 1 - age_min / 90)
    return risk_weight * freshness, age_min


def _report_severity(verdict):
    return {"NO_GO": 100.0, "RISKY": 65.0, "GO": 20.0}.get(verdict, 0.0)


def evaluate_route(leg, vehicle, spots, hotspots, forecast_by_point, departure_at,
                   reports_available=True, hotspots_available=True):
    """Return an auditable route index and explicit coverage/freshness metadata."""
    points = route_points(leg, spots, hotspots)
    point_scores, reasons = [], set()
    stale_reports, stale_hotspots, conflicts = set(), set(), set()
    lookahead_end = departure_at + config.PREDICTIVE_LOOKAHEAD_MIN * 60
    covered_points, weather_points = 0, 0
    reports_near_route = False
    for point in points:
        arrival = departure_at + float(leg["duration_min"]) * 60 * point["fraction"]
        if arrival > lookahead_end:
            continue
        covered_points += 1
        key = (round(point["lat"], 5), round(point["lon"], 5))
        forecast = at_time(forecast_by_point.get(key), arrival)
        weather_score = _weather_score(forecast)
        if weather_score is not None:
            weather_points += 1
        if forecast:
            rain = forecast.get("rain")
            rain = forecast.get("precipitation") if rain is None else rain
            if ((rain is not None and rain >= config.PREDICTIVE_RAIN_REASON_MM)
                    or (forecast.get("precipitation_probability") or 0) >= config.PREDICTIVE_RAIN_REASON_PROBABILITY
                    or forecast.get("weather_code") in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)):
                reasons.add("rain_expected")

        nearby_reports = []
        for spot in spots:
            distance = geo.haversine_m(point["lon"], point["lat"], spot["lon"], spot["lat"])
            if distance <= config.PREDICTIVE_EVENT_RADIUS_M:
                quality, age = _event_quality(spot, arrival)
                verdict = spot.get("verdicts", {}).get(vehicle, "GO")
                severity = _report_severity(verdict)
                nearby_reports.append((severity * quality, spot, age))
                if age > 90:
                    stale_reports.add(spot["spotId"])
        report_score = max((entry[0] for entry in nearby_reports), default=0.0)
        if nearby_reports:
            reports_near_route = True
            reasons.add("active_report_near_route")
            if any(spot.get("closure") and spot.get("source_type") == "official"
                   for _, spot, _ in nearby_reports):
                reasons.add("official_closure")
            if len({spot.get("verdicts", {}).get(vehicle, "GO")
                    for _, spot, _ in nearby_reports}) > 1:
                conflicts.update(spot["spotId"] for _, spot, _ in nearby_reports)

        nearby_hotspots = []
        for hotspot in hotspots:
            if str(hotspot.get("hotspotId", "")).startswith("#"):
                continue
            distance = geo.haversine_m(point["lon"], point["lat"], hotspot["lon"], hotspot["lat"])
            if distance <= config.PREDICTIVE_EVENT_RADIUS_M:
                quality, age = _event_quality(hotspot, arrival)
                severity = 80.0 if hotspot.get("risk") == "flooding_likely_now" else 55.0
                nearby_hotspots.append(severity * quality * (1 - distance / config.PREDICTIVE_EVENT_RADIUS_M))
                if age > 30:
                    stale_hotspots.add(hotspot["hotspotId"])
        hotspot_score = max(nearby_hotspots, default=0.0)
        if hotspot_score > 0:
            reasons.add("chronic_hotspot_risk")

        components = []
        if weather_score is not None:
            components.append((weather_score, config.PREDICTIVE_RISK_WEIGHTS["weather"]))
        if reports_available:
            components.append((report_score, config.PREDICTIVE_RISK_WEIGHTS["reports"]))
        if hotspots_available:
            components.append((hotspot_score, config.PREDICTIVE_RISK_WEIGHTS["hotspots"]))
        if components:
            point_scores.append(sum(value * weight for value, weight in components)
                                / sum(weight for _, weight in components))

    if stale_reports or stale_hotspots:
        reasons.add("stale_observations")
    if conflicts:
        reasons.add("conflicting_reports")
    if reports_available and not reports_near_route:
        reasons.add("no_recent_reports")
    if not reports_available:
        reasons.add("reports_unavailable")
    if not hotspots_available:
        reasons.add("hotspots_unavailable")
    total_points = len(points)
    duration = float(leg["duration_min"])
    coverage = min(1.0, config.PREDICTIVE_LOOKAHEAD_MIN / duration) if duration > 0 else 1.0
    if covered_points < total_points:
        reasons.add("route_horizon_partial")
    if not point_scores or (weather_points == 0 and all(score == 0 for score in point_scores)):
        score = None
    else:
        score = round(0.6 * max(point_scores) + 0.4 * (sum(point_scores) / len(point_scores)))

    if score is None:
        level = "unknown"
        reasons.add("no_route_risk_inputs")
    elif score >= config.PREDICTIVE_SCORE_BANDS["elevated"]:
        level = "elevated"
    elif score >= config.PREDICTIVE_SCORE_BANDS["watch"]:
        level = "watch"
    else:
        level = "lower_relative_concern"
    if not weather_points:
        reasons.add("weather_unavailable")
    elif weather_points < covered_points:
        reasons.add("weather_partial")

    return {
        "risk_score": score,
        "risk_level": level,
        "coverage_fraction": round(coverage, 3),
        "covered_points": covered_points,
        "total_points": total_points,
        "weather_coverage_fraction": round(weather_points / covered_points, 3) if covered_points else 0,
        "stale_reports": len(stale_reports),
        "stale_hotspots": len(stale_hotspots),
        "conflicting_report_groups": len(conflicts),
        "reasons": sorted(reasons),
    }
