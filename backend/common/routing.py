"""Flood-aware routing over a compact street graph exported by scripts/build_graph.py.

Graph JSON:
  nodes: [[lon, lat], ...]
  edges: [[u, v, length_m, road_class, flags, geometry|null], ...]
     road_class: 0 motorway, 1 major (trunk/primary/secondary), 2 tertiary (bus-capable),
                 3 gali (residential/service/unclassified), 4 track/path, 5 foot-only
     flags bit 1: oneway (u->v only), bit 2: tunnel/underpass, bit 4: bridge
     geometry: [[lon, lat], ...] including both ends, or null for a straight edge

Pure Python (heapq A*). ~30k nodes routes in well under a second inside Lambda, and the
same file can be shipped to the PWA for on-device routing.
"""
import heapq
import math

from . import config, geo

ONEWAY, TUNNEL, BRIDGE = 1, 2, 4

# Which road classes each vehicle may use, and whether it must respect one-way streets.
# Buses stay on bus-capable roads (no galis); two-wheelers and autos use galis but not expressways.
ACCESS = {
    "pedestrian": ({1, 2, 3, 4, 5}, False),
    "bicycle": ({1, 2, 3, 4, 5}, True),
    "scooter": ({1, 2, 3, 4}, True),
    "auto": ({1, 2, 3, 4}, True),
    "car": ({0, 1, 2, 3}, True),
    "suv": ({0, 1, 2, 3, 4}, True),
    "bus": ({0, 1, 2}, True),
    "ambulance": ({0, 1, 2, 3}, True),
}
COMPARE_VEHICLES = ["scooter", "auto", "car", "suv", "bus"]

GRID = 0.001  # ~100 m grid for the edge spatial index
# A graph can cover several separate areas of a city (e.g. central and north-west Delhi). Each area's
# road network is its own big component; tiny islands (one-way stubs, gated lanes) are still dropped.
MIN_AREA_NODES = 50
OUT_OF_AREA_M = 500  # a tap further than this from any usable road is outside our coverage


