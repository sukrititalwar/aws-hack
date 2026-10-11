"""Clearly labelled fallback for DrainReady photo analysis when Bedrock cannot answer.

Order of preference (the record always says which one was used, in `analysisMode`):
  bedrock             full AI assessment (Claude vision)
  rekognition_labels  Amazon Rekognition image labels + simple rules. Crude on purpose: it can say
                      "looks like rubbish around a drain", not "how blocked". Always low confidence
                      and flagged `needsReview`
  manual              nothing automatic worked; the report is queued unrated for a person

A resident's report is NEVER dropped because an AI service failed, and a drain is NEVER marked
cleared by a fallback: a dispatcher has to confirm clearance from the photos.
"""
import logging
from functools import lru_cache

import boto3

from . import config

log = logging.getLogger()

DRAIN_WORDS = {"drain", "drainage", "gutter", "sewer", "manhole", "grate", "grille", "culvert", "canal", "ditch", "pipe", "gully"}
TRASH_WORDS = {"trash", "garbage", "litter", "waste", "rubbish", "debris", "plastic bag", "plastic", "dump", "bag", "junk"}
WATER_WORDS = {"puddle", "flood", "flooding", "water", "wet", "stream"}
MIN_CONF = 60


@lru_cache(maxsize=None)
def _rek():
    return boto3.client("rekognition", region_name=config.REGION)


def labels_for(bucket: str, key: str) -> list[tuple[str, float]]:
    r = _rek().detect_labels(Image={"S3Object": {"Bucket": bucket, "Name": key}}, MaxLabels=40, MinConfidence=MIN_CONF)
    return [(l["Name"], float(l["Confidence"])) for l in r.get("Labels", [])]


def _best(labels, words) -> tuple[str, float]:
    hits = [(n, c) for n, c in labels if n.lower() in words]
    return max(hits, key=lambda x: x[1]) if hits else ("", 0.0)


def describe(labels, limit: int = 4) -> str:
    return ", ".join(f"{n} {c:.0f}%" for n, c in sorted(labels, key=lambda x: -x[1])[:limit]) or "no clear labels"


def rate_report(labels, error: str) -> dict:
    """Assessment for a new drain report from image labels. Same shape as depth.classify_drain
    output plus the fields that label how it was produced."""
    _, trash = _best(labels, TRASH_WORDS)
    _, water = _best(labels, WATER_WORDS)
    _, drain = _best(labels, DRAIN_WORDS)
    if trash >= 80 and (drain >= MIN_CONF or water >= MIN_CONF):
        severity, why = "blocked", "rubbish is visible around the drain or water"
    elif trash >= MIN_CONF or water >= 80:
        severity, why = "partial", "some rubbish or standing water is visible"
    else:
        severity, why = "partial", "the labels did not show clear rubbish, so this is an unrated default"
    return {
        "is_drain_photo": True, "severity": severity, "blockage_type": "garbage" if trash >= MIN_CONF else "other",
        "standing_water": water >= MIN_CONF, "confidence": "low", "analysisMode": "rekognition_labels",
        "needsReview": True, "analysisError": error,
        "reasoning": (f"Automatic AI analysis is unavailable, so this was rated from basic image labels "
                      f"({describe(labels)}): {why}. A person should confirm before work is scheduled."),
        "reasoning_hi": "स्वचालित AI जाँच अभी उपलब्ध नहीं है, इसलिए यह केवल सामान्य इमेज लेबल से आँका गया है। काम तय करने से पहले किसी व्यक्ति से पुष्टि कराएँ।",
    }


def unrated_report(error: str) -> dict:
    return {
        "is_drain_photo": True, "severity": "partial", "blockage_type": "other", "standing_water": False,
        "confidence": "low", "analysisMode": "manual", "needsReview": True, "analysisError": error,
        "reasoning": "No automatic analysis was available. This report is queued unrated and needs a person to check the photo.",
        "reasoning_hi": "कोई स्वचालित जाँच उपलब्ध नहीं थी। रिपोर्ट बिना रेटिंग के कतार में है; फ़ोटो किसी व्यक्ति को जाँचनी होगी।",
    }


def after_looks_clear(labels) -> tuple[bool, str]:
    """Hint only (never clears a drain): do the labels still show rubbish?"""
    name, conf = _best(labels, TRASH_WORDS)
    if conf >= MIN_CONF:
        return False, f"Basic image labels still show {name.lower()} ({conf:.0f}%)."
    return True, f"Basic image labels show no rubbish ({describe(labels)})."
