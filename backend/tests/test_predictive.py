import json
from datetime import datetime, timezone

import pytest

from common import config, predictive, routing, weather_forecast
from tests.test_routing import D, NODES, graph


NOW = 1_760_000_000


def route_leg(duration_min=10):
    return {
        "geometry": {"type": "LineString", "coordinates": [[72.85, 19.101], [72.851, 19.101]]},
        "distance_m": 105,
        "duration_min": duration_min,
        "spots_on_route": [],
    }


def forecast(rain=0, probability=0, code=0, at=NOW):
    return [
        {"time": datetime.fromtimestamp(at, timezone.utc), "precipitation": rain,
         "precipitation_probability": probability, "rain": rain, "weather_code": code},
        {"time": datetime.fromtimestamp(at + 3600, timezone.utc), "precipitation": 0,
         "precipitation_probability": 0, "rain": 0, "weather_code": 0},
    ]


def test_weather_normalization_converts_values_and_timestamps_to_utc():
    normalized = weather_forecast.normalize_forecast({
        "hourly_units": {"precipitation": "mm", "precipitation_probability": "%",
                         "rain": "mm", "weather_code": "wmo code"},
        "hourly": {"time": ["2026-01-01T12:00", "2026-01-01T13:00"],
                   "precipitation": [1.25, 0], "precipitation_probability": [70, 0],
                   "rain": [1.25, 0], "weather_code": [61, 0]},
    })
    assert normalized[0]["time"] == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert normalized[0]["precipitation"] == 1.25
    assert normalized[0]["precipitation_probability"] == 70
    assert normalized[0]["weather_code"] == 61


def test_weather_normalization_rejects_invalid_units_and_arrays():
    payload = {"hourly_units": {"precipitation": "inch"},
               "hourly": {"time": ["2026-01-01T12:00"], "precipitation": [1],
                          "precipitation_probability": [0], "rain": [0], "weather_code": [0]}}
    with pytest.raises(weather_forecast.WeatherProviderError, match="units"):
        weather_forecast.normalize_forecast(payload)
    payload["hourly_units"]["precipitation"] = "mm"
    payload["hourly"]["rain"] = []
    with pytest.raises(weather_forecast.WeatherProviderError, match="hourly rain"):
        weather_forecast.normalize_forecast(payload)


def test_weather_adapter_preserves_multi_location_response_order(monkeypatch):
    def location(amount):
        return {
            "hourly_units": {"precipitation": "mm", "precipitation_probability": "%",
                             "rain": "mm", "weather_code": "wmo code"},
            "hourly": {"time": ["2026-01-01T12:00Z"], "precipitation": [amount],
                       "precipitation_probability": [50], "rain": [amount], "weather_code": [61]},
        }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps([location(1), location(2)]).encode()

    def open_url(url, timeout):
        assert "precipitation_probability" in url and "weather_code" in url
        assert timeout == 2
        return Response()

    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", open_url)
    results = weather_forecast.fetch_forecasts([(19.1, 72.85), (19.2, 72.95)], timeout_s=2)
    assert [result[0]["rain"] for result in results] == [1, 2]


def test_weather_interpolates_at_arrival_time():
    records = forecast(rain=0, probability=0)
    records[1]["rain"] = records[1]["precipitation"] = 10
    records[1]["precipitation_probability"] = 100
    route = route_leg(duration_min=60)
    points = predictive.route_points(route, [], [])
    forecasts = {(round(p["lat"], 5), round(p["lon"], 5)): records for p in points}
    result = predictive.evaluate_route(route, "scooter", [], [], forecasts, NOW,
                                       reports_available=False, hotspots_available=False)
    assert result["risk_score"] is not None
    assert result["risk_score"] > 0
    assert result["coverage_fraction"] == 1


def test_route_longer_than_one_hour_reports_partial_coverage():
    route = route_leg(duration_min=120)
    points = predictive.route_points(route, [], [])
    forecasts = {(round(p["lat"], 5), round(p["lon"], 5)): forecast(rain=2) for p in points}
    result = predictive.evaluate_route(route, "scooter", [], [], forecasts, NOW)
    assert result["coverage_fraction"] == 0.5
    assert result["covered_points"] < result["total_points"]
    assert "route_horizon_partial" in result["reasons"]


def test_stale_and_conflicting_reports_reduce_weight_and_are_reported():
    spots = [
        {"spotId": "old-no-go", "lat": 19.101, "lon": 72.85, "lastUpdated": NOW - 3 * 3600,
         "verification": "single_report", "confidence": "low",
         "verdicts": {"scooter": "NO_GO"}},
        {"spotId": "old-risky", "lat": 19.101, "lon": 72.85, "lastUpdated": NOW - 3 * 3600,
         "verification": "single_report", "confidence": "low",
         "verdicts": {"scooter": "RISKY"}},
    ]
    points = predictive.route_points(route_leg(), spots, [])
    forecasts = {(round(p["lat"], 5), round(p["lon"], 5)): forecast() for p in points}
    result = predictive.evaluate_route(route_leg(), "scooter", spots, [], forecasts, NOW)
    assert result["stale_reports"] == 2
    assert result["conflicting_report_groups"] == 2
    assert "stale_observations" in result["reasons"]
    assert "conflicting_reports" in result["reasons"]
    fresh = [dict(spot, lastUpdated=NOW, verification="confirmed", confidence="high") for spot in spots]
    fresh_result = predictive.evaluate_route(route_leg(), "scooter", fresh, [], forecasts, NOW)
    assert fresh_result["risk_score"] > result["risk_score"]


