"""DEMO: a made-up heavy-rain evening in central Delhi, for demos.

Nothing here is real. The values (depths, report counts, posts, rain) are invented to show what the
app looks like in a Delhi storm. The point of the module is that the *logic* is the real thing:
verdicts come from rules.py, spots are merged by spots.py, drains are ranked by drains.py, and the
routes come from the real router. Every item carries `simulated: True`, nothing is ever written to
the database, and no alert (SNS, WhatsApp) can be triggered from it.

Fixed storm clock: the evening starts at START (17:00) and runs 5.5 hours. `at` is epoch seconds
inside that window, so the timeline scrubber works.
"""
import math
import random
from datetime import datetime, timedelta, timezone

from . import drains, spots

IST = timezone(timedelta(hours=5, minutes=30))
START = int(datetime(2026, 7, 26, 17, 0, tzinfo=IST).timestamp())     # a fixed, fictional storm evening
MINUTES = 330
END = START + MINUTES * 60
CITY = "delhi"
AREA = "Central Delhi: Minto Bridge, ITO, Pragati Maidan, Moolchand, Ashram"
DISCLAIMER = "Demo storm."

# place, lon, lat, onset (min), peak (min), peak depth cm, hazards, how many reports at the peak
SITES = [
    ("Minto Bridge underpass", 77.2224, 28.6364, 15, 70, 95, [], 7),
    ("Pragati Maidan tunnel", 77.2407, 28.6172, 20, 75, 85, ["strong_current"], 6),
    ("Moolchand underpass", 77.2341, 28.5655, 30, 90, 60, ["open_drain_or_manhole_risk"], 5),
    ("ITO crossing", 77.2410, 28.6282, 35, 90, 28, [], 4),
    ("Ashram underpass", 77.2583, 28.5725, 40, 110, 70, [], 5),
    ("Vinay Marg underpass", 77.1909, 28.5817, 45, 100, 40, [], 3),
    ("Sewa Nagar underpass", 77.2220, 28.5792, 55, 120, 30, ["electric_pole_or_wire_in_water"], 3),
    ("AIIMS-side underpass", 77.2140, 28.5690, 60, 110, 32, ["debris"], 3),
    ("Shivaji Bridge approach", 77.2289, 28.6323, 70, 130, 12, [], 2),
]

# minute, text, kind: "public" | "news" | "official" (official = a *generic demo* alert, never a real agency's words)
POSTS = [
    (22, "Sudden heavy downpour over central Delhi, roads filling up fast #DelhiRains", "public", None),
    (38, "Water logging at Minto Bridge underpass, cars stuck, please avoid", "public", "Minto Bridge underpass"),
    (52, "Pragati Maidan tunnel: knee deep water and a strong flow, bikes turning back", "public", "Pragati Maidan tunnel"),
    (60, "Demo traffic alert: Minto Bridge underpass closed to traffic because of waterlogging. Use alternate routes.", "official", "Minto Bridge underpass"),
    (70, "Moolchand underpass is a pond right now. Open manhole near the divider. Careful!", "public", "Moolchand underpass"),
    (78, "ITO crossing crawling, water up to the kerb, buses diverted", "public", "ITO crossing"),
    (88, "Ashram underpass flooded, scooters stalling, a DTC bus is stuck", "public", "Ashram underpass"),
    (96, "Demo news: Heavy rain lashes Delhi, several underpasses waterlogged, traffic snarls across the centre", "news", None),
    (104, "Vinay Marg underpass water above the tyres of cars, avoid", "public", "Vinay Marg underpass"),
    (118, "DANGER: live wire hanging near Sewa Nagar underpass, water everywhere, stay away", "public", "Sewa Nagar underpass"),
    (125, "Demo traffic alert: Pragati Maidan tunnel closed. Diversion via Ring Road.", "official", "Pragati Maidan tunnel"),
    (140, "AIIMS side underpass: lots of plastic and branches in the water, drain blocked", "public", "AIIMS-side underpass"),
    (170, "Rain easing at ITO but the road is still under water, give it an hour", "public", "ITO crossing"),
    (215, "Water slowly receding at Minto Bridge underpass, still not safe for two-wheelers", "public", "Minto Bridge underpass"),
    (260, "Demo news: Waterlogging clears from most central Delhi underpasses after rain stops", "news", None),
]

# (place, lon, lat, minute reported, severity, assigned at minute or None)
DRAIN_SITES = [
    ("Minto Road gully near the bridge", 77.2218, 28.6362, 25, "blocked", 60),
    ("ITO drain at the signal", 77.2405, 28.6280, 40, "partial", None),
    ("Moolchand underpass sump", 77.2338, 28.5657, 45, "blocked", 95),
    ("Ashram flyover gully", 77.2580, 28.5728, 55, "blocked", None),
    ("Pragati Maidan tunnel mouth", 77.2400, 28.6175, 35, "partial", 80),
    ("Sewa Nagar nala", 77.2223, 28.5790, 70, "blocked", None),
]