class Graph:
    def __init__(self, data: dict):
        self.nodes = data["nodes"]
        self.edges = data["edges"]
        # [{"name": ..., "bbox": [w, s, e, n]}]: what we have road data for, shown to the user
        self.areas = data.get("areas") or ([{"name": data.get("city", ""), "bbox": data["bbox"]}] if data.get("bbox") else [])
        self._adj_cache: dict = {}
        self._core_cache: dict = {}
        self._comp_cache: dict = {}
        self._grid: dict = {}
        for i, e in enumerate(self.edges):
            for cell in self._cells_for(self.geometry(i)):
                self._grid.setdefault(cell, []).append(i)

    # ---------- geometry ----------
    def geometry(self, ei: int) -> list:
        u, v, _, _, _, g = self.edges[ei]
        return g if g else [self.nodes[u], self.nodes[v]]

    @staticmethod
    def _cells_for(coords):
        xs, ys = [c[0] for c in coords], [c[1] for c in coords]
        for gx in range(math.floor(min(xs) / GRID), math.floor(max(xs) / GRID) + 1):
            for gy in range(math.floor(min(ys) / GRID), math.floor(max(ys) / GRID) + 1):
                yield gx, gy

    def edges_near(self, lon, lat, radius_m) -> set[int]:
        r_deg = radius_m / 111_000 / max(math.cos(math.radians(lat)), 0.2)
        found = set()
        for gx in range(math.floor((lon - r_deg) / GRID), math.floor((lon + r_deg) / GRID) + 1):
            for gy in range(math.floor((lat - r_deg) / GRID), math.floor((lat + r_deg) / GRID) + 1):
                for ei in self._grid.get((gx, gy), ()):
                    if ei not in found and geo.point_polyline_m(lon, lat, self.geometry(ei)) <= radius_m:
                        found.add(ei)
        return found

    # ---------- adjacency ----------
    def adjacency(self, vehicle: str) -> dict:
        """node -> [(neighbour, edge_index, reversed)] for this vehicle's access profile."""
        classes, respect_oneway = ACCESS[vehicle]
        key = (frozenset(classes), respect_oneway)
        if key not in self._adj_cache:
            adj: dict = {}
            for i, (u, v, _, cls, flags, _) in enumerate(self.edges):
                if cls not in classes:
                    continue
                adj.setdefault(u, []).append((v, i, False))
                if not (respect_oneway and flags & ONEWAY):
                    adj.setdefault(v, []).append((u, i, True))
            self._adj_cache[key] = adj
        return self._adj_cache[key]

    def core(self, vehicle: str) -> set[int]:
        """Nodes of the big strongly connected components for this vehicle's profile (one per covered
        area), so a start/end point is never snapped onto a one-way stub with no way in or out."""
        adj = self.adjacency(vehicle)
        key = id(adj)
        if key in self._core_cache:
            return self._core_cache[key]
        # Kosaraju, iterative (no recursion limits on big graphs)
        order, seen = [], set()
        for start in adj:
            if start in seen:
                continue
            seen.add(start)
            stack = [(start, iter(adj.get(start, ())))]
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    order.append(node)
                    stack.pop()
                elif nxt[0] not in seen:
                    seen.add(nxt[0])
                    stack.append((nxt[0], iter(adj.get(nxt[0], ()))))
        radj: dict = {}
        for u, outs in adj.items():
            for v, _, _ in outs:
                radj.setdefault(v, []).append(u)
        comp_of, comps = {}, []
        for root in reversed(order):
            if root in comp_of:
                continue
            comp, stack = {root}, [root]
            comp_of[root] = root
            while stack:
                u = stack.pop()
                for w in radj.get(u, ()):
                    if w not in comp_of:
                        comp_of[w] = root
                        comp.add(w)
                        stack.append(w)
            comps.append(comp)
        largest = max((len(c) for c in comps), default=0)
        keep = [c for c in comps if len(c) == largest or (len(c) >= MIN_AREA_NODES and len(c) >= largest * 0.05)]
        core = set().union(*keep) if keep else set()
        self._core_cache[key] = core
        self._comp_cache[key] = {n: i for i, c in enumerate(keep) for n in c}
        return core

    def same_area(self, a: int, b: int, vehicle: str) -> bool:
        """Both nodes in the same covered road network (a route between them can exist)."""
        self.core(vehicle)
        comp = self._comp_cache[id(self.adjacency(vehicle))]
        return comp.get(a) == comp.get(b)

    def nearest_node(self, lon, lat, vehicle: str) -> tuple[int, float]:
        k = math.cos(math.radians(lat))
        best, best_d = -1, float("inf")
        for n in self.core(vehicle):
            x, y = self.nodes[n]
            d = ((x - lon) * k) ** 2 + (y - lat) ** 2
            if d < best_d:
                best, best_d = n, d
        if best < 0:
            raise ValueError("graph has no usable roads for this vehicle")
        return best, geo.haversine_m(lon, lat, *self.nodes[best])

    # ---------- search ----------
    def astar(self, src: int, dst: int, vehicle: str, cost_mult: dict[int, float] | None = None,
              blocked: set[int] | None = None):
        """Returns list of (edge_index, reversed) or None. cost_mult: edge -> length multiplier."""
        adj = self.adjacency(vehicle)
        cost_mult = cost_mult or {}
        blocked = blocked or set()
        tx, ty = self.nodes[dst]

        def h(n):
            x, y = self.nodes[n]
            return geo.haversine_m(x, y, tx, ty)

        g = {src: 0.0}
        prev: dict = {}
        pq = [(h(src), 0.0, src)]
        done = set()
        while pq:
            _, gc, n = heapq.heappop(pq)
            if n in done:
                continue
            if n == dst:
                path = []
                while n != src:
                    p, ei, rev = prev[n]
                    path.append((ei, rev))
                    n = p
                return path[::-1]
            done.add(n)
            for m, ei, rev in adj.get(n, ()):
                if ei in blocked or m in done:
                    continue
                nc = gc + self.edges[ei][2] * cost_mult.get(ei, 1.0)
                if nc < g.get(m, float("inf")):
                    g[m] = nc
                    prev[m] = (n, ei, rev)
                    heapq.heappush(pq, (nc + h(m), nc, m))
        return None

    def path_geojson(self, path) -> dict:
        coords = []
        for ei, rev in path:
            seg = self.geometry(ei)
            seg = seg[::-1] if rev else seg
            coords.extend(seg if not coords else seg[1:])
        return {"type": "LineString", "coordinates": coords}

    def path_length(self, path) -> float:
        return sum(self.edges[ei][2] for ei, _ in path)


def spot_edges(graph: Graph, spots: list[dict], vehicle: str) -> tuple[set, dict, dict]:
    """For the chosen vehicle: (blocked edges, risky edge multipliers, edge -> [spotIds])."""
    blocked, risky, edge_spots = set(), {}, {}
    for s in spots:
        verdict = s["verdicts"].get(vehicle, "GO")
        if verdict == "GO":
            continue
        for ei in graph.edges_near(s["lon"], s["lat"], config.EDGE_BLOCK_RADIUS_M):
            edge_spots.setdefault(ei, []).append(s["spotId"])
            if verdict == "NO_GO":
                blocked.add(ei)
            else:
                risky[ei] = config.RISKY_PENALTY
    return blocked, risky, edge_spots


