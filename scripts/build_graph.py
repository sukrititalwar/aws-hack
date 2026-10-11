"""Download the OSM street network for the demo area with OSMnx and export the compact JSON
graph used by backend/common/routing.py (server) and, later, the PWA (offline routing).

Includes residential / service / unclassified roads and paths, i.e. the galis that
navigation apps have no waterlogging data for.

  pip install -r scripts/requirements.txt
  python scripts/build_graph.py --city mumbai                 # writes data/graphs/mumbai.json.gz
  python scripts/build_graph.py --city mumbai --bucket <PhotosBucketName>   # and uploads to S3
"""
import argparse
import gzip
import json
import os
import sys

# Andheri - Vile Parle - Santacruz West: covers Andheri subway and Milan subway plus the lanes
# around them. ~4.7 km x 6 km. Keep it small so Lambda cold starts stay fast.
# A city can have several separate areas; each becomes its own routable network in one graph file.
# The names are shown to users when a trip falls outside coverage. bbox = (west, south, east, north).
AREAS = {
    "mumbai": [("Andheri, Vile Parle, Santacruz West", (72.825, 19.075, 72.870, 19.130))],
    "delhi": [
        ("Central Delhi: Minto Bridge, ITO, Pragati Maidan, Moolchand", (77.195, 28.555, 77.265, 28.645)),
        ("North-west Delhi: DTU, Rohini, Samaypur Badli", (77.095, 28.715, 77.165, 28.770)),
    ],
    "gurugram": [("Hero Honda Chowk, Rajiv Chowk, IFFCO, Golf Course Rd", (77.000, 28.420, 77.110, 28.510))],
    "kochi": [("MG Road, Kaloor, Edappally, Vyttila", (76.270, 9.950, 76.325, 10.035))],
    "thiruvananthapuram": [("Thampanoor, Chalai, Vanchiyoor, Pattoor, Pattom", (76.915, 8.465, 76.975, 8.535))],
    "bengaluru": [("Silk Board", (77.600, 12.905, 77.645, 12.935))],
}

# Must match backend/common/routing.py
CLASS = {
    "motorway": 0, "motorway_link": 0,
    "trunk": 1, "trunk_link": 1, "primary": 1, "primary_link": 1, "secondary": 1, "secondary_link": 1,
    "tertiary": 2, "tertiary_link": 2, "busway": 2,                       # bus-capable
    "residential": 3, "unclassified": 3, "living_street": 3, "service": 3, "road": 3,  # galis
    "track": 4, "path": 4,
}  # everything else (footway, pedestrian, steps, cycleway, corridor, ...) -> 5 (foot only)

ONEWAY, TUNNEL, BRIDGE = 1, 2, 4
SKIP_SERVICE = {"parking_aisle", "parking", "driveway", "drive-through", "emergency_access"}
UNDERPASS_WORDS = ("subway", "underpass", "under pass", "tunnel")


def first(x):
    return x[0] if isinstance(x, list) else x