def _depth(site, m: float) -> float:
    """Depth (cm) of a site at minute m: rises from the onset to the peak, then drains slowly."""
    _, _, _, onset, peak, hi, *_ = site
    if m < onset:
        return 0.0
    if m <= peak:
        return hi * math.sin((m - onset) / (peak - onset) * math.pi / 2)
    return max(hi * 0.35, hi * (1 - 0.65 * min(1, (m - peak) / 150)))


def _reports() -> list[dict]:
    """The full set of invented reports for the whole evening (seeded: identical every time)."""
    out = []
    for si, site in enumerate(SITES):
        place, lon, lat, onset, peak, hi, hazards, n_peak = site
        rnd = random.Random(1000 + si)
        n = n_peak + 3
        first, last = onset + 8, min(MINUTES - 20, peak + 90)      # reports cluster around the peak of each spot
        for i in range(n):
            m = first + (last - first) * (i + rnd.uniform(0, 0.9)) / n
            high = max(3.0, _depth(site, m) * rnd.uniform(0.88, 1.15))
            conf = rnd.choices(["high", "medium", "low"], [0.35, 0.45, 0.2])[0]
            out.append({
                "reportId": f"sim-{si}-{i}", "lat": lat + rnd.uniform(-0.0002, 0.0002), "lon": lon + rnd.uniform(-0.0002, 0.0002),
                "ts": START + int(m * 60), "depth_low": round(max(0, high - rnd.uniform(8, 16))), "depth_high": round(high),
                "confidence": conf, "image_quality": rnd.choice(["good", "ok", "ok"]), "flowing_water": "strong_current" in hazards,
                "hazards": list(hazards), "votes": {}, "source_type": "social" if i % 3 == 2 else "photo", "place": place,
            })
    return out


_ALL = None


def _all():
    global _ALL
    if _ALL is None:
        _ALL = _reports()
    return _ALL


def clamp(at: float | None) -> float:
    return min(max(float(at) if at else START, START), END)


def spots_at(at: float | None) -> list[dict]:
    """Merged flooded spots at storm time `at`, from the real merging + rules code."""
    now = clamp(at)
    out = spots.build_spots(_all(), now)
    for s in out:
        s["simulated"] = True
    return out


def rain_at(at: float | None) -> dict:
    """Invented rainfall: a bell-shaped burst peaking around 19:30."""
    m = (clamp(at) - START) / 60

    def rate(x):
        return 38 * math.exp(-(((x - 150) / 65) ** 2))
    past = sum(rate(m - k * 10) / 6 for k in range(0, 18) if m - k * 10 >= 0)
    nxt = sum(rate(m + k * 10) / 6 for k in range(1, 19))
    at_risk = sum(1 for s in spots_at(at) if s["verdicts"].get("scooter") == "NO_GO")
    return {"rainNow": round(rate(m), 1), "rainPast3h": round(past, 1), "rainNext3h": round(nxt, 1),
            "maxRainNowAtHotspots": round(rate(m), 1), "hotspotsAtRisk": at_risk, "updatedAt": int(clamp(at)),
            "source": "DEMO rainfall", "simulated": True}


def posts_at(at: float | None) -> list[dict]:
    now = clamp(at)
    out = []
    for i, (m, text, kind, place) in enumerate(POSTS):
        ts = START + m * 60
        if ts <= now:
            out.append({"id": f"sim-post-{i}", "text": text, "ts": ts, "url": None, "place": place, "simulated": True,
                        "source": "simulated", "author_type": kind,
                        "author": {"official": "Demo traffic alert", "news": "Demo news", "public": "Demo public post"}[kind]})
    return sorted(out, key=lambda p: -p["ts"])


def drains_at(at: float | None) -> list[dict]:
    now = clamp(at)
    reports = []
    rain = rain_at(at)["rainNext3h"] * 3                          # rough 24 h figure for the priority maths
    for i, (place, lon, lat, m, sev, assigned) in enumerate(DRAIN_SITES):
        if START + m * 60 > now:
            continue
        is_assigned = assigned is not None and START + assigned * 60 <= now
        for k in range(2 if sev == "blocked" else 1):
            reports.append({"reportId": f"sim-drain-{i}-{k}", "city": CITY, "lat": lat + k * 0.00008, "lon": lon, "ts": START + (m + k * 4) * 60,
                            "status": "assigned" if is_assigned else "open", "severity": sev, "blockage_type": "garbage",
                            "rainNext24h": round(max(rain, 20), 1), "deviceHash": f"sim{i}{k}", "note": place,
                            "assignedTo": "Demo worker" if is_assigned else None,
                            "assignedAt": START + (assigned or 0) * 60 if is_assigned else None, "groupId": f"sim-drain-{i}-0"})
    rows = drains.build_groups(reports, [{"name": s[0], "lon": s[1], "lat": s[2]} for s in SITES])
    for r in rows:
        r["simulated"] = True
    return rows


def payload(at: float | None) -> dict:
    """Everything the app needs to draw the demo storm at time `at`."""
    now = clamp(at)
    return {
        "simulation": True, "disclaimer": DISCLAIMER,
        "scenario": {"city": CITY, "area": AREA, "start": START, "end": END, "name": "Delhi storm (demo)"},
        "now": int(now), "spots": spots_at(now), "weather": rain_at(now), "posts": posts_at(now), "drains": drains_at(now),
    }
