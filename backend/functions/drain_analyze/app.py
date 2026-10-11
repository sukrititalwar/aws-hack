"""S3 put -> classify the drain photo -> group duplicates -> store. Never fails silently.

  drains/<reportId>.jpg        a resident's report
  drains-after/<groupId>.jpg   a worker's after-photo

Analysis order: Bedrock (full AI) -> Amazon Rekognition labels (clearly labelled, low confidence,
"needs review") -> unrated manual queue. A resident's report is never dropped because an AI
service failed, and an after-photo only clears a drain when AI verification succeeds. Otherwise
it waits for a dispatcher to confirm it (labelled "manual").
"""
import logging
import time
import urllib.parse

import boto3

from common import config, depth, drain_store, drains, fallback, views, weather

log = logging.getLogger()
log.setLevel(logging.INFO)
rek = boto3.client("rekognition", region_name=config.REGION)


def _unsafe(bucket, key):
    labels = rek.detect_moderation_labels(Image={"S3Object": {"Bucket": bucket, "Name": key}},
                                          MinConfidence=80).get("ModerationLabels", [])
    return labels[0]["Name"] if labels else None


def _fail(rid, reason, status="rejected", **extra):
    drain_store.update(rid, {"status": status, "rejection_reason": reason, **extra})


def assess_report(bucket, key, img, city):
    """-> (assessment, metrics). Falls back, never raises for AI problems."""
    try:
        a, metrics = depth.classify_drain(img, city)
        a["analysisMode"] = "bedrock"
        return a, metrics
    except (depth.AIUnavailable, ValueError) as e:
        err = str(e)[:300]
        log.error("Bedrock unavailable for drain report, using fallback: %s", err)
    try:
        return fallback.rate_report(fallback.labels_for(bucket, key), err), {"fallback": "rekognition_labels"}
    except Exception as e2:
        log.error("Rekognition fallback failed too: %s", e2)
        return fallback.unrated_report(f"{err} | labels: {type(e2).__name__}: {str(e2)[:120]}"), {"fallback": "manual"}


def report(bucket, key):
    rid = key.rsplit("/", 1)[-1].split(".")[0]
    r = drain_store.get(rid)
    if not r or r.get("status") != "analysing":
        return  # duplicate S3 event, or already processed
    try:
        try:
            if _unsafe(bucket, key):
                return _fail(rid, "The photo was flagged as unsafe content.")
        except Exception as e:  # moderation is best effort: do not lose a report because of it
            log.warning("moderation skipped: %s", e)
        img = views.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        a, metrics = assess_report(bucket, key, img, r["city"])
        mode = a["analysisMode"]
        if mode == "bedrock":
            if not a["is_drain_photo"]:
                return _fail(rid, a.get("rejection_reason") or "No drain is visible in this photo.", analysisMode=mode)
            if a["severity"] == "clear":
                return _fail(rid, "This drain looks clear, so no work is needed.", analysisMode=mode)
        existing = drain_store.for_city(r["city"])
        gid = drains.find_group(r, existing) or rid
        fields = {
            "status": "open", "severity": a["severity"], "blockage_type": a.get("blockage_type"),
            "standing_water": bool(a.get("standing_water")), "confidence": a["confidence"],
            "reasoning": a.get("reasoning", ""), "reasoning_hi": a.get("reasoning_hi", ""),
            "groupId": gid, "rainNext24h": weather.next24h_mm(r["lat"], r["lon"]), "metrics": metrics,
            "analysisMode": mode, "needsReview": bool(a.get("needsReview")), "analysisError": a.get("analysisError"),
            "analysedAt": int(time.time()),
        }
        head = next((m for m in existing if m["reportId"] == gid and gid != rid), None)
        if head and head.get("status") == "assigned":  # joining a blockage a worker already has
            fields.update({"status": "assigned", "assignedTo": head.get("assignedTo"), "assignedAt": head.get("assignedAt")})
        if not drain_store.update(rid, fields, only_if_status="analysing"):
            log.info("report %s changed while analysing; keeping the newer state", rid)
    except Exception as e:
        log.exception("drain analysis failed for %s", rid)
        _fail(rid, f"Analysis failed ({type(e).__name__}). Tap retry.", status="error", analysisError=str(e)[:300])


def after(bucket, key):
    gid = key.rsplit("/", 1)[-1].split(".")[0]
    head = drain_store.get(gid)
    if not head:
        return
    city = head["city"]
    fields = {"afterKey": key, "afterAt": int(time.time()), "awaitingReview": False, "afterRejected": False}
    try:
        try:
            img = views.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
            a, _ = depth.classify_drain(img, city)
            fields.update({"afterSeverity": a["severity"], "afterReasoning": a.get("reasoning", ""), "afterMode": "bedrock"})
            if a["is_drain_photo"] and a["severity"] == "clear" and a["confidence"] != "low":
                fields.update({"status": "cleared", "clearedAt": int(time.time()), "clearanceVerified": True,
                               "afterNote": "Verified clear by AI from the after-photo."})
            else:
                fields.update({"afterRejected": True,
                               "afterNote": "The after-photo does not clearly show a cleared drain. Send another photo."})
        except (depth.AIUnavailable, ValueError) as e:
            # AI verification is unavailable: NEVER auto-clear. Keep the photo for a dispatcher.
            err = str(e)[:300]
            log.error("Bedrock unavailable for after-photo: %s", err)
            hint = ""
            try:
                _, hint = fallback.after_looks_clear(fallback.labels_for(bucket, key))
            except Exception:
                pass
            fields.update({"afterMode": "manual", "awaitingReview": True, "afterError": err,
                           "afterNote": ("Automatic verification is unavailable, so a dispatcher must confirm this "
                                         "clearance from the photos. " + hint).strip()})
        drain_store.update_group(city, gid, fields)
    except Exception as e:
        log.exception("after-photo handling failed for %s", gid)
        try:
            drain_store.update_group(city, gid, {"afterKey": key, "afterRejected": True,
                                                 "afterNote": f"Could not process the after-photo ({type(e).__name__}). Send it again."})
        except Exception:
            log.exception("could not even record the after-photo failure")


def handler(event, _ctx):
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        (after if key.startswith("drains-after/") else report)(bucket, key)
