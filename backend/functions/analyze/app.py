"""S3 put (uploads/<reportId>.jpg) -> Rekognition moderation -> dedupe -> Bedrock -> rules -> DynamoDB.

Then notifies "watch my route" subscribers if the new report is NO-GO on their route.
"""
import json
import logging
import time
import urllib.parse

import boto3
from boto3.dynamodb.conditions import Key

from common import config, db, depth, geo, pipeline, views
from common import whatsapp as wa

log = logging.getLogger()
log.setLevel(logging.INFO)
rek = boto3.client("rekognition", region_name=config.REGION)
sns = boto3.client("sns", region_name=config.REGION)

MODERATION_MIN_CONF = 80
DUP_HAMMING = 5


def _emf(metrics: dict, status: str):
    """CloudWatch Embedded Metric Format: latency + tokens become real metrics, no extra API calls."""
    print(json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": "CanMyScooterCross", "Dimensions": [["Status"]],
            "Metrics": [{"Name": "ModelLatencyMs", "Unit": "Milliseconds"},
                        {"Name": "InputTokens", "Unit": "Count"},
                        {"Name": "OutputTokens", "Unit": "Count"}]}]},
        "Status": status,
        "ModelLatencyMs": metrics.get("latency_ms", 0),
        "InputTokens": metrics.get("input_tokens", 0),
        "OutputTokens": metrics.get("output_tokens", 0),
        "model": metrics.get("model"), "attempts": metrics.get("attempts"),
    }))


def _unsafe(bucket: str, key: str) -> str | None:
    labels = rek.detect_moderation_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}}, MinConfidence=MODERATION_MIN_CONF
    ).get("ModerationLabels", [])
    return labels[0]["Name"] if labels else None


def _is_duplicate(report: dict, phash: str | None) -> bool:
    """Same (perceptually) photo uploaded in this area during the last 24 h."""
    if not phash:
        return False
    now = time.time()
    t = db.table(config.REPORTS_TABLE)
    items = t.query(IndexName="byCell",
                    KeyConditionExpression=Key("cell").eq(report["cell"])
                    & Key("ts").gte(int(now - 86400))).get("Items", [])
    mine = int(phash, 16)
    for it in items:
        if it["reportId"] != report["reportId"] and it.get("phash"):
            if bin(mine ^ int(it["phash"], 16)).count("1") <= DUP_HAMMING:
                return True
    return False


def _notify_watchers(report: dict, fields: dict):
    """Alert route subscribers whose route passes within 75 m of a new NO-GO report."""
    if fields.get("status") != "live" or not config.ALERTS_TOPIC_ARN:
        return
    subs = db.table(config.SUBSCRIPTIONS_TABLE).scan().get("Items", [])
    for s in map(db.from_ddb, subs):
        v = s.get("vehicle")
        if fields["verdicts"].get(v, {}).get("verdict") != "NO_GO":
            continue
        coords = (s.get("route") or {}).get("coordinates") or []
        if len(coords) < 2 or geo.point_polyline_m(report["lon"], report["lat"], coords) > config.SPOT_RADIUS_M:
            continue
        place = report.get("place") or "a spot"
        msg = (f"New flood report on your route '{s.get('name', 'saved route')}': {place}, "
               f"about {round(fields['depth_high'])} cm. {fields['verdicts'][v]['label_en']}. "
               f"Open the app for a safe route.")
        sns.publish(TopicArn=config.ALERTS_TOPIC_ARN, Message=msg, Subject="Flood on your route",
                    MessageAttributes={"audience": {"DataType": "String", "StringValue": s["subId"]}})


def _reply_whatsapp(report_id: str):
    """If the report came from WhatsApp, send the verdict back, then forget the phone number."""
    r = db.get_report(report_id)
    rt = (r or {}).get("replyTo")
    if not rt:
        return
    try:
        wa.send(rt, rt["to"], wa.verdict_text(r, rt.get("vehicle", "scooter"), rt.get("lang", "en")))
    except Exception:
        log.exception("WhatsApp reply failed for %s", report_id)
    db.table(config.REPORTS_TABLE).update_item(Key={"reportId": report_id}, UpdateExpression="REMOVE replyTo")


def process(bucket: str, key: str):
    try:
        _process(bucket, key)
    finally:
        _reply_whatsapp(key.rsplit("/", 1)[-1].split(".")[0])


def _process(bucket: str, key: str):
    report_id = key.rsplit("/", 1)[-1].split(".")[0]
    report = db.get_report(report_id)
    if not report or report.get("status") != "analysing":
        log.info("skip %s (missing or already processed)", report_id)
        return

    try:
        bad = _unsafe(bucket, key)
        if bad:
            db.update_report(report_id, {"status": "rejected",
                                         "rejection_reason": "The photo was flagged as unsafe content."})
            log.info("moderation rejected %s: %s", report_id, bad)
            return

        image = views.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        phash = depth.dhash(image)
        if _is_duplicate(report, phash):
            db.update_report(report_id, {"status": "rejected", "phash": phash,
                                         "rejection_reason": "This photo was already reported."})
            return

        fields, metrics = pipeline.assess(image, report["city"], report.get("place"))
        fields["phash"] = phash
        fields["metrics"] = metrics

        exif = report.get("exifTime")
        if fields["status"] == "live" and exif and time.time() - exif > config.STALE_PHOTO_H * 3600:
            fields["status"] = "stale"
            fields["rejection_reason"] = "This photo was taken more than 6 hours ago, so it is not shown as live."

        db.update_report(report_id, fields)
        _emf(metrics, fields["status"])
        _notify_watchers(report, fields)
    except Exception as e:  # never leave a report stuck in "analysing"
        log.exception("analyze failed for %s", report_id)
        db.update_report(report_id, {"status": "error", "rejection_reason": f"Analysis failed: {type(e).__name__}"})


def handler(event, _ctx):
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        process(bucket, key)