def test_report_adapter_preserves_cluster_conflicts_and_official_closures():
    reports = [
        {"reportId": "shallow", "status": "live", "ts": NOW, "lat": 19.101, "lon": 72.85,
         "depth_high": 5, "confidence": "high", "image_quality": "good", "source_type": "photo"},
        {"reportId": "deep", "status": "live", "ts": NOW, "lat": 19.101, "lon": 72.85,
         "depth_high": 30, "confidence": "high", "image_quality": "good", "source_type": "photo"},
        {"reportId": "closure", "status": "live", "ts": NOW, "lat": 19.101, "lon": 72.85,
         "closure": True, "source_type": "official"},
        {"reportId": "old-closure", "status": "live", "ts": NOW - 7 * 3600,
         "lat": 19.101, "lon": 72.85, "closure": True, "source_type": "official"},
        {"reportId": "cleared-closure", "status": "live", "ts": NOW - 3600,
         "lat": 19.101, "lon": 72.85, "closure": True, "source_type": "official",
         "votes": {"cleared": config.CLEARED_VOTES_NEEDED}},
    ]
    active = [{"spotId": "shallow", "reportIds": ["shallow", "deep"],
               "verification": "confirmed", "predicted": False}]
    evidence = predictive.report_evidence(reports, active, NOW)
    by_id = {item["spotId"]: item for item in evidence}
    assert by_id["shallow"]["verdicts"]["scooter"] == "GO"
    assert by_id["deep"]["verdicts"]["scooter"] == "NO_GO"
    assert by_id["closure"]["verdicts"] == {vehicle: "NO_GO" for vehicle in config.VEHICLES}
    assert by_id["closure"]["verification"] == "official"
    assert "old-closure" not in by_id and "cleared-closure" not in by_id


def test_missing_weather_and_observations_are_unknown_not_zero_risk():
    result = predictive.evaluate_route(route_leg(), "scooter", [], [], {}, NOW)
    assert result["risk_score"] is None
    assert result["risk_level"] == "unknown"
    assert "weather_unavailable" in result["reasons"]
    assert "no_route_risk_inputs" in result["reasons"]


