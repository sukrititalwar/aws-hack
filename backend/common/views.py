"""Public JSON shape of a report (never leaks deviceId / IP / perceptual hash)."""
from functools import lru_cache

import boto3
from botocore.config import Config

from . import config

PUBLIC_FIELDS = [
    "reportId", "city", "mode", "lat", "lon", "place", "status", "rejection_reason",
    "createdAt", "ts", "depth_low", "depth_high", "confidence", "image_quality",
    "flowing_water", "hazards", "danger", "reasoning", "reasoning_hi", "reference_objects",
    "location_type", "verdicts", "votes", "source_type", "source_url", "source_label",
    "demoReplayTime", "source_platform", "closure", "locatedBy",
]


@lru_cache(maxsize=None)
def s3():
    # Virtual-host style + SigV4 so presigned URLs work outside us-east-1 without redirects.
    return boto3.client("s3", region_name=config.REGION,
                        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))


def photo_url(key: str, expires: int = 3600) -> str:
    return s3().generate_presigned_url("get_object", Params={"Bucket": config.PHOTOS_BUCKET, "Key": key},
                                       ExpiresIn=expires)


def public_report(item: dict, with_photo: bool = True) -> dict:
    out = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    if with_photo and item.get("s3Key") and item.get("status") in ("live", "stale", "cleared"):
        out["photoUrl"] = photo_url(item["s3Key"])
    return out
