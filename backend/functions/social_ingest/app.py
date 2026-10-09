"""EventBridge every 10 min: social media + news -> Bedrock extraction -> geocode -> live reports.

Raw posts are archived to S3 (social/raw/date=YYYY-MM-DD/) for audit. Each post becomes at most
one report (id = hash of its URL), so re-runs never duplicate.
"""
import json
import logging
import time

from botocore.exceptions import ClientError

from common import config, db, social, views

log = logging.getLogger()
log.setLevel(logging.INFO)
MAX_AGE_H = 6          # only posts from the last 6 hours count as live
MAX_EXTRACT_PER_RUN = 30


def ingest_city(city: str, now: float) -> dict:
    hs = [h for h in db.hotspots(city) if not h["hotspotId"].startswith("#")]
    posts, stats = social.fetch_all(city, hours=24)
    views.s3().put_object(
        Bucket=config.DATA_BUCKET,
        Key=f"social/raw/date={time.strftime('%Y-%m-%d', time.gmtime(now))}/{city}-{int(now)}.jsonl",
        Body="\n".join(json.dumps(p, ensure_ascii=False) for p in posts).encode(), ContentType="application/x-ndjson")
    cands = social.prefilter(posts, city, hs, MAX_AGE_H, now)
    t = db.table(config.REPORTS_TABLE)
    written = skipped = 0
    for p in cands[:MAX_EXTRACT_PER_RUN]:
        rid = social.report_id(p)
        if t.get_item(Key={"reportId": rid}, ProjectionExpression="reportId").get("Item"):
            skipped += 1
            continue
        try:
            ext = social.extract(p, city)
        except Exception:
            log.exception("extract failed")
            continue
        if not (ext.get("is_waterlogging_report") and ext.get("is_current", True)):
            continue
        loc = social.locate(ext, p["text"], city, hs)
        if not loc:
            log.info("could not locate %r", ext.get("road_or_landmark"))
            continue
        try:
            t.put_item(Item=db.to_ddb(social.to_report(p, ext, loc, city)),
                       ConditionExpression="attribute_not_exists(reportId)")
            written += 1
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return {"fetched": stats, "candidates": len(cands), "written": written, "already_seen": skipped}


def handler(event, _ctx):
    now = time.time()
    out = {}
    for city in (event or {}).get("cities") or list(config.CITIES):
        try:
            out[city] = ingest_city(city, now)
        except Exception as e:
            log.exception("ingest failed for %s", city)
            out[city] = {"error": str(e)}
    log.info(json.dumps(out))
    return out
