"""DrainReady API.

  POST /drains/upload-url          {lat, lon, city, deviceId, note?} -> presigned S3 POST for the photo
  GET  /drains?city=               blockages ranked by priority (severity x reports x rain x hotspot)
  GET  /drains/metrics?city=       blockages cleared before rain, median time to clear, repeat blockages
  GET  /drains/{groupId}           one blockage with photos
  POST /drains/{id}/retry          re-run analysis if it failed or never started (photo must be in S3)
  POST /drains/{id}/assign         [dispatcher] {worker}
  POST /drains/{id}/after-url      [dispatcher] -> presigned S3 POST for the after-photo; the blockage
                                   is cleared only when AI verification of that photo succeeds
  POST /drains/{id}/confirm        [dispatcher] {decision: clear|reject, note?} manual confirmation
                                   of an after-photo when automatic verification was unavailable
Dispatcher routes need the x-admin-token header (demo-grade shared secret).
"""
import hashlib
import hmac
import time
import uuid

from common import config, db, drain_store, drains, geo, http, ratelimit, views

PER_DEVICE_PER_HOUR = 10
STALE_ANALYSIS_S = 150      # still "analysing" after this long = the analyser never finished


def _admin(event) -> bool:
    tok = (event.get("headers") or {}).get("x-admin-token", "")
    return bool(config.ADMIN_TOKEN) and hmac.compare_digest(tok, config.ADMIN_TOKEN)


def _city(q):
    c = (q.get("city") or "delhi").lower()
    if c not in config.CITIES:
        raise ValueError("unsupported city")
    return c


def _hotspots(city):
    return [h for h in db.hotspots(city) if not h["hotspotId"].startswith("#")]


def upload_url(event):
    b = http.body(event)
    lat, lon, city = b.get("lat"), b.get("lon"), str(b.get("city") or "delhi").lower()
    device = str(b.get("deviceId") or "")[:64]
    if not geo.valid_lonlat(lon, lat):
        return http.bad("lat/lon missing or out of range")
    if city not in config.CITIES:
        return http.bad("unsupported city")
    if len(device) < 8:
        return http.bad("deviceId required")
    if ratelimit.limited("drain", device, PER_DEVICE_PER_HOUR):
        return http.bad("Too many reports from this device. Try again in an hour.", 429)
    rid, now = uuid.uuid4().hex[:16], int(time.time())
    key = f"drains/{rid}.jpg"
    drain_store.put({
        "reportId": rid, "city": city, "lat": float(lat), "lon": float(lon), "ts": now, "status": "analysing",
        "note": (str(b["note"])[:200] if b.get("note") else None), "s3Key": key,
        "deviceHash": hashlib.sha256(device.encode()).hexdigest()[:16],
    })
    post = views.s3().generate_presigned_post(
        Bucket=config.PHOTOS_BUCKET, Key=key, Fields={"Content-Type": "image/jpeg"},
        Conditions=[{"Content-Type": "image/jpeg"}, ["content-length-range", 1, 8 * 1024 * 1024]], ExpiresIn=600)
    return http.resp(200, {"reportId": rid, "uploadUrl": post["url"], "fields": post["fields"]})


def listing(q):
    city = _city(q)
    rows = drains.build_groups(drain_store.for_city(city), _hotspots(city))
    if q.get("status") != "all":
        rows = [r for r in rows if r["status"] != "cleared"]
    return http.resp(200, {"drains": rows, "now": int(time.time())})


def metrics(q):
    city = _city(q)
    return http.resp(200, drains.metrics(drain_store.for_city(city), time.time()))


def _row(head):
    """Computed blockage row for the group containing `head` (empty if it is not a real blockage yet)."""
    for row in drains.build_groups(drain_store.for_city(head["city"]), _hotspots(head["city"])):
        if head["reportId"] in row["reportIds"]:
            return row
    return {}


def one(event):
    rid = http.path_param(event, "id")
    head = drain_store.get(rid)
    if not head:
        # the id may be a merged group's id: look it up in the computed groups
        for city in config.CITIES:
            for row in drains.build_groups(drain_store.for_city(city), _hotspots(city)):
                if rid == row["groupId"]:
                    head = drain_store.get(row["reportIds"][0])
    if not head:
        return http.bad("not found", 404)
    status, error = head["status"], head.get("rejection_reason")
    if status == "analysing" and time.time() - head["ts"] > STALE_ANALYSIS_S:
        status, error = "error", "The analysis did not finish. Tap retry; if the photo never uploaded, send it again."
    row = _row(head)
    out = {"status": status, "rejection_reason": error, "stage": status, "analysisMode": head.get("analysisMode"),
           "analysisError": head.get("analysisError"), **row,
           "reasoning": head.get("reasoning"), "reasoning_hi": head.get("reasoning_hi"),
           "confidence": head.get("confidence"), "standing_water": head.get("standing_water"),
           "afterSeverity": head.get("afterSeverity"), "afterNote": row.get("afterNote") or head.get("afterNote"),
           "clearanceVerified": any(m.get("clearanceVerified") for m in [head]),
           "photoUrl": views.photo_url(head["s3Key"]) if head.get("s3Key") else None}
    if status == "error" and error:
        out["status"] = "error"
    if head.get("afterKey"):
        out["afterUrl"] = views.photo_url(head["afterKey"])
    return http.resp(200, out)


