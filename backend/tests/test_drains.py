"""DrainReady: grouping, priority, metrics (pure) and the full report -> assign -> clear flow (moto)."""
import json
import time
from io import BytesIO

import boto3
import pytest

from common import drains
from tests.test_handlers import _event, aws  # noqa: F401  (fixture)

NOW = 1_760_000_000
H = 3600


def rep(rid, lat=28.6364, lon=77.2224, hours_ago=2, status="open", sev="blocked", rain=0.0, device=None, **kw):
    r = {"reportId": rid, "city": "delhi", "lat": lat, "lon": lon, "ts": NOW - hours_ago * H, "status": status,
         "severity": sev, "rainNext24h": rain, "deviceHash": device or rid}
    r.update(kw)
    return r


# ---------- grouping ----------

def test_duplicate_within_30m_joins_open_group():
    a = rep("a")
    b = rep("b", lat=28.63655)           # ~15 m north
    far = rep("c", lat=28.6370)          # ~65 m
    assert drains.find_group(b, [a]) == "a"
    assert drains.find_group(far, [a]) is None


def test_cleared_or_assigned_groups():
    cleared = rep("a", status="cleared", clearedAt=NOW)
    assert drains.find_group(rep("b"), [cleared]) is None     # a cleared drain that blocks again is NEW (repeat)
    assigned = rep("a", status="assigned", groupId="g1")
    assert drains.find_group(rep("b"), [assigned]) == "g1"


# ---------- priority ----------

def test_priority_orders_by_severity_reports_rain_and_hotspot():
    base = drains.priority([rep("a", sev="partial")])["score"]
    blocked = drains.priority([rep("a", sev="blocked")])["score"]
    two = drains.priority([rep("a"), rep("b", device="other")])["score"]
    rainy = drains.priority([rep("a", rain=30)])["score"]
    hot = drains.priority([rep("a")], [{"name": "Minto Bridge", "lon": 77.2224, "lat": 28.6364}])
    assert base < blocked < two
    assert rainy > blocked * 2 and drains.priority([rep("a", rain=30)])["urgent"]
    assert hot["score"] == pytest.approx(blocked * 1.5) and hot["nearHotspot"] == "Minto Bridge"
    assert "near known flood spot: Minto Bridge" in hot["reasons"]


def test_same_device_twice_is_one_reporter():
    assert drains.priority([rep("a", device="d1"), rep("b", device="d1")])["reportCount"] == 1


def test_ranking_cleared_last_rain_first():
    reports = [rep("dry", lat=28.60), rep("wet", lat=28.62, rain=40), rep("done", lat=28.64, status="cleared", clearedAt=NOW)]
    rows = drains.build_groups(reports)
    assert [r["groupId"] for r in rows] == ["wet", "dry", "done"]
    assert rows[0]["urgent"] and rows[2]["status"] == "cleared"


def test_group_rows_merge_members_and_skip_unanalysed():
    reports = [rep("a"), rep("b", lat=28.63645, groupId="a", device="x"), rep("c", status="analysing"), rep("d", status="rejected")]
    for r in reports[:2]:
        r["groupId"] = "a"
    rows = drains.build_groups(reports)
    assert len(rows) == 1 and rows[0]["reportCount"] == 2 and rows[0]["reportIds"] == ["a", "b"]


# ---------- metrics ----------

def test_metrics():
    reports = [
        rep("a", hours_ago=30, status="cleared", clearedAt=NOW - 20 * H, rain=25),           # 10 h, before rain
        rep("b", hours_ago=60, status="cleared", clearedAt=NOW - 4 * H, rain=25),            # 56 h: too slow
        rep("c", hours_ago=10, status="cleared", clearedAt=NOW - 8 * H, rain=0, lat=28.70),  # 2 h, dry day
        rep("d", hours_ago=1, status="open", lat=28.6364),                                   # repeat of 'a' (same spot, later)
        rep("e", hours_ago=1, status="assigned", lat=28.50),
    ]
    m = drains.metrics(reports, NOW)
    assert m["reported"] == 5 and m["open"] == 2 and m["assigned"] == 1 and m["cleared"] == 3
    assert m["median_hours_to_clear"] == 10.0
    assert m["rain_forecast_cases"] == 2 and m["cleared_before_rain"] == 1
    assert m["repeat_blockages"] == 1


def test_metrics_empty():
    m = drains.metrics([], NOW)
    assert m["cleared"] == 0 and m["median_hours_to_clear"] is None


# ---------- end to end on moto ----------

