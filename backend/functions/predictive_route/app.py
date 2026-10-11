"""POST /predictive-route: prototype route risk using forecasts and current flood data."""
import logging
import time

from common import config, db, geo, http, predictive, routing, weather_forecast
from functions.route.app import BBOX_MARGIN_DEG, load_graph

log = logging.getLogger()


def _point_key(point):
    return round(point["lat"], 5), round(point["lon"], 5)


def _option(vehicle, result, forecasts, spots, hotspots, now,
            reports_available, hotspots_available):
    route = result["safe"]
    if not result["normal"] or route is None:
        reasons = ["no_feasible_route"]
        if result["normal"] and result["safe"] is None:
            reasons.append("route_blocked")
        return {
            "vehicle": vehicle, "feasible": False, "route": None, "risk_score": None,
            "risk_level": "unknown", "coverage_fraction": 0, "reasons": reasons,
        }
    score = predictive.evaluate_route(
        route, vehicle, spots, hotspots, forecasts, now,
        reports_available=reports_available, hotspots_available=hotspots_available,
    )
    return {"vehicle": vehicle, "feasible": True, "route": route, **score}


def handler(event, _ctx):
    try:
        body = http.body(event)
    except ValueError as exc:
        return http.bad(str(exc))
    frm, to = body.get("from"), body.get("to")
    vehicle = body.get("vehicle")
    city = str(body.get("city") or "delhi").lower()
    if not (isinstance(frm, list) and isinstance(to, list) and len(frm) == 2 and len(to) == 2
            and geo.valid_lonlat(*frm) and geo.valid_lonlat(*to)):
        return http.bad("from/to must be [lon, lat]")
    if vehicle not in config.VEHICLES:
        return http.bad(f"vehicle must be one of {config.VEHICLES}")
    if city not in config.CITIES or body.get("mode", "live") != "live":
        return http.bad("predictive routing supports live data for supported cities only")
    frm, to = [float(value) for value in frm], [float(value) for value in to]
    west, south, east, north = config.CITIES[city]["bbox"]
    if not all(west <= point[0] <= east and south <= point[1] <= north for point in (frm, to)):
        return http.bad(f"Both points must be inside {config.CITIES[city]['label']}: we only have road and flood data there.")

    try:
        graph = load_graph(city)
    except Exception:
        log.exception("predictive route graph load failed")
        return http.bad("Routing is not available for this city yet.", 503)

    bbox = [min(frm[0], to[0]) - BBOX_MARGIN_DEG, min(frm[1], to[1]) - BBOX_MARGIN_DEG,
            max(frm[0], to[0]) + BBOX_MARGIN_DEG, max(frm[1], to[1]) + BBOX_MARGIN_DEG]
    now = time.time()
    reports_available, hotspots_available = True, True
    try:
        raw_reports = db.query_bbox(city, "live", bbox, now - 2 * config.EXPIRE_AFTER_H * 3600, now)
    except Exception:
        log.exception("predictive route community reports load failed")
        raw_reports = []
        reports_available = False
    try:
        hotspot_items = db.hotspots(city)
    except Exception:
        log.exception("predictive route hotspots load failed")
        hotspot_items = []
        hotspots_available = False
    active_spots = db.active_spots(
        city, "live", bbox, now, report_items=raw_reports, hotspot_items=hotspot_items,
    )
    hotspots = [item for item in hotspot_items if not item["hotspotId"].startswith("#")]
    included_report_ids = {
        report_id
        for spot in active_spots
        for report_id in ([spot.get("spotId")] + spot.get("reportIds", []))
    }
    for report in raw_reports:
        activity = max(float(report.get("ts") or 0), float(report.get("lastStillTs") or 0))
        closure_cleared = predictive.closure_is_cleared(report, included_report_ids, now)
        if (report.get("status") != "live" or not report.get("closure")
                or report.get("source_type") != "official"
                or activity > now or now - activity > config.EXPIRE_AFTER_H * 3600
                or closure_cleared
                or report.get("reportId") in included_report_ids):
            continue
        active_spots.append({
            "spotId": report["reportId"], "lat": report["lat"], "lon": report["lon"],
            "place": report.get("place"), "depth_high": report.get("depth_high"),
            "confidence": report.get("confidence", "high"), "closure": True,
            "source_type": "official", "verification": "official", "reportCount": 1,
            "sources": ["official"], "lastUpdated": activity,
            "verdicts": {candidate: "NO_GO" for candidate in config.VEHICLES},
        })
        included_report_ids.add(report.get("reportId"))
    report_evidence = predictive.report_evidence(raw_reports, active_spots, now)
    evidence_spots = report_evidence + [spot for spot in active_spots if spot.get("predicted")]

    plans = {}
    try:
        for candidate in config.VEHICLES:
            plans[candidate] = routing.plan(graph, frm, to, candidate, active_spots)
    except ValueError as exc:
        return http.bad(str(exc))

    locations = {}
    for plan in plans.values():
        leg = plan.get("safe")
        if leg:
            for point in predictive.route_points(leg, evidence_spots, hotspots):
                locations.setdefault(_point_key(point), (point["lat"], point["lon"]))
    forecasts = {}
    weather_available = False
    if locations:
        try:
            values = weather_forecast.fetch_forecasts(
                list(locations.values()), timeout_s=config.PREDICTIVE_WEATHER_TIMEOUT_S,
            )
            forecasts = dict(zip(locations, values))
            weather_available = True
        except weather_forecast.WeatherProviderError:
            log.exception("predictive route weather forecast failed")

    options = [
        _option(candidate, plans[candidate], forecasts, evidence_spots, hotspots, now,
                reports_available, hotspots_available)
        for candidate in config.VEHICLES
    ]
    # The requested vehicle's departure alternatives are scored against the same actual route
    # and flood snapshot; only forecast arrival times shift.
    selected = next(item for item in options if item["vehicle"] == vehicle)
    alternatives = []
    if selected["feasible"]:
        for offset in (0, 15, 30, 45, 60):
            departure = now + offset * 60
            score = predictive.evaluate_route(
                selected["route"], vehicle, evidence_spots, hotspots, forecasts, departure,
                reports_available=reports_available, hotspots_available=hotspots_available,
            )
            alternatives.append({
                "offset_min": offset, "departure_at": int(departure), "feasible": True,
                "route": selected["route"], **score,
            })
    complete = [item for item in options if weather_available and reports_available
                and hotspots_available and item["feasible"]
                and item["risk_score"] is not None and item["coverage_fraction"] == 1
                and item["weather_coverage_fraction"] == 1]
    recommended_vehicle = min(
        complete,
        key=lambda item: (item["risk_score"], item["route"]["duration_min"], config.VEHICLES.index(item["vehicle"])),
    )["vehicle"] if complete else None
    comparable_departures = [
        item for item in alternatives if weather_available and reports_available
        and hotspots_available and item["risk_score"] is not None
        and item["coverage_fraction"] == 1 and item["weather_coverage_fraction"] == 1
    ]
    preferred_departure = None
    if comparable_departures:
        best = min(comparable_departures, key=lambda item: (item["risk_score"], item["offset_min"]))
        current_score = alternatives[0]["risk_score"]
        if best["offset_min"] > 0 and current_score is not None and best["risk_score"] < current_score:
            preferred_departure = best["departure_at"]
    for item in alternatives:
        item["recommended"] = item["departure_at"] == preferred_departure

    return http.resp(200, {
        "generated_at": int(now),
        "lookahead_minutes": config.PREDICTIVE_LOOKAHEAD_MIN,
        "risk_model": {
            "name": "prototype_weighted_index",
            "is_probability": False,
            "weights": config.PREDICTIVE_RISK_WEIGHTS,
            "weather_signal_weights": config.PREDICTIVE_WEATHER_SIGNAL_WEIGHTS,
            "rain_score_per_mm": config.PREDICTIVE_RAIN_SCORE_PER_MM,
            "score_bands": config.PREDICTIVE_SCORE_BANDS,
        },
        "selected_vehicle": vehicle,
        "recommended_vehicle": recommended_vehicle,
        "vehicle_options": options,
        "departure_alternatives": alternatives,
        "preferred_departure_at": preferred_departure,
        "data_quality": {
            "weather": "available" if weather_available else "unavailable",
            "reports_available": reports_available,
            "hotspots_available": hotspots_available,
            "forecast_locations": len(locations),
            "active_reports": len(report_evidence),
            "hotspots": len(hotspots),
            "limitations": [
                "The score is a prototype index, not a probability or safety guarantee.",
                "Weather forecasts do not provide route-level water depth.",
                "Missing or stale reports do not mean a route is dry.",
            ],
        },
    })
