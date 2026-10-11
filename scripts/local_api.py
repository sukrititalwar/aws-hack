"""Local mock of the HTTP API for frontend development, no AWS needed.

Uses the REAL rules, spot merging, predicted-spot and routing code on the real graphs
(data/graphs/<city>.json.gz), with in-memory reports. What is real-time here:
  * rain: live Open-Meteo rainfall at every cited hotspot (refreshed every 10 min)
  * --social: live Google News / Bluesky / Mastodon posts every 10 min (heuristic extraction:
    only posts naming a known hotspot become pins; production uses Bedrock + Amazon Location)
Photo analysis returns a canned MOCK result unless --bedrock (real Bedrock with your AWS creds).

  python scripts/local_api.py [--social] [--bedrock]      # http://localhost:8787
  (also serves POST /predictive-route; set VITE_PREDICTIVE_ROUTE_ENABLED=true in frontend/.env.local to see it)
"""
import argparse
import gzip
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from common import bus, config, db, depth, drains, pipeline, routing, simulation, social, spots  # noqa: E402
from functions.insights import app as insights  # noqa: E402
from functions.predictive_route import app as predictive_route  # noqa: E402
from functions.route import app as route_app  # noqa: E402
from functions.risk_scheduler.app import fetch_rain, risk_of  # noqa: E402

REPORTS: dict[str, dict] = {}
DRAINS: dict[str, dict] = {}          # DrainReady, in memory; dispatcher access code is "demo"
DRAIN_AFTER_CLEAR = {"on": True}
PLACES: dict[str, list[dict]] = {}     # saved addresses per mock user (email); dev mode only
PHOTOS: dict[str, bytes] = {}
HOTSPOTS: dict[str, list] = {}
WEATHER: dict[str, dict] = {}
GRAPHS: dict = {}
BUS: dict = {}
ARGS = None
LOCK = threading.Lock()

MOCK = {"is_flooded_road_photo": True, "depth_cm_low": 18, "depth_cm_high": 28, "confidence": "medium",
        "reference_objects": [{"object": "kerb", "observation": "fully under water", "implied_depth_cm": 20},
                              {"object": "car tyre", "observation": "lower half covered", "implied_depth_cm": 28}],
        "reasoning": "LOCAL MOCK: water covers the kerb and the lower half of a car tyre, so roughly 18-28 cm.",
        "reasoning_hi": "लोकल मॉक: पानी फ़ुटपाथ के ऊपर और कार के आधे टायर तक है, लगभग 18-28 सेमी।",
        "flowing_water": False, "hazards": ["open_drain_or_manhole_risk"], "location_type": "underpass",
        "image_quality": "good"}


def graph(city):
    if city not in GRAPHS:
        p = os.path.join(ROOT, "data", "graphs", f"{city}.json.gz")
        GRAPHS[city] = routing.Graph(json.loads(gzip.decompress(open(p, "rb").read()))) if os.path.exists(p) else None
    return GRAPHS[city]


def bus_routes(city):
    if city not in BUS:
        p = os.path.join(ROOT, "data", f"bus_routes_{city}.json")
        BUS[city] = bus.index(json.load(open(p))["routes"]) if os.path.exists(p) else []
    return BUS[city]


def load_hotspots(city):
    p = os.path.join(ROOT, "data", f"hotspots_{city}.geojson")
    if not os.path.exists(p):
        return []
    return [{**f["properties"], "city": city, "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
             "risk": "normal"} for f in json.load(open(p, encoding="utf-8"))["features"]]


def refresh_rain():
    """Live rainfall at every hotspot + city centre (same code as the risk_scheduler Lambda)."""
    for city, cfg in config.CITIES.items():
        hs = HOTSPOTS.setdefault(city, load_hotspots(city))
        try:
            rain = fetch_rain([(h["lat"], h["lon"]) for h in hs] + [(cfg["center"][1], cfg["center"][0])])
        except Exception as e:
            print("  rain fetch failed", city, e)
            continue
        for h, r in zip(hs, rain):
            h.update({"rainPast3h": r["past3h"], "rainNow": r["now"], "rainNext3h": r["next3h"],
                      "risk": risk_of(r), "riskUpdatedAt": int(time.time())})
        c = rain[-1]
        WEATHER[city] = {"rainNow": c["now"], "rainPast3h": c["past3h"], "rainNext3h": c["next3h"],
                         "maxRainNowAtHotspots": max([r["now"] for r in rain] + [0]),
                         "hotspotsAtRisk": sum(1 for h in hs if h["risk"] != "normal"), "updatedAt": int(time.time()),
                         "source": "Open-Meteo forecast API"}
    print("  rain refreshed:", {c: round(w["rainPast3h"], 1) for c, w in WEATHER.items()})


