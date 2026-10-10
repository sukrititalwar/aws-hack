"""DrainReady API.

  POST /drains/upload-url          {lat, lon, city, deviceId, note?} -> presigned S3 POST for the photo
  GET  /drains?city=               blockages ranked by priority (severity x reports x rain x hotspot)
  GET  /drains/metrics?city=       blockages cleared before rain, median time to clear, repeat blockages
  GET  /drains/{groupId}           one blockage with photos
  POST /drains/{groupId}/assign    [dispatcher] {worker}
  POST /drains/{groupId}/after-url [dispatcher] -> presigned S3 POST for the after-photo; the
                                   blockage is cleared only if the photo shows a clear drain
Dispatcher routes need the x-admin-token header (demo-grade shared secret).
"""
import hashlib
import hmac
import time
import uuid

from common import config, db, drain_store, drains, geo, http, ratelimit, views

PER_DEVICE_PER_HOUR = 10


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


def one(event):
    gid = http.path_param(event, "id")
    head = drain_store.get(gid)
    if not head:
        return http.bad("not found", 404)
    ms = drain_store.members(head["city"], head.get("groupId") or gid)
    rows = drains.build_groups(ms, _hotspots(head["city"]))
    row = rows[0] if rows else {}                      # empty while still analysing / if rejected
    out = {"status": head["status"], "rejection_reason": head.get("rejection_reason"), **row,
           "reasoning": head.get("reasoning"), "reasoning_hi": head.get("reasoning_hi"),
           "confidence": head.get("confidence"), "standing_water": head.get("standing_water"),
           "afterSeverity": head.get("afterSeverity"), "afterNote": head.get("afterNote"),
           "clearanceVerified": head.get("clearanceVerified", False),
           "photoUrl": views.photo_url(head["s3Key"])}
    if head.get("afterKey"):
        out["afterUrl"] = views.photo_url(head["afterKey"])
    return http.resp(200, out)


def assign(event):
    gid = http.path_param(event, "id")
    worker = str(http.body(event).get("worker") or "").strip()[:60]
    head = drain_store.get(gid)
    if not head or head.get("status") not in drains.OPEN:
        return http.bad("not found or already cleared", 404)
    if not worker:
        return http.bad("worker name required")
    drain_store.update_group(head["city"], head.get("groupId") or gid,
                             {"status": "assigned", "assignedTo": worker, "assignedAt": int(time.time())})
    return http.resp(200, {"ok": True, "assignedTo": worker})


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
        if route in ("POST /drains/{id}/assign", "POST /drains/{id}/after-url"):
            if not _admin(event):
                return http.bad("Dispatcher access only.", 403)
            return assign(event) if route.endswith("assign") else after_url(event)
    except ValueError as e:
        return http.bad(str(e))
    return http.bad("not found", 404)
