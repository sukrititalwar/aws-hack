"""Where is it raining in India right now? Live rainfall at ~50 cities from Open-Meteo (free, no key).

Open-Meteo gives model analysis + nowcast data, not rain-gauge readings, and the UI says so.
Intensity levels follow the usual hourly bands: light up to 2.5 mm/h, moderate up to 7.5, heavy up to
50, extreme above that (7.5 mm/h is also the "flooding likely" trigger used for the hotspots).
"""
import json
import time
import urllib.parse
import urllib.request

from . import config

# key, name, state, lat, lon, also-known-as (for matching social posts)
_RAW = [
    ("delhi", "Delhi", "Delhi", 28.61, 77.23, ["new delhi"]), ("gurugram", "Gurugram", "Haryana", 28.46, 77.03, ["gurgaon"]),
    ("chandigarh", "Chandigarh", "Chandigarh", 30.73, 76.78, []), ("amritsar", "Amritsar", "Punjab", 31.63, 74.87, []),
    ("dehradun", "Dehradun", "Uttarakhand", 30.32, 78.03, []), ("srinagar", "Srinagar", "J&K", 34.08, 74.80, []),
    ("jaipur", "Jaipur", "Rajasthan", 26.91, 75.79, []), ("lucknow", "Lucknow", "Uttar Pradesh", 26.85, 80.95, []),
    ("kanpur", "Kanpur", "Uttar Pradesh", 26.45, 80.35, []), ("varanasi", "Varanasi", "Uttar Pradesh", 25.32, 83.00, ["banaras"]),
    ("patna", "Patna", "Bihar", 25.59, 85.14, []), ("ranchi", "Ranchi", "Jharkhand", 23.34, 85.31, []),
    ("kolkata", "Kolkata", "West Bengal", 22.57, 88.36, ["calcutta"]), ("bhubaneswar", "Bhubaneswar", "Odisha", 20.30, 85.82, []),
    ("guwahati", "Guwahati", "Assam", 26.14, 91.74, []), ("shillong", "Shillong", "Meghalaya", 25.57, 91.88, []),
    ("imphal", "Imphal", "Manipur", 24.82, 93.94, []), ("agartala", "Agartala", "Tripura", 23.83, 91.28, []),
    ("ahmedabad", "Ahmedabad", "Gujarat", 23.02, 72.57, []), ("surat", "Surat", "Gujarat", 21.17, 72.83, []),
    ("rajkot", "Rajkot", "Gujarat", 22.30, 70.80, []), ("bhopal", "Bhopal", "Madhya Pradesh", 23.26, 77.41, []),
    ("indore", "Indore", "Madhya Pradesh", 22.72, 75.86, []), ("raipur", "Raipur", "Chhattisgarh", 21.25, 81.63, []),
    ("nagpur", "Nagpur", "Maharashtra", 21.15, 79.09, []), ("nashik", "Nashik", "Maharashtra", 20.00, 73.79, []),
    ("mumbai", "Mumbai", "Maharashtra", 19.08, 72.88, ["bombay"]), ("pune", "Pune", "Maharashtra", 18.52, 73.86, []),
    ("goa", "Goa", "Goa", 15.30, 74.12, ["panaji"]), ("hyderabad", "Hyderabad", "Telangana", 17.39, 78.49, []),
    ("visakhapatnam", "Visakhapatnam", "Andhra Pradesh", 17.69, 83.22, ["vizag"]), ("vijayawada", "Vijayawada", "Andhra Pradesh", 16.51, 80.65, []),
    ("tirupati", "Tirupati", "Andhra Pradesh", 13.63, 79.42, []), ("nellore", "Nellore", "Andhra Pradesh", 14.44, 79.99, []),
    ("bengaluru", "Bengaluru", "Karnataka", 12.97, 77.59, ["bangalore"]), ("mysuru", "Mysuru", "Karnataka", 12.30, 76.64, ["mysore"]),
    ("mangaluru", "Mangaluru", "Karnataka", 12.91, 74.86, ["mangalore"]), ("chennai", "Chennai", "Tamil Nadu", 13.08, 80.27, ["madras"]),
    ("puducherry", "Puducherry", "Puducherry", 11.93, 79.83, ["pondicherry"]), ("tiruchirappalli", "Tiruchirappalli", "Tamil Nadu", 10.79, 78.70, ["trichy"]),
    ("salem", "Salem", "Tamil Nadu", 11.66, 78.15, []), ("coimbatore", "Coimbatore", "Tamil Nadu", 11.00, 76.96, []),
    ("madurai", "Madurai", "Tamil Nadu", 9.93, 78.12, []), ("rameswaram", "Rameswaram", "Tamil Nadu", 9.29, 79.31, []),
    ("kanyakumari", "Kanyakumari", "Tamil Nadu", 8.09, 77.54, []), ("kozhikode", "Kozhikode", "Kerala", 11.26, 75.78, ["calicut"]),
    ("thrissur", "Thrissur", "Kerala", 10.52, 76.21, ["trichur"]), ("kochi", "Kochi", "Kerala", 9.93, 76.27, ["ernakulam", "cochin"]),
    ("thiruvananthapuram", "Thiruvananthapuram", "Kerala", 8.52, 76.94, ["trivandrum"]), ("port-blair", "Port Blair", "Andaman & Nicobar", 11.62, 92.73, []),
]
CITIES = [dict(key=k, name=n, state=s, lat=la, lon=lo, aka=a) for k, n, s, la, lo, a in _RAW]
BY_KEY = {c["key"]: c for c in CITIES}

