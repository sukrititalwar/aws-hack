"""DynamoDB access for reports, hotspots and subscriptions.

Reports table
  PK  reportId
  GSI byCell  PK cell     = "<mode>#<city>#<geohash5>"   SK ts   (viewport queries)
  GSI byCity  PK cityMode = "<mode>#<city>"              SK ts   (demo timeline, admin)
  mode is "live" or "demo" so replayed archive photos never mix with live reports.
  ts = createdAt for live reports, the replay time for demo reports.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Key

from . import config, geo, spots


@lru_cache(maxsize=None)
def _ddb():
    return boto3.resource("dynamodb", region_name=config.REGION)


def table(name: str):
    return _ddb().Table(name)


def to_ddb(o):
    """floats -> Decimal, recursively (DynamoDB rejects floats)."""
    if isinstance(o, float):
        return Decimal(str(round(o, 7)))
    if isinstance(o, dict):
        return {k: to_ddb(v) for k, v in o.items() if v is not None}
    if isinstance(o, (list, tuple)):
        return [to_ddb(v) for v in o]
    return o


def from_ddb(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, dict):
        return {k: from_ddb(v) for k, v in o.items()}
    if isinstance(o, list):
        return [from_ddb(v) for v in o]
    if isinstance(o, set):
        return sorted(from_ddb(v) for v in o)
    return o


def cell_key(mode: str, city: str, lat: float, lon: float) -> str:
    return f"{mode}#{city}#{geo.geohash_encode(lat, lon, config.GEOHASH_PRECISION)}"


# ---------- reports ----------

def put_report(item: dict):
    table(config.REPORTS_TABLE).put_item(Item=to_ddb(item))


def get_report(report_id: str):
    it = table(config.REPORTS_TABLE).get_item(Key={"reportId": report_id}).get("Item")
    return from_ddb(it) if it else None


def update_report(report_id: str, fields: dict):
    fields = to_ddb(fields)
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    table(config.REPORTS_TABLE).update_item(
        Key={"reportId": report_id}, UpdateExpression=expr,
        ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def _query_all(index: str, key_name: str, key_value: str, ts_from: float, ts_to: float):
    t = table(config.REPORTS_TABLE)
    kwargs = {"IndexName": index,
              "KeyConditionExpression": Key(key_name).eq(key_value)
              & Key("ts").between(Decimal(str(int(ts_from))), Decimal(str(int(ts_to))))}
    items = []
    while True:
        page = t.query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def query_bbox(city: str, mode: str, bbox, ts_from: float, ts_to: float) -> list[dict]:
    """All reports in bbox with ts in [ts_from, ts_to]. One query per geohash cell, in parallel."""
    cells = [f"{mode}#{city}#{c}" for c in geo.cover_bbox(bbox, config.GEOHASH_PRECISION)]
    with ThreadPoolExecutor(max_workers=min(16, len(cells) or 1)) as ex:
        pages = ex.map(lambda c: _query_all("byCell", "cell", c, ts_from, ts_to), cells)
    min_lon, min_lat, max_lon, max_lat = bbox
    out = []
    for page in pages:
        for it in page:
            it = from_ddb(it)
            if min_lon <= it["lon"] <= max_lon and min_lat <= it["lat"] <= max_lat:
                out.append(it)
    return out


def query_city(city: str, mode: str, ts_from: float = 0, ts_to: float = 4102444800) -> list[dict]:
    return [from_ddb(i) for i in _query_all("byCity", "cityMode", f"{mode}#{city}", ts_from, ts_to)]


def as_spot_input(it: dict) -> dict:
    return {
        "reportId": it["reportId"], "lat": it["lat"], "lon": it["lon"], "ts": it["ts"],
        "depth_low": it.get("depth_low"), "depth_high": it.get("depth_high"),
        "confidence": it.get("confidence"), "image_quality": it.get("image_quality"),
        "flowing_water": it.get("flowing_water"), "hazards": it.get("hazards"),
        "votes": it.get("votes") or {}, "lastStillTs": it.get("lastStillTs"),
        "source_type": it.get("source_type", "photo"), "place": it.get("place"),
        "closure": it.get("closure"), "source_url": it.get("source_url"),
    }


def hotspots(city: str) -> list[dict]:
    """Chronic hotspots for a city plus the '#weather' summary item (split by caller)."""
    items = table(config.HOTSPOTS_TABLE).query(KeyConditionExpression=Key("city").eq(city)).get("Items", [])
    return [from_ddb(i) for i in items]


def active_spots(city: str, mode: str, bbox, now: float | None = None, predicted: bool = True) -> list[dict]:
    """Merged active spots at time `now` (demo replay passes the replay time). In live mode,
    chronic hotspots under heavy rain are added as low-confidence *predicted* spots."""
    now = now or time.time()
    real = _real_spots(city, mode, bbox, now)
    if mode != "live" or not predicted:
        return real
    min_lon, min_lat, max_lon, max_lat = bbox
    hs = [h for h in hotspots(city) if not h["hotspotId"].startswith("#")
          and min_lon <= h["lon"] <= max_lon and min_lat <= h["lat"] <= max_lat]
    return real + spots.predicted_spots(hs, real, now)


def _real_spots(city: str, mode: str, bbox, now: float) -> list[dict]:
    # "still flooded" votes keep a report alive past its own ts, so look back 2x the expiry
    # window; build_spots drops anything without activity in the last EXPIRE_AFTER_H.
    items = query_bbox(city, mode, bbox, now - 2 * config.EXPIRE_AFTER_H * 3600, now)
    live = [as_spot_input(i) for i in items if i.get("status") == "live"]
    return spots.build_spots(live, now)
