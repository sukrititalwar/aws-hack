"""Load data/hotspots_<city>.geojson into the Hotspots DynamoDB table.

  python scripts/seed_hotspots.py --city mumbai --table <HotspotsTableName> [--include-unverified]
"""
import argparse
import json
import os
from decimal import Decimal

import boto3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="delhi")
    ap.add_argument("--table", required=True)
    # tip: run once per city: delhi, gurugram, kochi (and mumbai)
    ap.add_argument("--include-unverified", action="store_true",
                    help="also load points not yet checked against a news source (dev only)")
    args = ap.parse_args()

    path = os.path.join(os.path.dirname(__file__), "..", "data", f"hotspots_{args.city}.geojson")
    fc = json.load(open(path, encoding="utf-8"))
    t = boto3.resource("dynamodb").Table(args.table)
    n = skipped = 0
    for f in fc["features"]:
        p = f["properties"]
        if not p.get("verified") and not args.include_unverified:
            skipped += 1
            continue
        lon, lat = f["geometry"]["coordinates"]
        t.put_item(Item={
            "city": args.city, "hotspotId": p["hotspotId"], "name": p["name"],
            "name_hi": p.get("name_hi", p["name"]), "kind": p.get("kind", "other"),
            "lat": Decimal(str(lat)), "lon": Decimal(str(lon)),
            "source_url": p.get("source_url", ""), "verified": bool(p.get("verified")),
            "aliases": p.get("aliases", []), "osm_match": p.get("osm_match", ""),
            "risk": "normal",
        })
        n += 1
    print(f"loaded {n} hotspots for {args.city} ({skipped} unverified skipped)")


if __name__ == "__main__":
    main()
