"""National rain and live posts for any city."""
import json

import pytest

from common import india_rain, social
from functions.insights import app as insights


def ev(route, qs=None):
    return {"routeKey": route, "queryStringParameters": qs}


# ---------------- India rain ----------------

def fake_openmeteo(cities, now_by_key=None, past=None, nxt=None):
    """Open-Meteo style multi-location response."""
    out = []
    for c in cities:
        n = (now_by_key or {}).get(c["key"], 0.0)
        out.append({"current": {"precipitation": n}, "hourly": {"precipitation": [(past or {}).get(c["key"], 0.0) / 3] * 3 + [(nxt or {}).get(c["key"], 0.0) / 6] * 6}})
    return out


def test_levels():
    assert india_rain.level_of(0.0) == "dry" and india_rain.level_of(0.05) == "dry"
    assert india_rain.level_of(0.3) == "light" and india_rain.level_of(2.5) == "light"
    assert india_rain.level_of(2.6) == "moderate" and india_rain.level_of(7.5) == "moderate"
    assert india_rain.level_of(7.6) == "heavy" and india_rain.level_of(51) == "extreme"
    assert india_rain.level_of(0.0, past3h=9.0) == "moderate"      # it just stopped: use the 3 h average


def test_parse_and_summary_are_honest_about_calm_days():
    cs = india_rain.CITIES[:5]
    rows = india_rain.parse(cs, fake_openmeteo(cs, {cs[0]["key"]: 0.3}))
    assert rows[0]["level"] == "light" and rows[1]["level"] == "dry"
    s = india_rain.summarise(rows)
    assert s["raining"] == 1 and "no heavy rain" in s["headline"] and s["wettest"] == [cs[0]["key"]]
    dry = india_rain.summarise(india_rain.parse(cs, fake_openmeteo(cs)))
    assert dry["headline"].startswith("No rain")
    wet = india_rain.parse(cs, fake_openmeteo(cs, {cs[2]["key"]: 12.0}))
    assert india_rain.summarise(wet)["headline"] == "Heavy rain at 1 place"


def test_supported_flag_and_catalogue():
    keys = {c["key"] for c in india_rain.CITIES}
    assert len(india_rain.CITIES) >= 45 and len(keys) == len(india_rain.CITIES)         # unique keys
    from common import config
    assert set(config.CITIES) <= keys                                                       # every live city is in the list
    row = india_rain.parse([india_rain.BY_KEY["thiruvananthapuram"]], fake_openmeteo([india_rain.BY_KEY["thiruvananthapuram"]]))[0]
    assert row["supported"] is True
    assert india_rain.parse([india_rain.BY_KEY["pune"]], fake_openmeteo([india_rain.BY_KEY["pune"]]))[0]["supported"] is False


def test_rain_endpoint_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(india_rain, "fetch_live", lambda: calls.append(1) or {"updatedAt": 1, "cities": [], "summary": {}, "source": "x"})
    india_rain._cache.update(ts=0.0, data=None)
    insights.handler(ev("GET /rain/india"), None)
    insights.handler(ev("GET /rain/india"), None)
    assert len(calls) == 1


# ---------------- live posts for any city ----------------

def test_city_info_for_unsupported_city():
    assert social.city_info("pune")["label"] == "Pune"
    assert "trivandrum" in social.city_info("thiruvananthapuram")["names"]
    with pytest.raises(KeyError):
        social.city_info("atlantis")


def test_live_posts_filters_and_hides_private_handles(monkeypatch):
    import time
    now = time.time()
    posts = [social._post("Heavy waterlogging near Pune station, roads flooded", "https://n/1", now - 600, "news", "The Hindu", "news"),
             social._post("Waterlogging at Katraj Pune, awful", "https://b/2", now - 300, "bluesky", "someone.bsky.social"),
             social._post("Mumbai rains: flooded roads", "https://n/3", now - 100, "news", "TOI", "news"),                  # other city
             social._post("Lovely weather in Pune today", "https://n/4", now - 100, "bluesky", "x"),                       # no flood words
             social._post("Waterlogging in Pune", "https://old", now - 3 * 86400, "news", "Old", "news")]                  # too old
    monkeypatch.setattr(social, "fetch_all", lambda city, hours=24: (posts, {"google_news": 3}))
    social._posts_cache.clear()
    r = social.live_posts("pune")
    assert [p["url"] for p in r["posts"]] == ["https://b/2", "https://n/1"]          # newest first
    by = {p["url"]: p for p in r["posts"]}
    assert by["https://b/2"]["author"] == "Public post"                              # private handle not shown
    assert by["https://n/1"]["author"] == "The Hindu"
    assert r["label"] == "Pune"


