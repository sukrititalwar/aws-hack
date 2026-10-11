"""Read-only "what is happening" endpoints. Nothing here writes to a database.

  GET /rain/india                    live rainfall at ~50 Indian cities (Open-Meteo), cached 5 min
  GET /rain/india/posts?city=<key>   recent public posts / news about rain and waterlogging in that city
  GET /simulation?at=<epoch>         the DEMO Delhi storm (made-up values), clearly marked simulated
"""
import logging

from common import http, india_rain, simulation, social

log = logging.getLogger()


def handler(event, _ctx):
    route, q = event.get("routeKey", ""), http.qs(event)
    try:
        if route == "GET /rain/india":
            return http.resp(200, india_rain.get())
        if route == "GET /simulation":
            return http.resp(200, simulation.payload(float(q["at"]) if q.get("at") else None))
        if route == "GET /rain/india/posts":
            city = (q.get("city") or "").lower()
            if city not in india_rain.BY_KEY:
                return http.bad("unknown city")
            return http.resp(200, social.live_posts(city, hours=float(q.get("hours") or 24)))
    except ValueError:
        return http.bad("bad parameter")
    except Exception:
        log.exception("insights failed")
        return http.bad("This data source is not reachable right now. Please try again in a minute.", 502)
    return http.bad("not found", 404)
