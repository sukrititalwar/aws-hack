"""POST /route  {from:[lon,lat], to:[lon,lat], vehicle, city?, compare?: bool}
    -> normal + flood-safe route for the vehicle, and (compare) the same trip for scooter, auto,
       car, SUV and bus: who can still take the usual road, who must detour, who is stuck.
GET /bus-impact?city=..&mode=..&at=..
    -> bus routes passing a spot that is risky/no-go for buses (or no-go on foot near stops).

Street graph (scripts/build_graph.py) and bus lines are loaded from S3 once per container.
"""
import gzip
import json
import logging
import os
import time

from common import bus, config, db, geo, http, routing, simulation, views

log = logging.getLogger()
_GRAPHS: dict = {}
BBOX_MARGIN_DEG = 0.01  # ~1 km around the from/to box when fetching spots


def load_graph(city: str) -> routing.Graph:
    if city not in _GRAPHS:
        t0 = time.time()
        local = os.environ.get("GRAPH_PATH")  # for sam local / tests
        if local:
            with open(local, "rb") as f:
                raw = f.read()
        else:
            raw = views.s3().get_object(Bucket=config.DATA_BUCKET, Key=f"graphs/{city}.json.gz")["Body"].read()
        data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
        _GRAPHS[city] = routing.Graph(data)
        log.info("loaded graph %s: %d nodes, %d edges in %.1fs",
                 city, len(data["nodes"]), len(data["edges"]), time.time() - t0)
    return _GRAPHS[city]


_BUS: dict = {}


def load_bus(city: str) -> list[dict]:
    if city not in _BUS:
        try:
            raw = views.s3().get_object(Bucket=config.DATA_BUCKET, Key=f"bus/{city}.json")["Body"].read()
            _BUS[city] = bus.index(json.loads(raw)["routes"])
        except Exception:
            log.warning("no bus routes for %s", city)
            _BUS[city] = []
    return _BUS[city]


def bus_impact(event):
    q = http.qs(event)
    city = (q.get("city") or "delhi").lower()
    mode = q.get("mode") or "live"
    if city not in config.CITIES or mode not in ("live", "sim"):
        return http.bad("bad city or mode")
    if mode == "sim" and city != simulation.CITY:
        return http.bad("The simulation covers Delhi only.")
    now = float(q.get("at") or time.time())
    routes = load_bus(city)
    spots = simulation.spots_at(now) if mode == "sim" else db.active_spots(city, mode, config.CITIES[city]["bbox"], now)
    return http.resp(200, {"routes_known": len(routes), "affected": bus.impact(routes, spots), "now": now})


def handler(event, _ctx):
    if event.get("routeKey") == "POST /predictive-route":
        if not config.PREDICTIVE_ROUTE_ENABLED:
            return http.bad("Predictive routing is not enabled.", 404)
        from functions.predictive_route.app import handler as predictive_handler
        return predictive_handler(event, _ctx)
    if event.get("routeKey") == "GET /bus-impact":
        return bus_impact(event)
    try:
        b = http.body(event)
    except ValueError as e:
        return http.bad(str(e))
    frm, to = b.get("from"), b.get("to")
    vehicle = b.get("vehicle")
    city = str(b.get("city") or "delhi").lower()
    mode = b.get("mode") or "live"
    if not (isinstance(frm, list) and isinstance(to, list) and len(frm) == 2 and len(to) == 2
            and geo.valid_lonlat(*frm) and geo.valid_lonlat(*to)):
        return http.bad("from/to must be [lon, lat]")
    if vehicle not in config.VEHICLES:
        return http.bad(f"vehicle must be one of {config.VEHICLES}")
    if city not in config.CITIES or mode not in ("live", "sim"):
        return http.bad("bad city or mode")
    if mode == "sim" and city != simulation.CITY:
        return http.bad("The simulation covers Delhi only.")
    frm, to = [float(x) for x in frm], [float(x) for x in to]
    # A point in another city (e.g. "my location" while away) would make the flood-spot lookup span
    # hundreds of km; say so plainly instead of failing.
    w, s, e, n = config.CITIES[city]["bbox"]
    if not all(w <= p[0] <= e and s <= p[1] <= n for p in (frm, to)):
        return http.bad(f"Both points must be inside {config.CITIES[city]['label']}: we only have road and flood data there.")

    try:
        graph = load_graph(city)
    except Exception:
        log.exception("graph load failed")
        return http.bad("Routing is not available for this city yet.", 503)

    bbox = [min(frm[0], to[0]) - BBOX_MARGIN_DEG, min(frm[1], to[1]) - BBOX_MARGIN_DEG,
            max(frm[0], to[0]) + BBOX_MARGIN_DEG, max(frm[1], to[1]) + BBOX_MARGIN_DEG]
    now = float(b.get("at") or time.time())
    spots = simulation.spots_at(now) if mode == "sim" else db.active_spots(city, mode, bbox, now)

    t0 = time.time()
    try:
        result = routing.plan(graph, frm, to, vehicle, spots)
    except ValueError as e:
        return http.bad(str(e))
    if b.get("compare"):
        result["compare"] = routing.compare(graph, frm, to, spots)
    result["compute_ms"] = int((time.time() - t0) * 1000)
    result["spots_considered"] = len(spots)
    # Coverage is reported separately from the flood verdict, with the areas we do cover.
    result["coverage"] = graph.areas
    result["checked_at"] = int(now)
    return http.resp(200, result)
