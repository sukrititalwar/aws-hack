"""Photo -> depth assessment via Amazon Bedrock (Converse API), plus JSON hardening.

Shared by the analyze Lambda, scripts/seed_demo.py and tests/eval_depth.py.
"""
import io
import json
import logging
import os
import re
import time
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from . import config

log = logging.getLogger()
MAX_SIDE = 1568


class AIUnavailable(Exception):
    """Bedrock could not answer (no model access, quota 0, throttled, bad request, ...).

    Carries the real AWS error code and message so the app can show a clearly labelled fallback
    and operators can see the actual cause instead of a bare exception class name."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def inference_config(max_tokens: int) -> dict:
    cfg = {"maxTokens": max_tokens}
    if config.BEDROCK_TEMPERATURE is not None:
        cfg["temperature"] = config.BEDROCK_TEMPERATURE
    return cfg


def converse(**kwargs) -> dict:
    """bedrock-runtime converse() with failures turned into AIUnavailable (code + message)."""
    try:
        return _bedrock().converse(**kwargs)
    except (ClientError, BotoCoreError) as e:
        err = getattr(e, "response", {}).get("Error", {}) if isinstance(e, ClientError) else {}
        code = err.get("Code") or type(e).__name__
        msg = (err.get("Message") or str(e)).replace("\n", " ")[:240]
        log.error("Bedrock %s: %s", code, msg)
        raise AIUnavailable(code, msg) from e
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "depth_prompt.txt")

HAZARDS = {"open_drain_or_manhole_risk", "strong_current", "submerged_vehicle",
           "electric_pole_or_wire_in_water", "debris", "poor_visibility_night", "none"}


@lru_cache(maxsize=None)
def _bedrock():
    return boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION,
                        config=Config(read_timeout=60, retries={"max_attempts": 3, "mode": "adaptive"}))


@lru_cache(maxsize=None)
def system_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Resize to <= MAX_SIDE on the long edge and re-encode as JPEG. Falls back to the
    original bytes if Pillow is unavailable (the PWA already resizes before upload)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data, "jpeg"
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "jpeg"


def extract_json(text: str) -> dict:
    """Parse model output robustly: strip code fences / prose around the JSON object."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def normalise(a: dict) -> dict:
    """Clamp and fill fields so the rules engine always gets a valid assessment."""
    def num(x, default=0.0):
        try:
            return max(0.0, min(300.0, float(x)))
        except (TypeError, ValueError):
            return default

    out = dict(a)
    out["is_flooded_road_photo"] = bool(a.get("is_flooded_road_photo", False))
    lo, hi = num(a.get("depth_cm_low")), num(a.get("depth_cm_high"))
    out["depth_cm_low"], out["depth_cm_high"] = min(lo, hi), max(lo, hi)
    out["confidence"] = a.get("confidence") if a.get("confidence") in ("low", "medium", "high") else "low"
    out["image_quality"] = a.get("image_quality") if a.get("image_quality") in ("good", "ok", "poor") else "ok"
    out["flowing_water"] = bool(a.get("flowing_water", False))
    out["hazards"] = [h for h in (a.get("hazards") or []) if h in HAZARDS and h != "none"]
    out["reference_objects"] = [r for r in (a.get("reference_objects") or []) if isinstance(r, dict)][:8]
    out["reasoning"] = str(a.get("reasoning") or "")[:500]
    out["reasoning_hi"] = str(a.get("reasoning_hi") or "")[:500]
    out["location_type"] = a.get("location_type") or "other"
    return out


def estimate_depth(image_bytes: bytes, city: str, place: str | None) -> tuple[dict, dict]:
    """Returns (normalised assessment, metrics). Raises on repeated failure."""
    img, fmt = prepare_image(image_bytes)
    user_text = f"City: {city}. Place name if given: {place or 'not given'}. Estimate the water depth."
    messages = [{"role": "user", "content": [
        {"image": {"format": fmt, "source": {"bytes": img}}},
        {"text": user_text},
    ]}]
    metrics = {"model": config.BEDROCK_MODEL_ID, "attempts": 0, "input_tokens": 0, "output_tokens": 0}
    t0 = time.time()
    last_err = None
    for attempt in range(2):
        metrics["attempts"] += 1
        r = converse(
            modelId=config.BEDROCK_MODEL_ID,
            system=[{"text": system_prompt()}],
            messages=messages,
            inferenceConfig=inference_config(1200),
        )
        usage = r.get("usage", {})
        metrics["input_tokens"] += usage.get("inputTokens", 0)
        metrics["output_tokens"] += usage.get("outputTokens", 0)
        text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
        try:
            parsed = normalise(extract_json(text))
            metrics["latency_ms"] = int((time.time() - t0) * 1000)
            return parsed, metrics
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            log.warning("JSON parse failed (attempt %d): %s", attempt + 1, text[:300])
            # Retry once with the bad answer in context and a firm instruction.
            messages = messages + [
                {"role": "assistant", "content": [{"text": text or "{}"}]},
                {"role": "user", "content": [{"text": "Return only the JSON object, nothing else."}]},
            ]
    raise ValueError(f"model did not return valid JSON: {last_err}")


def dhash(image_bytes: bytes, size: int = 8) -> str | None:
    """Perceptual difference hash (64 bit hex) to block re-uploads of the same photo."""
    try:
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((size + 1, size))
    px = list(img.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return f"{bits:016x}"


DRAIN_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "drain_prompt.txt")


@lru_cache(maxsize=None)
def drain_prompt() -> str:
    with open(DRAIN_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def classify_drain(image_bytes: bytes, city: str) -> tuple[dict, dict]:
    """Photo of a drain -> {severity: clear|partial|blocked, blockage_type, ...}. Categories only."""
    img, fmt = prepare_image(image_bytes)
    messages = [{"role": "user", "content": [
        {"image": {"format": fmt, "source": {"bytes": img}}},
        {"text": f"City: {city}. Assess this drain."}]}]
    t0 = time.time()
    last = None
    for attempt in range(2):
        r = converse(modelId=config.BEDROCK_MODEL_ID, system=[{"text": drain_prompt()}], messages=messages,
                     inferenceConfig=inference_config(600))
        text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
        try:
            a = extract_json(text)
            a["severity"] = a.get("severity") if a.get("severity") in ("clear", "partial", "blocked") else "partial"
            a["confidence"] = a.get("confidence") if a.get("confidence") in ("low", "medium", "high") else "low"
            a["is_drain_photo"] = bool(a.get("is_drain_photo", False))
            usage = r.get("usage", {})
            return a, {"latency_ms": int((time.time() - t0) * 1000), "input_tokens": usage.get("inputTokens", 0),
                       "output_tokens": usage.get("outputTokens", 0), "model": config.BEDROCK_MODEL_ID}
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            messages += [{"role": "assistant", "content": [{"text": text or "{}"}]},
                         {"role": "user", "content": [{"text": "Return only the JSON object, nothing else."}]}]
    raise ValueError(f"model did not return valid JSON: {last}")