def retry(event):
    """Re-trigger analysis for a report that failed or never finished."""
    rid = http.path_param(event, "id")
    head = drain_store.get(rid)
    if not head or not head.get("s3Key"):
        return http.bad("not found", 404)
    stale = head["status"] == "analysing" and time.time() - head["ts"] > 60
    if head["status"] != "error" and not stale:
        return http.bad("This report is not stuck, so there is nothing to retry.", 409)
    key = head["s3Key"]
    s3 = views.s3()
    try:
        s3.head_object(Bucket=config.PHOTOS_BUCKET, Key=key)
    except Exception:
        return http.bad("The photo never arrived. Please send it again.", 409)
    drain_store.update(rid, {"status": "analysing", "retriedAt": int(time.time())}, remove=["rejection_reason", "analysisError"])
    # A copy onto itself raises ObjectCreated:Copy, which triggers the analyser again.
    s3.copy_object(Bucket=config.PHOTOS_BUCKET, Key=key, CopySource={"Bucket": config.PHOTOS_BUCKET, "Key": key},
                   ContentType="image/jpeg", MetadataDirective="REPLACE")
    return http.resp(200, {"ok": True, "status": "analysing"})


def assign(event):
    gid = http.path_param(event, "id")
    worker = str(http.body(event).get("worker") or "").strip()[:60]
    head = drain_store.get(gid)
    if not head or head.get("status") not in drains.OPEN:
        return http.bad("not found or already cleared", 404)
    if not worker:
        return http.bad("worker name required")
    drain_store.update_group(head["city"], gid, {"status": "assigned", "assignedTo": worker, "assignedAt": int(time.time())})
    return http.resp(200, {"ok": True, "assignedTo": worker})


def confirm(event):
    """Dispatcher decision on an after-photo when automatic verification could not run."""
    gid = http.path_param(event, "id")
    b = http.body(event)
    decision, note = b.get("decision"), str(b.get("note") or "")[:200]
    head = drain_store.get(gid)
    if not head or head.get("status") not in drains.OPEN:
        return http.bad("not found or already cleared", 404)
    row = _row(head)
    members = [drain_store.get(i) for i in (row.get("reportIds") or [gid])]
    if not any(m and m.get("afterKey") for m in members):
        return http.bad("There is no after-photo to confirm yet.", 409)
    if decision == "clear":
        drain_store.update_group(head["city"], gid, {
            "status": "cleared", "clearedAt": int(time.time()), "clearanceVerified": False, "clearedBy": "dispatcher",
            "awaitingReview": False, "afterRejected": False,
            "afterNote": ("Confirmed clear by a dispatcher from the after-photo (manual, not AI-verified)." + (f" {note}" if note else ""))})
    elif decision == "reject":
        drain_store.update_group(head["city"], gid, {
            "awaitingReview": False, "afterRejected": True,
            "afterNote": "A dispatcher rejected the after-photo. Send another photo." + (f" {note}" if note else "")})
    else:
        return http.bad("decision must be clear or reject")
    return http.resp(200, {"ok": True, "decision": decision})


def after_url(event):
    gid = http.path_param(event, "id")
    head = drain_store.get(gid)
    if not head or head.get("status") not in drains.OPEN:
        return http.bad("not found or already cleared", 404)
    post = views.s3().generate_presigned_post(
        Bucket=config.PHOTOS_BUCKET, Key=f"drains-after/{gid}.jpg", Fields={"Content-Type": "image/jpeg"},
        Conditions=[{"Content-Type": "image/jpeg"}, ["content-length-range", 1, 8 * 1024 * 1024]], ExpiresIn=600)
    return http.resp(200, {"uploadUrl": post["url"], "fields": post["fields"]})


def handler(event, _ctx):
    route, q = event.get("routeKey", ""), http.qs(event)
    try:
        if route == "POST /drains/upload-url":
            return upload_url(event)
        if route == "GET /drains":
            return listing(q)
        if route == "GET /drains/metrics":
            return metrics(q)
        if route == "GET /drains/{id}":
            return one(event)
        if route == "POST /drains/{id}/retry":
            dev = str(http.body(event).get("deviceId") or "")[:64]
            if len(dev) < 8:
                return http.bad("deviceId required")
            if ratelimit.limited("drainretry", dev, PER_DEVICE_PER_HOUR):
                return http.bad("Too many retries. Try again later.", 429)
            return retry(event)
        if route in ("POST /drains/{id}/assign", "POST /drains/{id}/after-url", "POST /drains/{id}/confirm"):
            if not _admin(event):
                return http.bad("Dispatcher access only.", 403)
            return {"assign": assign, "after-url": after_url, "confirm": confirm}[route.rsplit("/", 1)[-1]](event)
    except ValueError as e:
        return http.bad(str(e))
    return http.bad("not found", 404)