def _jpeg():
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (64, 48), (80, 80, 80)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def drain_env(aws, monkeypatch):  # noqa: F811
    from common import config, db, depth, drain_store, views, weather
    monkeypatch.setattr(config, "DRAINS_TABLE", "Drains")
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secret-token")
    boto3.client("dynamodb").create_table(
        TableName="Drains", BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "reportId", "AttributeType": "S"}, {"AttributeName": "city", "AttributeType": "S"},
                              {"AttributeName": "ts", "AttributeType": "N"}],
        KeySchema=[{"AttributeName": "reportId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{"IndexName": "byCity", "Projection": {"ProjectionType": "ALL"},
                                 "KeySchema": [{"AttributeName": "city", "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}]}])
    db._ddb.cache_clear()
    views.s3.cache_clear()
    answers = {"drains": {"is_drain_photo": True, "severity": "blocked", "blockage_type": "garbage", "confidence": "high",
                          "standing_water": True, "reasoning": "Grating covered by plastic.", "reasoning_hi": "x"},
               "after": {"is_drain_photo": True, "severity": "clear", "confidence": "high", "reasoning": "Clear."}}
    state = {"mode": "drains"}
    monkeypatch.setattr(depth, "classify_drain", lambda img, city: (dict(answers[state["mode"]]), {}))
    monkeypatch.setattr(weather, "next24h_mm", lambda lat, lon: 32.0)
    from functions.drain_analyze import app as da
    monkeypatch.setattr(da, "_unsafe", lambda b, k: None)
    return state, answers, drain_store


def _report(lat=28.6364, lon=77.2224, device="resident-0001"):
    from functions.drain_analyze import app as da
    from functions.drains import app as api
    r = json.loads(api.handler(_event("POST /drains/upload-url", {"lat": lat, "lon": lon, "city": "delhi", "deviceId": device}), None)["body"])
    key = f"drains/{r['reportId']}.jpg"
    boto3.client("s3").put_object(Bucket="test-photos", Key=key, Body=_jpeg())
    da.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": key}}}]}, None)
    return r["reportId"]


def _admin(route, body, path, token="secret-token"):
    e = _event(route, body, path)
    e["headers"] = {"x-admin-token": token}
    return e


def test_full_flow(drain_env):
    state, answers, store = drain_env
    from functions.drain_analyze import app as da
    from functions.drains import app as api

    first = _report()
    second = _report(lat=28.63655, device="resident-0002")       # ~15 m away: duplicate
    third = _report(lat=28.7000, device="resident-0003")         # elsewhere
    assert store.get(first)["status"] == "open" and store.get(first)["rainNext24h"] == 32.0
    assert store.get(second)["groupId"] == first and store.get(third)["groupId"] == third

    rows = json.loads(api.handler(_event("GET /drains", qs={"city": "delhi"}), None)["body"])["drains"]
    assert len(rows) == 2
    top = rows[0]
    assert top["groupId"] == first and top["reportCount"] == 2 and top["urgent"]
    assert "2 independent reports" in top["reasons"] and "32 mm rain forecast in 24 h" in top["reasons"]

    # dispatcher auth
    assert api.handler(_admin("POST /drains/{id}/assign", {"worker": "Ramesh"}, {"id": first}, token="wrong"), None)["statusCode"] == 403
    ok = api.handler(_admin("POST /drains/{id}/assign", {"worker": "Ramesh"}, {"id": first}), None)
    assert ok["statusCode"] == 200
    assert store.get(second)["status"] == "assigned"                 # whole group is assigned

    # an after-photo that does NOT show a clear drain is rejected: no clearance without evidence
    up = json.loads(api.handler(_admin("POST /drains/{id}/after-url", {}, {"id": first}), None)["body"])
    assert up["fields"]["key"] == f"drains-after/{first}.jpg"
    boto3.client("s3").put_object(Bucket="test-photos", Key=f"drains-after/{first}.jpg", Body=_jpeg())
    state["mode"] = "after"
    answers["after"]["severity"] = "blocked"
    da.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": f"drains-after/{first}.jpg"}}}]}, None)
    assert store.get(first)["status"] == "assigned" and store.get(first)["afterRejected"]

    # a proper after-photo clears every report in the group
    answers["after"]["severity"] = "clear"
    da.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": f"drains-after/{first}.jpg"}}}]}, None)
    assert store.get(first)["status"] == "cleared" and store.get(second)["status"] == "cleared"
    assert store.get(first)["clearanceVerified"] is True

    detail = json.loads(api.handler(_event("GET /drains/{id}", path={"id": first}), None)["body"])
    assert detail["photoUrl"].startswith("https://") and detail["afterUrl"].startswith("https://")
    m = json.loads(api.handler(_event("GET /drains/metrics", qs={"city": "delhi"}), None)["body"])
    assert m["cleared"] == 1 and m["cleared_before_rain"] == 1 and m["open"] == 1 and m["repeat_blockages"] == 0

    # the same drain blocks again after clearing: new group, counted as a repeat blockage
    state["mode"] = "drains"
    again = _report(device="resident-0004")
    assert store.get(again)["groupId"] == again
    m = json.loads(api.handler(_event("GET /drains/metrics", qs={"city": "delhi"}), None)["body"])
    assert m["repeat_blockages"] == 1


def test_clear_drain_and_non_drain_photos_are_rejected(drain_env):
    state, answers, store = drain_env
    answers["drains"]["severity"] = "clear"
    rid = _report()
    assert store.get(rid)["status"] == "rejected" and "clear" in store.get(rid)["rejection_reason"]
    answers["drains"].update({"severity": "blocked", "is_drain_photo": False, "rejection_reason": "That is a dog."})
    rid = _report(device="resident-0005")
    assert store.get(rid)["rejection_reason"] == "That is a dog."


def test_detail_while_analysing_and_after_rejection(drain_env):
    from functions.drains import app as api
    state, answers, store = drain_env
    up = json.loads(api.handler(_event("POST /drains/upload-url", {"lat": 28.6, "lon": 77.2, "city": "delhi",
                                                                     "deviceId": "resident-0009"}), None)["body"])
    d = json.loads(api.handler(_event("GET /drains/{id}", path={"id": up["reportId"]}), None)["body"])
    assert d["status"] == "analysing" and "photoUrl" in d
    answers["drains"].update({"is_drain_photo": False, "rejection_reason": "No drain."})
    rid = _report(device="resident-0010")
    d = json.loads(api.handler(_event("GET /drains/{id}", path={"id": rid}), None)["body"])
    assert d["status"] == "rejected" and d["rejection_reason"] == "No drain."


def test_dispatcher_routes_closed_without_token(drain_env):
    from functions.drains import app as api
    e = _event("POST /drains/{id}/assign", {"worker": "x"}, {"id": "nope"})
    assert api.handler(e, None)["statusCode"] == 403
