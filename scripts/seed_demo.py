"""Seed demo-mode reports from archived monsoon photos, through the REAL Bedrock pipeline.

Each row of data/demo_photos.csv is analysed by Bedrock + the rules engine (results cached in
data/demo_cache/ so re-seeding is instant and free), the photo is uploaded to S3 under demo/,
and a report is written with mode=demo and ts = its replay time on the timeline.

  python scripts/seed_demo.py --bucket <PhotosBucketName> --table <ReportsTableName>

Before you have photos, test the map and routing with clearly-labelled SYNTHETIC points placed
on real roads of the routing graph (never use these in the video):

  python scripts/seed_demo.py --bucket .. --table .. --synthetic 12

  --wipe  deletes existing demo reports for the city first.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import sys
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from common import config, db, depth, geo, pipeline  # noqa: E402

CACHE_DIR = os.path.join(ROOT, "data", "demo_cache")


def cached_assessment(photo_path: str, city: str, place: str) -> dict:
    data = open(photo_path, "rb").read()
    h = hashlib.sha256(data + config.BEDROCK_MODEL_ID.encode()).hexdigest()[:16]
    cpath = os.path.join(CACHE_DIR, f"{h}.json")
    if os.path.exists(cpath):
        return json.load(open(cpath, encoding="utf-8"))
    print(f"  Bedrock -> {os.path.basename(photo_path)} ...", flush=True)
    a, metrics = depth.estimate_depth(data, city, place)
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump({"assessment": a, "metrics": metrics}, open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"    {a['depth_cm_low']:.0f}-{a['depth_cm_high']:.0f} cm, {a['confidence']}, {metrics.get('latency_ms')} ms")
    return {"assessment": a, "metrics": metrics}


def wipe(table, city):
    items = db.query_city(city, "demo")
    with table.batch_writer() as bw:
        for it in items:
            bw.delete_item(Key={"reportId": it["reportId"]})
    print(f"deleted {len(items)} existing demo reports")


def demo_item(rid, city, lat, lon, place, ts, fields, **extra):
    item = {"reportId": rid, "city": city, "mode": "demo", "cell": db.cell_key("demo", city, lat, lon),
            "cityMode": f"demo#{city}", "lat": lat, "lon": lon, "place": place, "createdAt": ts, "ts": ts,
            "demoReplayTime": datetime.fromtimestamp(ts).astimezone().isoformat(),
            "source_type": "photo", "votes": {"still": 0, "cleared": 0, "wrong": 0}}
    item.update(fields)
    item.update(extra)
    return item


def seed_photos(args, s3, table):
    path = os.path.join(ROOT, "data", "demo_photos.csv")
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r.get("file") and not r["file"].startswith("#")]
    n = 0
    for r in rows:
        if r["city"].lower() != args.city:
            continue
        photo = os.path.join(ROOT, "data", "demo_photos", r["file"])
        if not os.path.exists(photo):
            print(f"  missing {photo}, skipped")
            continue
        res = cached_assessment(photo, args.city, r["place"])
        fields = pipeline.fields_from_assessment(res["assessment"])
        if fields["status"] != "live":
            print(f"  {r['file']}: rejected by model ({fields.get('rejection_reason')}), skipped")
            continue
        rid = "demo-" + hashlib.sha1(r["file"].encode()).hexdigest()[:10]
        key = f"demo/photos/{rid}.jpg"
        img, _ = depth.prepare_image(open(photo, "rb").read())
        s3.put_object(Bucket=args.bucket, Key=key, Body=img, ContentType="image/jpeg")
        ts = int(datetime.fromisoformat(r["replay_time"]).timestamp())
        table.put_item(Item=db.to_ddb(demo_item(
            rid, args.city, float(r["lat"]), float(r["lon"]), r["place"], ts, fields,
            s3Key=key, source_url=r.get("source"), source_label=r.get("licence"), metrics=res["metrics"])))
        n += 1
    print(f"seeded {n} demo photo reports")


def seed_synthetic(args, table):
    """Random points ON real roads (so routing reacts), clearly marked synthetic."""
    gpath = os.path.join(ROOT, "data", "graphs", f"{args.city}.json.gz")
    g = json.loads(gzip.decompress(open(gpath, "rb").read()))
    rnd = random.Random(42)
    roads = [e for e in g["edges"] if e[3] in (1, 2) and e[2] > 60]
    start = int(datetime.fromisoformat(args.start).timestamp())
    for i in range(args.synthetic):
        e = rnd.choice(roads)
        coords = e[5] or [g["nodes"][e[0]], g["nodes"][e[1]]]
        lon, lat = coords[len(coords) // 2]
        hi = rnd.choice([8, 14, 18, 25, 30, 35, 45, 60])
        a = depth.normalise({"is_flooded_road_photo": True, "depth_cm_low": max(hi - 10, 0), "depth_cm_high": hi,
                             "confidence": rnd.choice(["medium", "high"]), "image_quality": "good",
                             "reasoning": f"SYNTHETIC test point ({hi} cm). Not a real report.",
                             "reasoning_hi": "परीक्षण बिंदु। असली रिपोर्ट नहीं।",
                             "flowing_water": False, "hazards": [], "location_type": "main_road"})
        fields = pipeline.fields_from_assessment(a)
        ts = start + i * 15 * 60  # one every 15 minutes
        table.put_item(Item=db.to_ddb(demo_item(f"synth-{i:03d}", args.city, lat, lon,
                                                f"Synthetic point {i + 1}", ts, fields,
                                                synthetic=True, source_label="synthetic")))
    print(f"seeded {args.synthetic} SYNTHETIC demo reports starting {args.start}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="delhi")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--synthetic", type=int, default=0)
    ap.add_argument("--start", default="2025-07-26T18:00:00+05:30", help="synthetic timeline start")
    ap.add_argument("--wipe", action="store_true")
    args = ap.parse_args()

    config.REPORTS_TABLE = args.table
    table = boto3.resource("dynamodb").Table(args.table)
    if args.wipe:
        wipe(table, args.city)
    if args.synthetic:
        seed_synthetic(args, table)
    else:
        seed_photos(args, boto3.client("s3"), table)


if __name__ == "__main__":
    main()
