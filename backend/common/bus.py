"""Which bus routes pass a flooded spot (and are therefore likely diverted or stuck).

Route lines come from data/bus_routes_<city>.json: from the official GTFS feed
(scripts/import_gtfs.py, e.g. Delhi DTC/cluster buses) or OSM route=bus relations
(scripts/build_graph.py). Format: {"routes": [{"ref", "name", "operator", "lines": [[[lon, lat], ...], ...]}]}
"""
from . import config, geo

NEAR_M = 40


def _bbox(line):
    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    return min(xs), min(ys), max(xs), max(ys)


def index(routes: list[dict]) -> list[dict]:
    """Precompute per-line bboxes once per container."""
    for r in routes:
        r["_bb"] = [_bbox(l) for l in r["lines"]]
    return routes


def impact(routes: list[dict], spots: list[dict]) -> list[dict]:
    """Routes passing within NEAR_M of a spot that is RISKY/NO-GO for a bus.

    Also lists spots NO-GO for pedestrians on the route: passengers can't safely reach those stops."""
    pad = NEAR_M / 111_000 * 1.5
    out = []
    for r in routes:
        hits = []
        for s in spots:
            bus_v = s["verdicts"].get("bus", "GO")
            walk_v = s["verdicts"].get("pedestrian", "GO")
            if bus_v == "GO" and walk_v != "NO_GO":
                continue
            for line, (a, b, c, d) in zip(r["lines"], r.get("_bb") or [_bbox(l) for l in r["lines"]]):
                if not (a - pad <= s["lon"] <= c + pad and b - pad <= s["lat"] <= d + pad):
                    continue
                if geo.point_polyline_m(s["lon"], s["lat"], line) <= NEAR_M:
                    hits.append({"spotId": s["spotId"], "place": s.get("place"), "depth_high": s["depth_high"],
                                 "bus": bus_v, "pedestrian": walk_v, "predicted": bool(s.get("predicted"))})
                    break
        if hits:
            worst = "NO_GO" if any(h["bus"] == "NO_GO" for h in hits) else ("RISKY" if any(h["bus"] == "RISKY" for h in hits) else "GO")
            out.append({"ref": r["ref"], "name": r["name"], "operator": r.get("operator", ""), "worst": worst, "spots": hits})
    order = {"NO_GO": 0, "RISKY": 1, "GO": 2}
    out.sort(key=lambda x: (order[x["worst"]], x["ref"]))
    return out
