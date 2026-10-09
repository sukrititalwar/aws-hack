"""Real-time pieces: rain risk, predicted spots, social extraction plumbing, bus impact, GTFS import."""
import csv
import io
import os
import sys
import time
import zipfile

from common import bus, social, spots
from functions.risk_scheduler.app import risk_of

NOW = 1_760_000_000
HOTSPOTS = [
    {"hotspotId": "minto-bridge", "name": "Minto Bridge underpass", "aliases": ["Minto Bridge", "Minto Road"],
     "lon": 77.22667, "lat": 28.63345, "kind": "underpass"},
    {"hotspotId": "hero-honda-chowk", "name": "Hero Honda Chowk underpass", "aliases": ["Hero Honda Chowk"],
     "lon": 77.01018, "lat": 28.43597, "kind": "underpass"},
    {"hotspotId": "ito", "name": "ITO", "lon": 77.24104, "lat": 28.62819, "kind": "junction"},
]


# ---------- rain ----------

def test_risk_levels():
    assert risk_of({"past3h": 25, "now": 0, "next3h": 0}) == "flooding_likely_now"
    assert risk_of({"past3h": 2, "now": 9, "next3h": 0}) == "flooding_likely_now"
    assert risk_of({"past3h": 2, "now": 1, "next3h": 20}) == "likely_flooded_soon"
    assert risk_of({"past3h": 5.3, "now": 0.2, "next3h": 1.8}) == "normal"   # Kochi, 9 Oct 2026


def test_predicted_spot_only_while_raining_hard_and_unreported():
    hs = [dict(HOTSPOTS[0], risk="flooding_likely_now", rainPast3h=30, rainNow=4),
          dict(HOTSPOTS[2], risk="likely_flooded_soon", rainPast3h=5, rainNow=0)]
    p = spots.predicted_spots(hs, [], NOW)
    assert [x["spotId"] for x in p] == ["pred-minto-bridge"]
    s = p[0]
    assert s["predicted"] and s["confidence"] == "low" and s["depth_high"] == 35
    # underpass ~35 cm + low-confidence escalation: scooter and car NO-GO, bus GO escalated to RISKY
    assert s["verdicts"]["scooter"] == "NO_GO" and s["verdicts"]["car"] == "NO_GO"
    assert s["verdicts"]["bus"] == "RISKY"
    # a real report nearby replaces the prediction
    real = [{"lon": 77.2268, "lat": 28.6335}]
    assert spots.predicted_spots(hs, real, NOW) == []


def test_verification_levels():
    assert spots.verification({"predicted": True}) == "predicted"
    assert spots.verification({"sources": ["photo", "official"], "reportCount": 2}) == "official"
    assert spots.verification({"sources": ["photo"], "reportCount": 3}) == "confirmed"
    assert spots.verification({"sources": ["photo", "social"], "reportCount": 2}) == "confirmed"
    assert spots.verification({"sources": ["photo"], "reportCount": 1}) == "single_report"


# ---------- social ----------

def post(text, mins_ago=10, author_type="public", source="x", author="someone"):
    return social._post(text, f"https://example.com/{abs(hash(text))}", NOW - mins_ago * 60, source, author, author_type)


def test_prefilter_needs_keyword_city_and_recency():
    ps = [post("Knee-deep water at Minto Bridge, avoid!"),                 # hotspot name, no city word: kept
          post("Delhi weather is lovely today"),                           # no flood words
          post("Waterlogging in Bengaluru at Silk Board"),                 # other city
          post("Heavy waterlogging near ITO, Delhi", mins_ago=60 * 8),      # too old
          post("जलभराव: दिल्ली के ज़खीरा अंडरपास में पानी")]                  # Hindi keyword + city
    kept = social.prefilter(ps, "delhi", HOTSPOTS, max_age_h=6, now=NOW)
    assert [p["text"][:10] for p in kept] == ["Knee-deep ", "जलभराव: दि"]


def test_match_hotspot_uses_aliases():
    assert social.match_hotspot("Traffic diverted at Minto Road due to waterlogging", HOTSPOTS)["hotspotId"] == "minto-bridge"
    assert social.match_hotspot("hero honda chowk underpass flooded again", HOTSPOTS)["hotspotId"] == "hero-honda-chowk"
    assert social.match_hotspot("waterlogging in sector 31", HOTSPOTS) is None


