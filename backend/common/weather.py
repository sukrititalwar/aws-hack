"""Forecast rain at a point (Open-Meteo, free, no key)."""
import json
import logging
import urllib.parse
import urllib.request

log = logging.getLogger()


def next24h_mm(lat: float, lon: float) -> float | None:
    """Total forecast precipitation over the next 24 h in mm, or None if the API is unreachable."""
    q = urllib.parse.urlencode({"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": "precipitation",
                                "forecast_hours": 24, "timezone": "Asia/Kolkata"})
    try:
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=8) as r:
            return round(sum(x or 0 for x in json.loads(r.read())["hourly"]["precipitation"]), 1)
    except Exception:
        log.warning("rain forecast unavailable for %s,%s", lat, lon)
        return None
