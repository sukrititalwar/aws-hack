"""S3 put -> classify the drain photo with Bedrock -> group duplicates -> store.

  drains/<reportId>.jpg        a resident's report: severity + type, grouped with open reports
                               within 30 m, forecast rain stored for prioritisation
  drains-after/<groupId>.jpg   a field worker's after-photo: the blockage is only marked cleared
                               if the photo itself shows a clear drain (evidence, not a button)
"""
import logging
import time
import urllib.parse

import boto3

from common import config, db, depth, drain_store, drains, views, weather

log = logging.getLogger()
log.setLevel(logging.INFO)
rek = boto3.client("rekognition", region_name=config.REGION)


def _unsafe(bucket, key):
    labels = rek.detect_moderation_labels(Image={"S3Object": {"Bucket": bucket, "Name": key}},
                                          MinConfidence=80).get("ModerationLabels", [])
    return labels[0]["Name"] if labels else None


def _rejected(report_id, reason):
    drain_store.update(report_id, {"status": "rejected", "rejection_reason": reason})


def report(bucket, key):
    rid = key.rsplit("/", 1)[-1].split(".")[0]
    r = drain_store.get(rid)
    if not r or r.get("status") != "analysing":
        return
    try:
        if _unsafe(bucket, key):
            return _rejected(rid, "The photo was flagged as unsafe content.")
        img = views.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        a, metrics = depth.classify_drain(img, r["city"])
        if not a["is_drain_photo"]:
            return _rejected(rid, a.get("rejection_reason") or "No drain is visible in this photo.")
        if a["severity"] == "clear":
            return _rejected(rid, "This drain looks clear, so no work is needed.")
        existing = drain_store.for_city(r["city"])
        gid = drains.find_group(r, existing) or rid
        rain = weather.next24h_mm(r["lat"], r["lon"])
        drain_store.update(rid, {
            "status": "open", "severity": a["severity"], "blockage_type": a.get("blockage_type"),
            "standing_water": bool(a.get("standing_water")), "confidence": a["confidence"],
            "reasoning": a.get("reasoning", ""), "reasoning_hi": a.get("reasoning_hi", ""),
            "groupId": gid, "rainNext24h": rain, "metrics": metrics})
        if gid != rid:  # join an existing open blockage: adopt its status
            head = next((m for m in existing if m["reportId"] == gid), None)
            if head and head.get("status") == "assigned":
                drain_store.update(rid, {"status": "assigned", "assignedTo": head.get("assignedTo"),
                                         "assignedAt": head.get("assignedAt")})
    except Exception as e:  # never leave a report stuck in "analysing"
        log.exception("drain analysis failed for %s", rid)
        _rejected(rid, f"Analysis failed: {type(e).__name__}")


def after(bucket, key):
    gid = key.rsplit("/", 1)[-1].split(".")[0]
    head = drain_store.get(gid)
    if not head:
        return
    try:
        img = views.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        a, _ = depth.classify_drain(img, head["city"])
        fields = {"afterKey": key, "afterSeverity": a["severity"], "afterReasoning": a.get("reasoning", "")}
        if a["is_drain_photo"] and a["severity"] == "clear" and a["confidence"] != "low":
            fields.update({"status": "cleared", "clearedAt": int(time.time()), "clearanceVerified": True})
        else:
            fields.update({"afterRejected": True,
                           "afterNote": "The after photo does not clearly show a cleared drain. Send another photo."})
        drain_store.update_group(head["city"], head.get("groupId") or gid, fields)
    except Exception:
        log.exception("after-photo analysis failed for %s", gid)


def handler(event, _ctx):
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        (after if key.startswith("drains-after/") else report)(bucket, key)