LEVELS = [(0.1, "dry"), (2.5, "light"), (7.5, "moderate"), (50.0, "heavy")]
CACHE_S = 300
_cache: dict = {"ts": 0.0, "data": None}


def level_of(now_mm_h: float, past3h: float = 0.0) -> str:
    """Intensity band from the current rate, or the 3-hour average if it just stopped raining."""
    x = max(now_mm_h, past3h / 3)
    if x < 0.1:
        return "dry"
    for top, name in LEVELS[1:]:
        if x <= top:
            return name
    return "extreme"


def parse(cities: list[dict], data) -> list[dict]:
    """Open-Meteo multi-location response -> one row per city."""
    data = data if isinstance(data, list) else [data]
    rows = []
    for c, d in zip(cities, data):
        p = [v or 0 for v in d["hourly"]["precipitation"]]          # past 3 h, then next 6 h
        now = float((d.get("current") or {}).get("precipitation") or 0)
        past, nxt = sum(p[:3]), sum(p[3:9])
        rows.append({"key": c["key"], "name": c["name"], "state": c["state"], "lat": c["lat"], "lon": c["lon"],
                     "now": round(now, 1), "past3h": round(past, 1), "next6h": round(nxt, 1),
                     "level": level_of(now, past), "supported": c["key"] in config.CITIES})
    return rows


def fetch_live() -> dict:
    q = urllib.parse.urlencode({
        "latitude": ",".join(str(c["lat"]) for c in CITIES), "longitude": ",".join(str(c["lon"]) for c in CITIES),
        "current": "precipitation", "hourly": "precipitation", "past_hours": 3, "forecast_hours": 6, "timezone": "Asia/Kolkata"})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=20) as r:
        data = json.loads(r.read())
    rows = parse(CITIES, data)
    return {"updatedAt": int(time.time()), "cities": rows, "summary": summarise(rows),
            "source": "Open-Meteo (model analysis and nowcast, not rain-gauge readings)"}


def summarise(rows: list[dict]) -> dict:
    by = {}
    for r in rows:
        by[r["level"]] = by.get(r["level"], 0) + 1
    raining = [r for r in rows if r["level"] != "dry"]
    top = sorted(raining, key=lambda r: -(r["now"] * 3 + r["past3h"] + r["next6h"]))[:3]
    heavy = by.get("heavy", 0) + by.get("extreme", 0)
    if heavy:
        headline = f"Heavy rain at {heavy} place{'s' if heavy != 1 else ''}"
    elif raining:
        headline = f"Only light to moderate rain right now ({len(raining)} of {len(rows)} places); no heavy rain reported"
    else:
        headline = "No rain at any of the places checked"
    return {"counts": by, "raining": len(raining), "checked": len(rows), "headline": headline,
            "wettest": [r["key"] for r in top]}


def get() -> dict:
    """Live data, cached for a few minutes per container so we never hammer the free API."""
    if _cache["data"] and time.time() - _cache["ts"] < CACHE_S:
        return _cache["data"]
    _cache.update(data=fetch_live(), ts=time.time())
    return _cache["data"]