def test_official_closure_is_no_go_for_all():
    p = post("Traffic movement closed at Minto Bridge underpass due to waterlogging", author_type="official", author="dtptraffic")
    ext = {"is_waterlogging_report": True, "closure": True, "depth_cm_low": None, "depth_cm_high": None, "confidence": "high"}
    loc = social.locate(ext, p["text"], "delhi", HOTSPOTS)
    assert loc[2] == "Minto Bridge underpass" and loc[3] == "hotspot"
    r = social.to_report(p, ext, loc, "delhi")
    assert r["source_type"] == "official" and r["source_label"] == "@dtptraffic"
    assert {v["verdict"] for v in r["verdicts"].values()} == {"NO_GO"}
    assert r["reportId"] == social.report_id(p)  # idempotent id from the URL


def test_public_post_without_depth_is_conservative():
    p = post("Waterlogging at ITO, crawling traffic")
    ext = {"is_waterlogging_report": True, "closure": False, "depth_cm_high": None, "confidence": "low"}
    r = social.to_report(p, ext, social.locate(ext, p["text"], "delhi", HOTSPOTS), "delhi")
    assert r["source_type"] == "social" and r["source_label"] == "Public post"
    assert r["depth_high"] == 25
    assert r["verdicts"]["scooter"]["verdict"] == "NO_GO"   # 25 cm + low confidence
    assert r["verdicts"]["bus"]["verdict"] == "RISKY"       # <40 cm GO, escalated once


def test_heuristic_extract_reads_depth_words():
    e = social.heuristic_extract(post("Knee deep water at Hero Honda Chowk"), "gurugram", HOTSPOTS)
    assert e["is_waterlogging_report"] and (e["depth_cm_low"], e["depth_cm_high"]) == (40, 55)


# ---------- buses ----------

def test_bus_impact():
    routes = bus.index([
        {"ref": "522", "name": "via Minto Road", "lines": [[[77.2250, 28.6334], [77.2280, 28.6335]]]},
        {"ref": "729", "name": "elsewhere", "lines": [[[77.10, 28.50], [77.11, 28.51]]]},
    ])
    flood = {"spotId": "s", "lon": 77.22667, "lat": 28.63345, "depth_high": 60, "place": "Minto Bridge",
             "verdicts": {"bus": "NO_GO", "pedestrian": "NO_GO"}}
    dry = dict(flood, spotId="d", verdicts={"bus": "GO", "pedestrian": "GO"})
    out = bus.impact(routes, [flood, dry])
    assert [r["ref"] for r in out] == ["522"] and out[0]["worst"] == "NO_GO"
    assert bus.impact(routes, [dry]) == []


def test_gtfs_import_with_and_without_shapes(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from import_gtfs import convert

    def make(with_shapes):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            def w(name, rows):
                s = io.StringIO()
                csv.writer(s).writerows(rows)
                z.writestr(name, s.getvalue())
            w("routes.txt", [["route_id", "route_short_name", "route_long_name"], ["r1", "522", "Minto Rd loop"]])
            w("trips.txt", [["route_id", "trip_id", "direction_id", "shape_id"], ["r1", "t1", "0", "sh1"]])
            w("stops.txt", [["stop_id", "stop_lat", "stop_lon"], ["a", "28.6334", "77.2250"], ["b", "28.6335", "77.2280"]])
            w("stop_times.txt", [["trip_id", "stop_id", "stop_sequence"], ["t1", "a", "1"], ["t1", "b", "2"]])
            if with_shapes:
                w("shapes.txt", [["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
                                 ["sh1", "28.6334", "77.2250", "1"], ["sh1", "28.6340", "77.2265", "2"], ["sh1", "28.6335", "77.2280", "3"]])
        p = tmp_path / f"g{with_shapes}.zip"
        p.write_bytes(buf.getvalue())
        return str(p)

    bbox = (77.195, 28.555, 77.265, 28.645)
    a = convert(make(True), bbox)
    b = convert(make(False), bbox)
    assert a[0]["ref"] == "522" and len(a[0]["lines"][0]) == 3
    assert len(b[0]["lines"][0]) == 2
    assert convert(make(True), (70, 10, 71, 11)) == []  # clipped away
