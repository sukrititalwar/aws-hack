"""POST /reports/upload-url -> create a pending report and a presigned S3 PUT URL.

The S3 put then triggers functions/analyze.
"""
import hashlib
import time
import uuid

from botocore.exceptions import ClientError

from common import config, db, geo, http, views


def _rate_limited(device_id: str) -> bool:
    """Atomic per-device counter per hour bucket; TTL cleans it up."""
    hour = int(time.time() // 3600)
    try:
        db.table(config.RATELIMIT_TABLE).update_item(
            Key={"key": f"dev#{device_id}#{hour}"},
            UpdateExpression="ADD n :one SET expiresAt = :exp",
            ConditionExpression="attribute_not_exists(n) OR n < :lim",
            ExpressionAttributeValues={":one": 1, ":lim": config.REPORTS_PER_DEVICE_PER_HOUR,
                                       ":exp": (hour + 2) * 3600},
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def handler(event, _ctx):
    try:
        b = http.body(event)
    except ValueError as e:
        return http.bad(str(e))

    lat, lon = b.get("lat"), b.get("lon")
    city = str(b.get("city") or "delhi").lower()
    device_id = str(b.get("deviceId") or "")[:64]
    if not geo.valid_lonlat(lon, lat):
        return http.bad("lat/lon missing or out of range")
    if city not in config.CITIES:
        return http.bad(f"unsupported city; use one of {sorted(config.CITIES)}")
    if len(device_id) < 8:
        return http.bad("deviceId required")
    if _rate_limited(device_id):
        return http.bad("Too many reports from this device. Try again in an hour.", 429)

    lat, lon = float(lat), float(lon)
    now = int(time.time())
    report_id = uuid.uuid4().hex[:16]
    key = f"uploads/{report_id}.jpg"
    exif_time = b.get("exifTime")

    db.put_report({
        "reportId": report_id,
        "city": city,
        "mode": "live",
        "cell": db.cell_key("live", city, lat, lon),
        "cityMode": f"live#{city}",
        "lat": lat, "lon": lon,
        "place": (str(b["place"])[:120] if b.get("place") else None),
        "deviceHash": hashlib.sha256(device_id.encode()).hexdigest()[:16],
        "ipHash": hashlib.sha256(http.source_ip(event).encode()).hexdigest()[:16],
        "createdAt": now, "ts": now,
        "exifTime": int(exif_time) if isinstance(exif_time, (int, float)) else None,
        "status": "analysing",
        "s3Key": key,
        "source_type": "photo",
        "votes": {"still": 0, "cleared": 0, "wrong": 0},
        "voters": None,
        "expiresAt": now + config.EXPIRE_AFTER_H * 3600,
    })

    # Presigned POST (not PUT) so S3 itself enforces the content type and an 8 MB size cap.
    post = views.s3().generate_presigned_post(
        Bucket=config.PHOTOS_BUCKET, Key=key,
        Fields={"Content-Type": "image/jpeg"},
        Conditions=[{"Content-Type": "image/jpeg"}, ["content-length-range", 1, 8 * 1024 * 1024]],
        ExpiresIn=600,
    )
    return http.resp(200, {"reportId": report_id, "uploadUrl": post["url"], "fields": post["fields"]})