def truthy(x):
    x = first(x)
    return x not in (None, False, "no", "0", "") and str(x).lower() != "nan"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="mumbai", choices=sorted(AREAS))
    ap.add_argument("--bucket", help="upload to s3://<bucket>/graphs/<city>.json.gz")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "data", "graphs"))
    ap.add_argument("--skip-bus", action="store_true", help="don't fetch OSM bus routes (slow for big areas)")
    args = ap.parse_args()

    import osmnx as ox
    ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["tunnel", "bridge", "layer", "covered", "name", "service", "access"]))

    import networkx as nx
    areas = AREAS[args.city]
    west, south = min(b[0] for _, b in areas), min(b[1] for _, b in areas)
    east, north = max(b[2] for _, b in areas), max(b[3] for _, b in areas)
    graphs = []
    for name, bbox in areas:
        print(f"Downloading OSM network for {args.city} / {name} bbox {bbox} ...")
        # OSMnx's "all" network (galis included); parking aisles, driveways and private roads are
        # dropped below. (A custom_filter silently lost most residential lanes, so filter in Python.)
        graphs.append(ox.graph_from_bbox(bbox=bbox, network_type="all", simplify=True, retain_all=False))
    G = nx.compose_all(graphs) if len(graphs) > 1 else graphs[0]  # OSM node ids are shared, so overlaps merge
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} directed edges")

    idx = {n: i for i, n in enumerate(G.nodes)}
    nodes = [[round(G.nodes[n]["x"], 6), round(G.nodes[n]["y"], 6)] for n in G.nodes]
    edges, underpasses = [], []
    for u, v, data in G.edges(data=True):
        if u == v:
            continue
        if str(first(data.get("service")) or "") in SKIP_SERVICE or str(first(data.get("access")) or "") in ("private", "no"):
            continue
        oneway = truthy(data.get("oneway"))
        if not oneway and idx[u] > idx[v] and G.has_edge(v, u):
            continue  # two-way road: keep one copy, routing adds the reverse direction
        hw = first(data.get("highway"))
        cls = CLASS.get(hw, 5)
        name = str(first(data.get("name")) or "")
        flags = ONEWAY if oneway else 0
        layer = first(data.get("layer"))
        try:
            low_layer = int(float(layer)) < 0
        except (TypeError, ValueError):
            low_layer = False
        if truthy(data.get("tunnel")) or truthy(data.get("covered")) or low_layer \
                or any(w in name.lower() for w in UNDERPASS_WORDS):
            flags |= TUNNEL
        if truthy(data.get("bridge")):
            flags |= BRIDGE
        geom = None
        if "geometry" in data:
            geom = [[round(x, 6), round(y, 6)] for x, y in data["geometry"].coords]
        edges.append([idx[u], idx[v], round(float(data["length"]), 1), cls, flags, geom])
        if flags & TUNNEL:
            g = geom or [nodes[idx[u]], nodes[idx[v]]]
            underpasses.append({"type": "Feature", "properties": {"name": name or "Underpass", "highway": hw},
                                "geometry": {"type": "LineString", "coordinates": g}})

    out = {"city": args.city, "bbox": [west, south, east, north],
           "areas": [{"name": name, "bbox": list(bbox)} for name, bbox in areas],
           "source": "© OpenStreetMap contributors (ODbL)", "nodes": nodes, "edges": edges}
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"{args.city}.json.gz")
    raw = json.dumps(out, separators=(",", ":")).encode()
    with open(path, "wb") as f:
        f.write(gzip.compress(raw, 9))
    upath = os.path.join(os.path.dirname(__file__), "..", "data", f"underpasses_{args.city}.geojson")
    with open(upath, "w") as f:
        json.dump({"type": "FeatureCollection", "features": underpasses}, f)
    by_cls = {c: sum(1 for e in edges if e[3] == c) for c in range(6)}
    print(f"  wrote {path}: {len(nodes)} nodes, {len(edges)} edges, {os.path.getsize(path) / 1e6:.1f} MB gz")
    print(f"  edges by class (0 motorway,1 major,2 tertiary,3 gali,4 track,5 foot): {by_cls}")
    print(f"  {len(underpasses)} underpass/tunnel segments -> {upath}")

    bpath = os.path.join(os.path.dirname(__file__), "..", "data", f"bus_routes_{args.city}.json")
    try:
        if args.skip_bus:
            raise RuntimeError("--skip-bus")
        routes = fetch_bus_routes(west, south, east, north)
        json.dump({"city": args.city, "source": "© OpenStreetMap contributors (ODbL)", "routes": routes},
                  open(bpath, "w"), separators=(",", ":"))
        print(f"  {len(routes)} OSM bus routes -> {bpath}")
    except Exception as e:  # Overpass is flaky; keep the previous file if any
        print(f"  bus routes skipped ({e}); re-run later")

    if args.bucket:
        import boto3
        s3 = boto3.client("s3")
        s3.upload_file(path, args.bucket, f"graphs/{args.city}.json.gz",
                       ExtraArgs={"ContentType": "application/json", "ContentEncoding": "gzip"})
        print(f"  uploaded to s3://{args.bucket}/graphs/{args.city}.json.gz")
        if os.path.exists(bpath):
            s3.upload_file(bpath, args.bucket, f"bus/{args.city}.json", ExtraArgs={"ContentType": "application/json"})
            print(f"  uploaded to s3://{args.bucket}/bus/{args.city}.json")


def fetch_bus_routes(west, south, east, north):
    """OSM route=bus relations in the bbox via Overpass: ref, name, operator and their way geometry
    (clipped to the bbox), so we can tell which bus lines pass a flooded spot."""
    import time
    import urllib.parse
    import urllib.request
    q = (f'[out:json][timeout:120];relation["route"="bus"]({south},{west},{north},{east});'
         f'out tags geom({south},{west},{north},{east});')
    last = None
    for host in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        for attempt in range(2):
            try:
                req = urllib.request.Request(host, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "CanMyScooterCross/0.1 (hackathon)"})
                els = json.loads(urllib.request.urlopen(req, timeout=180).read())["elements"]
                break
            except Exception as e:
                last = e
                time.sleep(5)
        else:
            continue
        break
    else:
        raise RuntimeError(last)
    routes = []
    for r in els:
        t = r.get("tags", {})
        lines = [[[round(p["lon"], 5), round(p["lat"], 5)] for p in m["geometry"] if p]
                 for m in r.get("members", []) if m.get("type") == "way" and m.get("geometry")]
        lines = [l for l in lines if len(l) >= 2]
        if lines:
            routes.append({"id": r["id"], "ref": t.get("ref", ""), "name": t.get("name", ""),
                           "operator": t.get("operator", ""), "lines": lines})
    return routes


if __name__ == "__main__":
    sys.exit(main())