def refresh_social():
    for city in config.CITIES:
        hs = HOTSPOTS.get(city, [])
        try:
            posts, stats = social.fetch_all(city, hours=24)
        except Exception as e:
            print("  social failed", city, e)
            continue
        cands = social.prefilter(posts, city, hs, max_age_h=6)
        n = 0
        for p in cands:
            ext = social.heuristic_extract(p, city, hs)
            h = social.match_hotspot(p["text"], hs)
            if not (ext["is_waterlogging_report"] and h):
                continue
            r = social.to_report(p, ext, (h["lon"], h["lat"], h["name"], "hotspot"), city)
            with LOCK:
                REPORTS.setdefault(r["reportId"], r)
            n += 1
        print(f"  social {city}: {stats} -> {len(cands)} candidates, {n} pinned")


def background():
    while True:
        refresh_rain()
        if ARGS.social:
            refresh_social()
        time.sleep(600)


def drain_hotspots(city):
    return HOTSPOTS.get(city, [])


def spots_for(city, mode, now):
    return simulation.spots_at(now) if mode == "sim" and city == simulation.CITY else city_spots(city, "live", now)


def city_spots(city, mode, now, predicted=True):
    with LOCK:
        rs = [r for r in REPORTS.values() if r["city"] == city and r["mode"] == mode and r.get("status") == "live"]
    real = spots.build_spots(rs, now)
    return real + (spots.predicted_spots(HOTSPOTS.get(city, []), real, now) if mode == "live" and predicted else [])