def test_open_meteo_timeout_is_an_explicit_provider_error(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(weather_forecast.urllib.request, "urlopen", timeout)
    with pytest.raises(weather_forecast.WeatherProviderError, match="request failed"):
        weather_forecast.fetch_forecasts([(19.1, 72.85)], timeout_s=0.01)


def test_selected_vehicle_keeps_its_own_hard_spot_verdict():
    spot = {"spotId": "underpass", "lon": 72.85 + D / 2, "lat": 19.101,
            "depth_high": 30, "place": "Underpass",
            "verdicts": {v: "GO" for v in routing.ACCESS}}
    spot["verdicts"]["ev_scooter"] = "NO_GO"
    ev = routing.plan(graph(), NODES[0], NODES[2], "ev_scooter", [spot])
    petrol = routing.plan(graph(), NODES[0], NODES[2], "scooter", [spot])
    assert ev["safe"]["distance_m"] == 432
    assert petrol["safe"]["distance_m"] == 210


def _event(body):
    return {"routeKey": "POST /predictive-route", "body": json.dumps(body)}


def test_predictive_handler_scores_departure_alternatives_and_vehicles(monkeypatch):
    from functions.predictive_route import app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setattr(app, "load_graph", lambda _city: graph())
    monkeypatch.setattr(app.db, "active_spots", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app.db, "hotspots", lambda *_args: [])
    monkeypatch.setattr(app.db, "query_bbox", lambda *_args: [])

    def fetch(points, timeout_s):
        assert timeout_s == config.PREDICTIVE_WEATHER_TIMEOUT_S
        return [forecast(rain=8, probability=80) for _ in points]

    monkeypatch.setattr(app.weather_forecast, "fetch_forecasts", fetch)
    response = app.handler(_event({"from": NODES[0], "to": NODES[2], "vehicle": "scooter",
                                   "city": "mumbai"}), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["risk_model"]["is_probability"] is False
    assert {option["vehicle"] for option in body["vehicle_options"]} == set(config.VEHICLES)
    assert [item["offset_min"] for item in body["departure_alternatives"]] == [0, 15, 30, 45, 60]
    assert body["departure_alternatives"][0]["risk_score"] > body["departure_alternatives"][-1]["risk_score"]
    assert body["preferred_departure_at"] == body["departure_alternatives"][-1]["departure_at"]


def test_predictive_vehicle_options_apply_selected_vehicle_verdicts(monkeypatch):
    from functions.predictive_route import app

    spot = {"spotId": "underpass", "lon": 72.85 + D / 2, "lat": 19.101,
            "depth_high": 30, "place": "Underpass",
            "verdicts": {candidate: "GO" for candidate in config.VEHICLES}}
    spot["verdicts"]["scooter"] = "NO_GO"
    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setattr(app, "load_graph", lambda _city: graph())
    monkeypatch.setattr(app.db, "active_spots", lambda *_args, **_kwargs: [spot])
    monkeypatch.setattr(app.db, "hotspots", lambda *_args: [])
    monkeypatch.setattr(app.db, "query_bbox", lambda *_args: [])
    monkeypatch.setattr(app.weather_forecast, "fetch_forecasts",
                        lambda points, **_kwargs: [forecast() for _ in points])
    response = app.handler(_event({"from": NODES[0], "to": NODES[2], "vehicle": "scooter",
                                   "city": "mumbai"}), None)
    options = json.loads(response["body"])["vehicle_options"]
    by_vehicle = {option["vehicle"]: option for option in options}
    assert by_vehicle["scooter"]["route"]["distance_m"] == 432
    assert by_vehicle["ev_scooter"]["route"]["distance_m"] == 210


def test_provider_failure_is_reported_without_claiming_low_risk(monkeypatch):
    from functions.predictive_route import app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setattr(app, "load_graph", lambda _city: graph())
    monkeypatch.setattr(app.db, "active_spots", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app.db, "hotspots", lambda *_args: [])
    monkeypatch.setattr(app.db, "query_bbox", lambda *_args: [])

    def unavailable(*_args, **_kwargs):
        raise weather_forecast.WeatherProviderError("offline")

    monkeypatch.setattr(app.weather_forecast, "fetch_forecasts", unavailable)
    response = app.handler(_event({"from": NODES[0], "to": NODES[2], "vehicle": "scooter",
                                   "city": "mumbai"}), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["data_quality"]["weather"] == "unavailable"
    selected = next(item for item in body["vehicle_options"] if item["vehicle"] == "scooter")
    assert selected["risk_score"] is None
    assert selected["risk_level"] == "unknown"
    assert "weather_unavailable" in selected["reasons"]


@pytest.mark.parametrize("failed_source", ["reports", "hotspots"])
def test_flood_data_failure_returns_degraded_prediction(monkeypatch, failed_source):
    from functions.predictive_route import app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setattr(app, "load_graph", lambda _city: graph())
    monkeypatch.setattr(app.db, "active_spots", lambda *_args, **_kwargs: [])

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(app.db, "hotspots",
                        unavailable if failed_source == "hotspots" else lambda *_args: [])
    monkeypatch.setattr(app.db, "query_bbox",
                        unavailable if failed_source == "reports" else lambda *_args: [])
    monkeypatch.setattr(app.weather_forecast, "fetch_forecasts",
                        lambda points, **_kwargs: [forecast(rain=2) for _ in points])

    response = app.handler(_event({"from": NODES[0], "to": NODES[2], "vehicle": "scooter",
                                   "city": "mumbai"}), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["data_quality"][f"{failed_source}_available"] is False
    selected = next(item for item in body["vehicle_options"] if item["vehicle"] == "scooter")
    assert f"{failed_source}_unavailable" in selected["reasons"]
    assert body["recommended_vehicle"] is None
    assert body["departure_alternatives"]


def test_official_closures_are_hard_vehicle_constraints(monkeypatch):
    from functions.predictive_route import app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setattr(app, "load_graph", lambda _city: graph())
    monkeypatch.setattr(app.db, "active_spots", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app.db, "hotspots", lambda *_args: [])
    closures = []
    for report_id, lon, lat in [
        ("top-closure", 72.85 + D / 2, 19.101),
        ("bottom-closure", 72.85 + D / 2, 19.100),
    ]:
        closures.append({"reportId": report_id, "status": "live", "closure": True,
                         "source_type": "official", "lon": lon, "lat": lat, "ts": NOW,
                         "depth_high": None})
    monkeypatch.setattr(app.db, "query_bbox", lambda *_args: closures)
    response = app.handler(_event({"from": NODES[0], "to": NODES[2], "vehicle": "scooter",
                                   "city": "mumbai"}), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    selected = next(item for item in body["vehicle_options"] if item["vehicle"] == "scooter")
    assert not selected["feasible"]
    assert "route_blocked" in selected["reasons"]
    assert selected["risk_score"] is None


def test_predictive_endpoint_is_disabled_by_default(monkeypatch):
    from functions.route import app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", False)
    response = app.handler({"routeKey": "POST /predictive-route", "body": "{}"}, None)
    assert response["statusCode"] == 404


def test_route_handler_dispatches_enabled_predictive_endpoint(monkeypatch):
    from functions.predictive_route import app as predictive_app
    from functions.route import app as route_app

    monkeypatch.setattr(config, "PREDICTIVE_ROUTE_ENABLED", True)
    monkeypatch.setattr(predictive_app, "handler", lambda event, _ctx: {
        "statusCode": 200, "body": event["routeKey"],
    })
    response = route_app.handler({"routeKey": "POST /predictive-route", "body": "{}"}, None)
    assert response == {"statusCode": 200, "body": "POST /predictive-route"}
