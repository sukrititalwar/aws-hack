"""Routing on a tiny synthetic grid:

    0 ---- 1 ---- 2        top row: a main road (class 1), the short way
    |             |
    3 ---- 4 ---- 5        bottom row: a gali (class 3), the detour

Going 0 -> 2 normally uses the top road. A NO_GO spot on edge 0-1 forces the detour.
"""
from common import routing

D = 0.001  # ~105 m in lon at this latitude, ~111 m in lat

NODES = [[72.85, 19.101], [72.85 + D, 19.101], [72.85 + 2 * D, 19.101],
         [72.85, 19.100], [72.85 + D, 19.100], [72.85 + 2 * D, 19.100]]
EDGES = [
    [0, 1, 105, 1, 0, None],
    [1, 2, 105, 1, 0, None],
    [0, 3, 111, 3, 0, None],
    [3, 4, 105, 3, 0, None],
    [4, 5, 105, 3, 0, None],
    [5, 2, 111, 3, 0, None],
]


def graph():
    return routing.Graph({"nodes": NODES, "edges": EDGES})


def spot(sid, lon, lat, verdict):
    return {"spotId": sid, "lon": lon, "lat": lat, "depth_high": 30, "place": sid,
            "verdicts": {v: verdict for v in routing.ACCESS}}


def test_no_spots_safe_equals_normal():
    r = routing.plan(graph(), NODES[0], NODES[2], "scooter", [])
    assert r["normal"]["distance_m"] == 210
    assert r["safe"] == r["normal"]
    assert "No flooded" in r["note"]


def test_no_go_spot_forces_detour_through_gali():
    s = spot("underpass", 72.85 + D / 2, 19.101, "NO_GO")
    r = routing.plan(graph(), NODES[0], NODES[2], "scooter", [s])
    assert r["normal"]["distance_m"] == 210
    assert r["safe"]["distance_m"] == 432
    assert [x["spotId"] for x in r["avoided_spots"]] == ["underpass"]
    assert r["extra_min"] > 0
    assert r["note"].startswith("Avoids 1 flooded spot")
    assert r["safe"]["geometry"]["coordinates"][0] == NODES[0]
    assert r["safe"]["geometry"]["coordinates"][-1] == NODES[2]


def test_risky_spot_penalised_not_blocked():
    s = spot("dip", 72.85 + D / 2, 19.101, "RISKY")
    r = routing.plan(graph(), NODES[0], NODES[2], "scooter", [s])
    # 105*5 + 105 = 630 > 432, so the detour wins
    assert r["safe"]["distance_m"] == 432


def test_go_spot_ignored():
    s = spot("puddle", 72.85 + D / 2, 19.101, "GO")
    r = routing.plan(graph(), NODES[0], NODES[2], "scooter", [s])
    assert r["safe"]["distance_m"] == 210


def test_no_dry_route():
    spots = [spot("a", 72.85 + D / 2, 19.101, "NO_GO"), spot("b", 72.85 + D / 2, 19.100, "NO_GO")]
    r = routing.plan(graph(), NODES[0], NODES[2], "scooter", spots)
    assert r["safe"] is None
    assert "No dry route" in r["note"]


def test_oneway_respected_for_cars_not_pedestrians():
    edges = [list(e) for e in EDGES]
    edges[0][4] = routing.ONEWAY  # 0 -> 1 only
    g = routing.Graph({"nodes": NODES, "edges": edges})
    car = routing.plan(g, NODES[1], NODES[0], "car", [])
    walk = routing.plan(g, NODES[1], NODES[0], "pedestrian", [])
    assert walk["normal"]["distance_m"] == 105
    assert car["normal"]["distance_m"] > 105


def test_reversed_edge_geometry_order():
    edges = [list(e) for e in EDGES]
    edges[0][5] = [NODES[0], [72.85 + D / 2, 19.1012], NODES[1]]
    g = routing.Graph({"nodes": NODES, "edges": edges})
    r = routing.plan(g, NODES[1], NODES[0], "pedestrian", [])
    coords = r["normal"]["geometry"]["coordinates"]
    assert coords == [NODES[1], [72.85 + D / 2, 19.1012], NODES[0]]


def test_bus_cannot_use_galis():
    s = spot("underpass", 72.85 + D / 2, 19.101, "NO_GO")
    r = routing.plan(graph(), NODES[0], NODES[2], "bus", [s])
    assert r["safe"] is None  # the only detour is a gali
    assert "No dry route" in r["note"]


def test_compare_scooter_detours_car_goes_usual_way():
    # 25 cm at the main-road spot: NO_GO for a scooter, RISKY for a car, GO for SUV and bus
    s = {"spotId": "u", "lon": 72.85 + D / 2, "lat": 19.101, "depth_high": 25, "place": "Underpass",
         "verdicts": {"scooter": "NO_GO", "auto": "NO_GO", "car": "RISKY", "suv": "GO", "bus": "GO"}}
    by = {x["vehicle"]: x for x in routing.compare(graph(), NODES[0], NODES[2], [s])}
    assert by["scooter"]["status"] == "detour" and by["scooter"]["blocking"] == ["Underpass"]
    assert by["car"]["status"] in ("detour", "usual_with_care")  # penalised: detour is shorter than 5x
    assert by["suv"]["status"] == "usual"
    assert by["bus"]["status"] == "usual"


def test_snapping_avoids_one_way_stubs():
    # node 6 hangs off node 2 by a one-way edge 6 -> 2 only: a car can leave 6 but never reach it
    nodes = NODES + [[72.85 + 2 * D, 19.1012]]
    edges = EDGES + [[6, 2, 22, 2, routing.ONEWAY, None]]
    g = routing.Graph({"nodes": nodes, "edges": edges})
    assert 6 not in g.core("car")
    r = routing.plan(g, NODES[0], nodes[6], "car", [])   # destination tapped on the stub
    assert r["normal"] is not None and r["snap_m"][1] < 30