def test_posts_endpoint_validates_city():
    assert insights.handler(ev("GET /rain/india/posts", {"city": "atlantis"}), None)["statusCode"] == 400


def test_fetch_all_runs_sources_in_parallel_and_survives_a_slow_or_broken_one(monkeypatch):
    import time

    def fast(city, hours):
        return [social._post("flooded road in Pune", "https://a", time.time(), "news")]

    def broken(city, hours):
        raise RuntimeError("down")

    def slow(city, hours):
        time.sleep(3)
        return []
    fast.__name__, broken.__name__, slow.__name__ = "fetch_google_news", "fetch_bluesky", "fetch_mastodon"
    monkeypatch.setattr(social, "FETCHERS", [fast, broken, slow])
    t0 = time.time()
    posts, stats = social.fetch_all("pune", budget_s=0.5)
    assert time.time() - t0 < 2.0                                    # did not wait for the slow source
    assert len(posts) == 1 and stats["google_news"] == 1
    assert stats["bluesky"].startswith("error: RuntimeError") and stats["mastodon"] == "error: timeout"


# ---------------- the DEMO storm (made-up values, clearly labelled) ----------------

def test_demo_is_labelled_as_made_up_everywhere():
    from common import simulation as sim
    assert sim.DISCLAIMER
    p = sim.payload(sim.START + 150 * 60)
    assert p["simulation"] is True and p["weather"]["simulated"] and "DEMO" in p["weather"]["source"]
    assert p["spots"] and all(s["simulated"] for s in p["spots"])
    assert p["posts"] and all(x["simulated"] and x["author"].startswith("Demo") and x["url"] is None for x in p["posts"])
    assert all(d["simulated"] for d in p["drains"])


def test_demo_is_deterministic_and_clamped():
    from common import simulation as sim
    a, b = sim.payload(sim.START + 100 * 60), sim.payload(sim.START + 100 * 60)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert sim.clamp(0) == sim.START and sim.clamp(sim.END + 99999) == sim.END


def test_demo_storm_builds_and_clears():
    from common import simulation as sim
    assert sim.spots_at(sim.START) == []
    assert len(sim.spots_at(sim.START + 150 * 60)) == len(sim.SITES)
    assert sim.rain_at(sim.START + 150 * 60)["rainNow"] > 30
    assert sim.rain_at(sim.START)["rainNow"] < 1


def test_demo_has_variety_and_danger_is_no_go_for_everyone():
    from common import simulation as sim
    spots = sim.spots_at(sim.START + 150 * 60)
    scooter = {s["verdicts"]["scooter"] for s in spots}
    assert len(scooter) >= 2
    danger = next(s for s in spots if "Sewa Nagar" in (s.get("place") or ""))
    assert all(v == "NO_GO" for v in danger["verdicts"].values())


def test_simulation_endpoint():
    from common import simulation as sim
    r = insights.handler(ev("GET /simulation", {"at": str(sim.START + 120 * 60)}), None)
    body = json.loads(r["body"])
    assert r["statusCode"] == 200 and body["simulation"] is True and body["scenario"]["city"] == "delhi"


def test_demo_route_detours_around_minto_bridge(monkeypatch):
    import os
    from common import routing, simulation as sim
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "graphs", "delhi.json.gz")
    monkeypatch.setenv("GRAPH_PATH", path)
    from functions.route import app as route
    route._GRAPHS.clear()
    at = sim.START + 100 * 60
    ev_ = {"routeKey": "POST /route", "body": json.dumps({"from": [77.2150, 28.6420], "to": [77.2300, 28.6290], "vehicle": "scooter",
                                                           "city": "delhi", "mode": "sim", "at": at})}
    r = route.handler(ev_, None)
    assert r["statusCode"] == 200
    out = json.loads(r["body"])
    assert out["spots_considered"] >= 1
    r2 = route.handler({**ev_, "body": json.dumps({"from": [77.2150, 28.6420], "to": [77.2300, 28.6290], "vehicle": "scooter", "city": "mumbai", "mode": "sim"})}, None)
    assert r2["statusCode"] == 400