def plan(graph: Graph, frm, to, vehicle: str, spots: list[dict]) -> dict:
    """Compute the normal shortest route and the flood-safe route for one vehicle."""
    src, d_src = graph.nearest_node(frm[0], frm[1], vehicle)
    dst, d_dst = graph.nearest_node(to[0], to[1], vehicle)
    speed = config.SPEED_KMH[vehicle] * 1000 / 60  # m/min
    blocked, risky, edge_spots = spot_edges(graph, spots, vehicle)
    by_id = {s["spotId"]: s for s in spots}

    def summary(path):
        ids = []
        for ei, _ in path:
            for sid in edge_spots.get(ei, []):
                if sid not in ids:
                    ids.append(sid)
        dist = graph.path_length(path)
        return {
            "geometry": graph.path_geojson(path),
            "distance_m": round(dist),
            "duration_min": round(dist / speed, 1),
            "spots_on_route": [{"spotId": i, "verdict": by_id[i]["verdicts"][vehicle],
                                "place": by_id[i].get("place"), "depth_high": by_id[i]["depth_high"],
                                "lon": by_id[i]["lon"], "lat": by_id[i]["lat"]} for i in ids],
        }

    out = {"vehicle": vehicle, "snap_m": [round(d_src), round(d_dst)], "normal": None, "safe": None,
           "avoided_spots": [], "extra_min": 0, "note": "", "out_of_area": False}
    # Coverage first: two far-away taps snap to the same edge node, which is NOT "the same place".
    # Measured to ANY road (pedestrian profile): a bus stop 600 m from campus is still covered.
    if max(graph.nearest_node(*frm, "pedestrian")[1], graph.nearest_node(*to, "pedestrian")[1]) > OUT_OF_AREA_M:
        out["out_of_area"] = True
        out["note"] = "This trip is outside the area we have road data for."
        return out
    if not graph.same_area(src, dst, vehicle):
        out["out_of_area"] = True
        out["note"] = "Start and destination are in different areas we cover; we can't route between them yet."
        return out
    if src == dst:
        out["note"] = "Start and destination are the same place."
        return out

    normal = graph.astar(src, dst, vehicle)
    if normal is None:
        out["note"] = "No road connection found between these points for this vehicle."
        return out
    out["normal"] = summary(normal)
    flooded_on_normal = out["normal"]["spots_on_route"]

    if not flooded_on_normal:
        out["safe"] = out["normal"]
        out["note"] = "No flooded spots reported on your route."
        return out

    safe = graph.astar(src, dst, vehicle, cost_mult=risky, blocked=blocked)
    if safe is None:
        out["note"] = (f"No dry route found for a {vehicle}. Wait for the water to go down, "
                       f"or try a bigger vehicle (car/SUV).")
        return out
    out["safe"] = summary(safe)
    safe_ids = {s["spotId"] for s in out["safe"]["spots_on_route"]}
    out["avoided_spots"] = [s for s in flooded_on_normal if s["spotId"] not in safe_ids]
    if not out["avoided_spots"]:
        # Every alternative still passes the same (risky) spots: the shortest route is best.
        out["safe"] = out["normal"]
        out["note"] = (f"No way around {len(flooded_on_normal)} risky spot(s) on this route. "
                       f"Go slowly, or wait for the water to go down.")
        return out
    out["extra_min"] = round(out["safe"]["duration_min"] - out["normal"]["duration_min"], 1)
    n = len(out["avoided_spots"])
    still_risky = [s for s in out["safe"]["spots_on_route"] if s["verdict"] == "RISKY"]
    note = f"Avoids {n} flooded spot{'s' if n != 1 else ''}, +{max(out['extra_min'], 0):g} min."
    if still_risky:
        note += f" Still passes {len(still_risky)} risky spot(s): go slowly."
    out["note"] = note
    return out


def compare(graph: Graph, frm, to, spots: list[dict], vehicles=COMPARE_VEHICLES) -> list[dict]:
    """Same trip for several vehicles: who can take the usual route, who must detour, who is stuck.

    Answers "the scooter is rerouted, but can a car still go the usual way?"
    """
    out = []
    for v in vehicles:
        try:
            r = plan(graph, frm, to, v, spots)
        except ValueError:
            continue
        if r["out_of_area"]:
            return []  # a coverage problem, not a per-vehicle verdict
        if not r["normal"]:
            out.append({"vehicle": v, "status": "stuck", "usual_km": 0, "usual_min": 0, "safe_km": None,
                        "safe_min": None, "extra_min": 0, "blocking": [], "risky": [], "note": r["note"],
                        "geometry": None})
            continue
        blocking = [s for s in r["normal"]["spots_on_route"] if s["verdict"] == "NO_GO"]
        risky = [s for s in r["normal"]["spots_on_route"] if s["verdict"] == "RISKY"]
        if r["safe"] is None:
            status = "stuck"
        elif r["avoided_spots"]:
            status = "detour"
        elif risky:
            status = "usual_with_care"
        else:
            status = "usual"
        out.append({
            "vehicle": v, "status": status,
            "usual_km": round(r["normal"]["distance_m"] / 1000, 1),
            "usual_min": r["normal"]["duration_min"],
            "safe_km": round(r["safe"]["distance_m"] / 1000, 1) if r["safe"] else None,
            "safe_min": r["safe"]["duration_min"] if r["safe"] else None,
            "extra_min": r["extra_min"],
            "blocking": [s.get("place") or "flooded spot" for s in blocking],
            "risky": [s.get("place") or "flooded spot" for s in risky],
            "note": r["note"],
            "geometry": (r["safe"] or r["normal"])["geometry"],
        })
    return out