def public(r):
    out = {k: v for k, v in r.items() if k not in ("model_json", "extraction", "cell", "cityMode")}
    if r["reportId"] in PHOTOS:
        out["photoUrl"] = f"http://localhost:{ARGS.port}/photo/{r['reportId']}"
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type,x-admin-token,authorization")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _mock_user(self):
        """Dev-only auth: 'Authorization: Bearer mock:<email>' (VITE_AUTH_MODE=mock). The real API uses Cognito."""
        a = self.headers.get("Authorization", "")
        return a[len("Bearer mock:"):] if a.startswith("Bearer mock:") and len(a) > 12 else None

    def _me(self, method, path, raw):
        user = self._mock_user()
        if not user:
            return self._send(401, {"message": "Unauthorized"})
        if path == "/me" and method == "GET":
            return self._send(200, {"sub": user, "email": user, "groups": []})
        if path == "/me/places" and method == "GET":
            return self._send(200, {"places": PLACES.get(user, [])})
        if path == "/me/places" and method == "POST":
            b = json.loads(raw)
            if not (1 <= len(str(b.get("label") or "").strip()) <= 40) or b.get("kind") not in ("home", "work", "other"):
                return self._send(400, {"error": "Give the place a short name (1 to 40 characters)."})
            mine = PLACES.setdefault(user, [])
            replaced = [p["placeId"] for p in mine if b["kind"] in ("home", "work") and p["kind"] == b["kind"]]
            mine[:] = [p for p in mine if p["placeId"] not in replaced]
            if len(mine) >= 20:
                return self._send(409, {"error": "You can save up to 20 places. Delete one first."})
            place = {"placeId": uuid.uuid4().hex[:12], "label": b["label"][:40], "kind": b["kind"], "address": b.get("address"),
                     "lat": float(b["lat"]), "lon": float(b["lon"]), "city": b.get("city"), "createdAt": int(time.time())}
            mine.append(place)
            mine.sort(key=lambda p: (["home", "work", "other"].index(p["kind"]), p["createdAt"]))
            return self._send(200, {"place": place, "replaced": replaced})
        m = re.fullmatch(r"/me/places/([\w-]+)", path)
        if m and method == "DELETE":
            PLACES[user] = [p for p in PLACES.get(user, []) if p["placeId"] != m.group(1)]
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):
        self._me("DELETE", urlparse(self.path).path, b"")

    def do_OPTIONS(self):
        self._send(204, b"")

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s\n" % (fmt % a))

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/me"):
            return self._me("GET", u.path, b"")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/rain/india", "/rain/india/posts", "/simulation"):      # same handler the Lambda runs
            r = insights.handler({"routeKey": f"GET {u.path}", "queryStringParameters": q}, None)
            return self._send(r["statusCode"], r["body"].encode())
        city = q.get("city", "delhi")
        if u.path == "/spots":
            now = float(q.get("at") or time.time())
            return self._send(200, {"spots": spots_for(city, q.get("mode", "live"), now), "now": now})
        if u.path == "/hotspots":
            return self._send(200, {"hotspots": HOTSPOTS.get(city, []), "weather": WEATHER.get(city)})
        if u.path == "/bus-impact":
            now = float(q.get("at") or time.time())
            routes = bus_routes(city)
            return self._send(200, {"routes_known": len(routes), "affected": bus.impact(routes, spots_for(city, q.get("mode", "live"), now))})
        if u.path == "/drains":
            rows = drains.build_groups([r for r in DRAINS.values() if r["city"] == city], drain_hotspots(city))
            if q.get("status") != "all":
                rows = [r for r in rows if r["status"] != "cleared"]
            return self._send(200, {"drains": rows, "now": int(time.time())})
        if u.path == "/drains/metrics":
            return self._send(200, drains.metrics([r for r in DRAINS.values() if r["city"] == city], time.time()))
        m = re.fullmatch(r"/drains/([\w-]+)", u.path)
        if m and m.group(1) in DRAINS:
            head = DRAINS[m.group(1)]
            ms = [r for r in DRAINS.values() if (r.get("groupId") or r["reportId"]) == (head.get("groupId") or head["reportId"])]
            rows = drains.build_groups(ms, drain_hotspots(head["city"]))
            out = {"status": head["status"], "rejection_reason": head.get("rejection_reason"), **(rows[0] if rows else {}),
                   "reasoning": head.get("reasoning"), "reasoning_hi": head.get("reasoning_hi"),
                   "afterNote": head.get("afterNote"), "clearanceVerified": head.get("clearanceVerified", False)}
            if head["reportId"] in PHOTOS:
                out["photoUrl"] = f"http://localhost:{ARGS.port}/photo/{head['reportId']}"
            if head["reportId"] + "-after" in PHOTOS:
                out["afterUrl"] = f"http://localhost:{ARGS.port}/photo/{head['reportId']}-after"
            return self._send(200, out)
        m = re.fullmatch(r"/reports/([\w-]+)", u.path)
        if m and m.group(1) in REPORTS:
            return self._send(200, public(REPORTS[m.group(1)]))
        m = re.fullmatch(r"/photo/([\w-]+)", u.path)
        if m and m.group(1) in PHOTOS:
            return self._send(200, PHOTOS[m.group(1)], "image/jpeg")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if u.path.startswith("/me"):
            return self._me("POST", u.path, raw)
        if u.path == "/predictive-route":      # the same Lambda handler, with DynamoDB swapped for the in-memory data
            b = json.loads(raw)
            city = str(b.get("city") or "delhi").lower()
            g = graph(city)
            if g:
                route_app._GRAPHS[city] = g
            with LOCK:
                reports = [dict(r) for r in REPORTS.values() if r["city"] == city and r["mode"] == "live"]
            db.query_bbox = lambda c, mode, bbox, t0, t1: [r for r in reports if bbox[0] <= r["lon"] <= bbox[2] and bbox[1] <= r["lat"] <= bbox[3]]
            db.hotspots = lambda c: HOTSPOTS.get(c, [])
            db.active_spots = lambda c, mode, bbox, now=None, predicted=True, report_items=None, hotspot_items=None: city_spots(c, mode, now or time.time(), predicted)
            r = predictive_route.handler({"routeKey": "POST /predictive-route", "body": json.dumps(b)}, None)
            return self._send(r["statusCode"], r["body"].encode())
        if u.path == "/drains/upload-url":
            b = json.loads(raw)
            rid = uuid.uuid4().hex[:16]
            DRAINS[rid] = {"reportId": rid, "city": b.get("city", "delhi"), "lat": b["lat"], "lon": b["lon"], "ts": int(time.time()),
                           "status": "analysing", "note": b.get("note"), "deviceHash": b["deviceId"][:16]}
            return self._send(200, {"reportId": rid, "uploadUrl": f"http://localhost:{ARGS.port}/upload-drain/{rid}", "fields": {}})
        m = re.fullmatch(r"/upload-drain/([\w-]+)", u.path)
        if m:
            rid = m.group(1)
            s_, e_ = raw.find(b"\xff\xd8"), raw.rfind(b"\xff\xd9")
            PHOTOS[rid] = raw[s_:e_ + 2]
            r = DRAINS[rid]
            time.sleep(1.2)
            if ARGS.bedrock_down:   # same labelled fallback the Lambda uses when Bedrock cannot answer
                from common import fallback
                r.update({"status": "open", "rainNext24h": 22.0,
                          **{k: v for k, v in fallback.rate_report([("Trash", 93.0), ("Drain", 88.0)],
                                                                   "AccessDeniedException: Operation not allowed").items()
                             if k not in ("is_drain_photo",)}})
            else:
                r.update({"status": "open", "severity": "blocked", "blockage_type": "garbage", "confidence": "medium", "standing_water": True,
                          "reasoning": "LOCAL MOCK: grating covered by plastic bags and silt, so water cannot enter.",
                          "reasoning_hi": "लोकल मॉक: जाली प्लास्टिक और गाद से ढकी है।", "rainNext24h": 22.0})
            r["groupId"] = drains.find_group(r, list(DRAINS.values())) or rid
            return self._send(204, b"")
        m = re.fullmatch(r"/drains/([\w-]+)/retry", u.path)
        if m:
            r = DRAINS.get(m.group(1))
            if not r or r["status"] not in ("error", "analysing"):
                return self._send(409, {"error": "This report is not stuck, so there is nothing to retry."})
            r["status"] = "open"
            return self._send(200, {"ok": True, "status": "analysing"})
        m = re.fullmatch(r"/drains/([\w-]+)/(assign|after-url|confirm)", u.path)
        if m:
            if self.headers.get("x-admin-token") != "demo":
                return self._send(403, {"error": "Dispatcher access only. (local access code: demo)"})
            gid, action = m.groups()
            members = [r for r in DRAINS.values() if (r.get("groupId") or r["reportId"]) == gid]
            if action == "confirm":
                body = json.loads(raw)
                if not any(r.get("afterKey") for r in members):
                    return self._send(409, {"error": "There is no after-photo to confirm yet."})
                for r in members:
                    if body.get("decision") == "clear":
                        r.update({"status": "cleared", "clearedAt": int(time.time()), "clearanceVerified": False, "awaitingReview": False,
                                  "afterNote": "Confirmed clear by a dispatcher from the after-photo (manual, not AI-verified)."})
                    else:
                        r.update({"awaitingReview": False, "afterRejected": True,
                                  "afterNote": "A dispatcher rejected the after-photo. Send another photo."})
                return self._send(200, {"ok": True})
            if action == "assign":
                for r in members:
                    r.update({"status": "assigned", "assignedTo": json.loads(raw)["worker"], "assignedAt": int(time.time())})
                return self._send(200, {"ok": True})
            return self._send(200, {"uploadUrl": f"http://localhost:{ARGS.port}/upload-after/{gid}", "fields": {}})
        m = re.fullmatch(r"/upload-after/([\w-]+)", u.path)
        if m:
            gid = m.group(1)
            s_, e_ = raw.find(b"\xff\xd8"), raw.rfind(b"\xff\xd9")
            PHOTOS[gid + "-after"] = raw[s_:e_ + 2]
            for r in DRAINS.values():
                if (r.get("groupId") or r["reportId"]) == gid:
                    if ARGS.bedrock_down:   # never auto-clear without AI verification: wait for a dispatcher
                        r.update({"afterKey": "x", "awaitingReview": True,
                                  "afterNote": "Automatic verification is unavailable, so a dispatcher must confirm this clearance from the photos."})
                    else:
                        r.update({"status": "cleared", "clearedAt": int(time.time()), "clearanceVerified": True, "afterKey": "x"})
            return self._send(204, b"")
        if u.path == "/reports/upload-url":
            b = json.loads(raw)
            rid = uuid.uuid4().hex[:16]
            REPORTS[rid] = {"reportId": rid, "city": b.get("city", "delhi"), "mode": "live", "lat": b["lat"], "lon": b["lon"],
                            "place": b.get("place"), "ts": int(time.time()), "createdAt": int(time.time()),
                            "status": "analysing", "votes": {}, "source_type": "photo"}
            return self._send(200, {"reportId": rid, "uploadUrl": f"http://localhost:{ARGS.port}/upload/{rid}",
                                    "fields": {"key": f"uploads/{rid}.jpg", "Content-Type": "image/jpeg"}})
        m = re.fullmatch(r"/upload/([\w-]+)", u.path)
        if m:
            rid = m.group(1)
            s, e = raw.find(b"\xff\xd8"), raw.rfind(b"\xff\xd9")
            img = raw[s:e + 2]
            PHOTOS[rid] = img
            r = REPORTS[rid]
            if ARGS.bedrock:
                fields, _ = pipeline.assess(img, r["city"], r.get("place"))
            else:
                time.sleep(1.5)
                m = dict(MOCK)
                if ARGS.unsure:  # an unclear photo: no reference object, low confidence
                    m.update({"confidence": "low", "reference_objects": [], "depth_cm_low": 0, "depth_cm_high": 12,
                              "reasoning": "LOCAL MOCK: I cannot see a kerb, tyre or person, so the depth is a guess.",
                              "hazards": []})
                fields = pipeline.fields_from_assessment(depth.normalise(m))
            r.update(fields)
            return self._send(204, b"")
        m = re.fullmatch(r"/reports/([\w-]+)/vote", u.path)
        if m:
            b = json.loads(raw)
            key = {"still_flooded": "still", "cleared": "cleared", "wrong": "wrong"}[b["type"]]
            v = REPORTS[m.group(1)].setdefault("votes", {})
            v[key] = v.get(key, 0) + 1
            return self._send(200, {"votes": v})
        if u.path == "/route":
            b = json.loads(raw)
            city = b.get("city", "delhi")
            g = graph(city)
            if not g:
                return self._send(503, {"error": f"No routing graph for {city}. Run scripts/build_graph.py --city {city}"})
            now = float(b.get("at") or time.time())
            sp = spots_for(city, b.get("mode", "live"), now)
            res = routing.plan(g, b["from"], b["to"], b["vehicle"], sp)
            if b.get("compare"):
                res["compare"] = routing.compare(g, b["from"], b["to"], sp)
            res["coverage"] = g.areas
            res["checked_at"] = int(now)
            res["spots_considered"] = len(sp)
            return self._send(200, res)
        if u.path == "/subscriptions":
            return self._send(200, {"subId": "local", "note": "LOCAL MOCK: no alert will be sent."})
        self._send(404, {"error": "not found"})


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bedrock", action="store_true", help="use real Bedrock for uploaded photos")
    ap.add_argument("--social", action="store_true", help="poll live social/news feeds every 10 min")
    ap.add_argument("--bedrock-down", action="store_true", help="simulate Bedrock being unavailable: drains use the labelled fallback")
    ap.add_argument("--unsure", action="store_true", help="mock photo analysis returns an unclear, low-confidence result")
    ARGS = ap.parse_args()
    for c in config.CITIES:
        HOTSPOTS[c] = load_hotspots(c)
    threading.Thread(target=background, daemon=True).start()
    print(f"Local API on http://localhost:{ARGS.port}  (live rain"
          f"{', live social' if ARGS.social else ''})")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
