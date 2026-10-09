"""GET /hotspots?city=..  chronic flood points (cited ground truth) with live rain risk,
plus the city's current rain summary written by risk_scheduler."""
from common import config, db, http


def handler(event, _ctx):
    city = (http.qs(event).get("city") or "delhi").lower()
    if city not in config.CITIES:
        return http.bad("unsupported city")
    items = db.hotspots(city)
    weather = next((i for i in items if i["hotspotId"] == "#weather"), None)
    return http.resp(200, {"hotspots": [i for i in items if not i["hotspotId"].startswith("#")],
                           "weather": weather})
