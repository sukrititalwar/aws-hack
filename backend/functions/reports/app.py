"""Read API for the map.

GET /reports/{id}                       poll a single report
GET /reports?bbox=..&city=..&since=..   individual reports in the viewport
GET /spots?bbox=..&city=..&mode=live|demo&at=<epoch>   merged spots (demo replays at `at`)
GET /demo/timeline?city=..              all archived demo reports with replay times
"""
import time

from common import config, db, geo, http, views


def _city(q):
    city = (q.get("city") or "delhi").lower()
    if city not in config.CITIES:
        raise ValueError("unsupported city")
    return city


def _mode(q):
    mode = q.get("mode") or "live"
    if mode not in ("live", "demo"):
        raise ValueError("mode must be live or demo")
    return mode


def _bbox(q, city):
    return geo.parse_bbox(q["bbox"]) if q.get("bbox") else config.CITIES[city]["bbox"]


def get_one(event):
    rid = http.path_param(event, "id")
    item = db.get_report(rid) if rid else None
    if not item:
        return http.bad("report not found", 404)
    return http.resp(200, views.public_report(item))


def list_reports(q):
    city, mode = _city(q), _mode(q)
    now = float(q.get("at") or time.time())
    since = float(q.get("since") or now - config.EXPIRE_AFTER_H * 3600)
    items = db.query_bbox(city, mode, _bbox(q, city), since, now)
    items = [i for i in items if i.get("status") == "live"]
    return http.resp(200, {"reports": [views.public_report(i) for i in items], "now": now})


def list_spots(q):
    city, mode = _city(q), _mode(q)
    now = float(q.get("at") or time.time())
    return http.resp(200, {"spots": db.active_spots(city, mode, _bbox(q, city), now), "now": now})


def timeline(q):
    city = _city(q)
    items = sorted((i for i in db.query_city(city, "demo") if i.get("status") == "live"),
                   key=lambda i: i["ts"])
    reports = [views.public_report(i) for i in items]
    return http.resp(200, {
        "city": city,
        "start": items[0]["ts"] if items else None,
        "end": items[-1]["ts"] if items else None,
        "reports": reports,
    })


def handler(event, _ctx):
    route = event.get("routeKey", "")
    q = http.qs(event)
    try:
        if route == "GET /reports/{id}":
            return get_one(event)
        if route == "GET /reports":
            return list_reports(q)
        if route == "GET /spots":
            return list_spots(q)
        if route == "GET /demo/timeline":
            return timeline(q)
    except ValueError as e:
        return http.bad(str(e))
    return http.bad("not found", 404)
