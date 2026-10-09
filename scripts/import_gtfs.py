"""Convert a GTFS static zip into data/bus_routes_<city>.json (route lines clipped to the city's
routing area). Uses shapes.txt when present, otherwise the stop sequence of one trip per
route and direction.

Delhi (DTC + cluster buses): https://mobilitydatabase.org/feeds/gtfs/mdb-3139 or otd.delhi.gov.in
  python scripts/import_gtfs.py --city delhi --gtfs ~/Downloads/delhi-bus.zip [--bucket <PhotosBucketName>]
"""
import argparse
import csv
import io
import json
import os
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from build_graph import AREAS  # noqa: E402


def read(z, name):
    if name not in z.namelist():
        return None
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))


def clip(points, bbox, margin=0.005):
    """Split a polyline into the runs that fall inside the bbox."""
    w, s, e, n = bbox
    runs, cur = [], []
    for x, y in points:
        if w - margin <= x <= e + margin and s - margin <= y <= n + margin:
            cur.append([round(x, 5), round(y, 5)])
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def convert(gtfs_path: str, bbox) -> list[dict]:
    z = zipfile.ZipFile(gtfs_path)
    routes = {r["route_id"]: r for r in read(z, "routes.txt")}
    trips = read(z, "trips.txt")
    shapes_rows = read(z, "shapes.txt")
    # one representative trip per (route, direction)
    rep = {}
    for t in trips:
        rep.setdefault((t["route_id"], t.get("direction_id", "0")), t)
    lines_by_route = defaultdict(list)
    if shapes_rows:
        shapes = defaultdict(list)
        for r in shapes_rows:
            shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
        for (rid, _), t in rep.items():
            pts = [(x, y) for _, x, y in sorted(shapes.get(t.get("shape_id", ""), []))]
            lines_by_route[rid].extend(clip(pts, bbox))
    else:
        stops = {s["stop_id"]: (float(s["stop_lon"]), float(s["stop_lat"])) for s in read(z, "stops.txt")}
        want = {t["trip_id"]: t["route_id"] for t in rep.values()}
        seqs = defaultdict(list)
        with z.open("stop_times.txt") as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                if r["trip_id"] in want and r["stop_id"] in stops:
                    seqs[r["trip_id"]].append((int(r["stop_sequence"]), stops[r["stop_id"]]))
        for tid, rid in want.items():
            pts = [p for _, p in sorted(seqs.get(tid, []))]
            lines_by_route[rid].extend(clip(pts, bbox))
    out = []
    for rid, lines in lines_by_route.items():
        if not lines:
            continue
        r = routes.get(rid, {})
        out.append({"id": rid, "ref": r.get("route_short_name") or rid, "name": r.get("route_long_name", ""),
                    "operator": r.get("agency_id", ""), "lines": lines})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True, choices=sorted(AREAS))
    ap.add_argument("--gtfs", required=True)
    ap.add_argument("--bucket")
    args = ap.parse_args()
    routes = convert(args.gtfs, AREAS[args.city])
    path = os.path.join(os.path.dirname(__file__), "..", "data", f"bus_routes_{args.city}.json")
    json.dump({"city": args.city, "source": f"GTFS: {os.path.basename(args.gtfs)}", "routes": routes},
              open(path, "w"), separators=(",", ":"))
    print(f"{len(routes)} bus routes cross the {args.city} routing area -> {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    if args.bucket:
        import boto3
        boto3.client("s3").upload_file(path, args.bucket, f"bus/{args.city}.json", ExtraArgs={"ContentType": "application/json"})
        print(f"uploaded to s3://{args.bucket}/bus/{args.city}.json")


if __name__ == "__main__":
    main()
