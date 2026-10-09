"""Local mock of the HTTP API for frontend development, no AWS needed.

Uses the REAL rules, spot merging, predicted-spot and routing code on the real graphs
(data/graphs/<city>.json.gz), with in-memory reports. What is real-time here:
  * rain: live Open-Meteo rainfall at every cited hotspot (refreshed every 10 min)
  * --social: live Google News / Bluesky / Mastodon posts every 10 min (heuristic extraction:
    only posts naming a known hotspot become pins; production uses Bedrock + Amazon Location)
  * --storm: pretend it is pouring at every hotspot (to see predicted spots when it is dry)
Photo analysis returns a canned MOCK result unless --bedrock (real Bedrock with your AWS creds).

  python scripts/local_api.py [--social] [--storm] [--bedrock]      # http://localhost:8787
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
from common import bus, config, depth, pipeline, routing, social, spots  # noqa: E402
from functions.risk_scheduler.app import fetch_rain, risk_of  # noqa: E402

REPORTS: dict[str, dict] = {}
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
        if ARGS.storm:
            rain = [{"past3h": 32.0, "now": 12.0, "next3h": 20.0} for _ in rain]
        for h, r in zip(hs, rain):
            h.update({"rainPast3h": r["past3h"], "rainNow": r["now"], "rainNext3h": r["next3h"],
                      "risk": risk_of(r), "riskUpdatedAt": int(time.time())})
        c = rain[-1]
        WEATHER[city] = {"rainNow": c["now"], "rainPast3h": c["past3h"], "rainNext3h": c["next3h"],
                         "maxRainNowAtHotspots": max([r["now"] for r in rain] + [0]),
                         "hotspotsAtRisk": sum(1 for h in hs if h["risk"] != "normal"), "updatedAt": int(time.time()),
                         "source": "Open-Meteo forecast API" + (" (SIMULATED STORM)" if ARGS.storm else "")}
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


def seed_synthetic(city, n=12):
    g = graph(city)
    if not g:
        return
    rnd = random.Random(city)
    roads = [i for i, e in enumerate(g.edges) if e[3] in (1, 2) and e[2] > 60]
    start = int(datetime.fromisoformat("2025-07-26T18:00:00+05:30").timestamp())
    pts = [(h["name"], h["lon"], h["lat"], 45 if h["kind"] == "underpass" else 25) for h in HOTSPOTS.get(city, [])[:3]]
    for i in range(n):
        c = g.geometry(rnd.choice(roads))
        lon, lat = c[len(c) // 2]
        pts.append((f"Synthetic point {i + 1}", lon, lat, rnd.choice([8, 14, 18, 25, 30, 35, 45, 60])))
    for i, (name, lon, lat, hi) in enumerate(pts):
        a = depth.normalise({**MOCK, "depth_cm_low": max(hi - 10, 0), "depth_cm_high": hi, "hazards": [],
                             "reasoning": f"SYNTHETIC test point ({hi} cm). Not a real report.",
                             "reasoning_hi": "परीक्षण बिंदु। असली रिपोर्ट नहीं।"})
        rid = f"synth-{city}-{i:03d}"
        REPORTS[rid] = {"reportId": rid, "city": city, "mode": "demo", "lat": lat, "lon": lon, "place": name,
                        "ts": start + i * 12 * 60, "createdAt": start + i * 12 * 60, "source_type": "photo",
                        "source_label": "synthetic", "votes": {}, **pipeline.fields_from_assessment(a)}


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
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, b"")

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s\n" % (fmt % a))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        city = q.get("city", "delhi")
        if u.path == "/spots":
            now = float(q.get("at") or time.time())
            return self._send(200, {"spots": city_spots(city, q.get("mode", "live"), now), "now": now})
        if u.path == "/hotspots":
            return self._send(200, {"hotspots": HOTSPOTS.get(city, []), "weather": WEATHER.get(city)})
        if u.path == "/bus-impact":
            now = float(q.get("at") or time.time())
            routes = bus_routes(city)
            return self._send(200, {"routes_known": len(routes), "affected": bus.impact(routes, city_spots(city, q.get("mode", "live"), now))})
        if u.path == "/demo/timeline":
            rs = sorted((r for r in REPORTS.values() if r["mode"] == "demo" and r["city"] == city), key=lambda r: r["ts"])
            return self._send(200, {"start": rs[0]["ts"] if rs else None, "end": rs[-1]["ts"] if rs else None,
                                    "reports": [public(r) for r in rs]})
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
                fields = pipeline.fields_from_assessment(depth.normalise(MOCK))
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
            sp = city_spots(city, b.get("mode", "live"), now)
            res = routing.plan(g, b["from"], b["to"], b["vehicle"], sp)
            if b.get("compare"):
                res["compare"] = routing.compare(g, b["from"], b["to"], sp)
            if max(res["snap_m"]) > 500:
                res["note"] = "One of your points is outside the routable demo area. " + res["note"]
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
    ap.add_argument("--storm", action="store_true", help="simulate heavy rain at every hotspot")
    ARGS = ap.parse_args()
    for c in config.CITIES:
        HOTSPOTS[c] = load_hotspots(c)
        seed_synthetic(c)
    threading.Thread(target=background, daemon=True).start()
    print(f"Local API on http://localhost:{ARGS.port}  ({len(REPORTS)} synthetic demo reports, live rain"
          f"{', live social' if ARGS.social else ''}{', SIMULATED STORM' if ARGS.storm else ''})")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
