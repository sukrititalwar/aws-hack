"""Social/news posts -> reports, outside Lambda.

Dry run on what is being posted RIGHT NOW (no AWS needed with --no-llm):
  python scripts/seed_social.py --city kochi --dry-run --no-llm --hours 72

Write what is being posted right now into the reports table (what the social_ingest Lambda does):
  python scripts/seed_social.py --city kochi --table <ReportsTableName>
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
from common import config, db, social  # noqa: E402


def load_hotspots(city):
    p = os.path.join(ROOT, "data", f"hotspots_{city}.geojson")
    if not os.path.exists(p):
        return []
    return [{**f["properties"], "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
            for f in json.load(open(p, encoding="utf-8"))["features"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True, choices=sorted(config.CITIES))
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="heuristic extraction (local testing only)")
    ap.add_argument("--table")
    args = ap.parse_args()
    hs = load_hotspots(args.city)

    posts, stats = social.fetch_all(args.city, hours=max(24, int(args.hours)))
    cands = social.prefilter(posts, args.city, hs, args.hours)
    print(f"{args.city}: fetched {stats}; {len(cands)} pass the keyword/city/recency filter")

    t = None if args.dry_run else __import__("boto3").resource("dynamodb").Table(args.table)
    n = 0
    for p in cands:
        ext = social.heuristic_extract(p, args.city, hs) if args.no_llm else social.extract(p, args.city)
        ok = ext.get("is_waterlogging_report") and ext.get("is_current", True)
        if not ok:
            loc = None
        elif args.no_llm:  # no Bedrock / Location credentials: hotspot-name matches only
            h = social.match_hotspot(p["text"], hs)
            loc = (h["lon"], h["lat"], h["name"], "hotspot") if h else None
        else:
            loc = social.locate(ext, p["text"], args.city, hs)
        when = datetime.fromtimestamp(p["ts"]).strftime("%d %b %H:%M")
        status = f"-> {loc[2]} ({loc[3]}), depth {ext.get('depth_cm_high')}, closure={ext.get('closure')}" if loc else "-> not used"
        print(f"  [{p['source']:8}] {when} {p['text'][:90]!r} {status}")
        if loc and t is not None:
            t.put_item(Item=db.to_ddb(social.to_report(p, ext, loc, args.city, mode="live")))
            n += 1
    print(f"wrote {n} reports" if t is not None else "dry run: nothing written")


if __name__ == "__main__":
    main()
