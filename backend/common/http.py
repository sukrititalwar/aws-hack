"""API Gateway HTTP API (payload v2) helpers."""
import json
from decimal import Decimal

from . import config


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not serialisable: {type(o)}")


def resp(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": config.ALLOWED_ORIGIN,
        },
        "body": json.dumps(body, default=_default, ensure_ascii=False),
    }


def bad(msg: str, status: int = 400) -> dict:
    return resp(status, {"error": msg})


def body(event) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("body is not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def qs(event) -> dict:
    return event.get("queryStringParameters") or {}


def path_param(event, name):
    return (event.get("pathParameters") or {}).get(name)


def source_ip(event) -> str:
    return ((event.get("requestContext") or {}).get("http") or {}).get("sourceIp", "unknown")
