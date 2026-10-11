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


# ======================= reliability: Bedrock down, fallback, retry, manual confirm =======================

def _bedrock_down(monkeypatch, code="AccessDeniedException", msg="Operation not allowed"):
    from common import depth

    def boom(img, city):
        raise depth.AIUnavailable(code, msg)
    monkeypatch.setattr(depth, "classify_drain", boom)


def _labels(monkeypatch, labels):
    from common import fallback
    monkeypatch.setattr(fallback, "labels_for", lambda b, k: labels)


def test_bedrock_request_never_sends_temperature(monkeypatch):
    """Claude 5-family models reject temperature with a ValidationException."""
    from common import config, depth
    monkeypatch.setattr(config, "BEDROCK_TEMPERATURE", None)
    assert depth.inference_config(500) == {"maxTokens": 500}
    monkeypatch.setattr(config, "BEDROCK_TEMPERATURE", 0.0)   # opt-in for older models only
    assert depth.inference_config(500) == {"maxTokens": 500, "temperature": 0.0}


def test_converse_errors_keep_the_real_aws_code_and_message(monkeypatch):
    from botocore.exceptions import ClientError

    from common import depth

    class Fake:
        def converse(self, **kw):
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "temperature is not supported"}}, "Converse")
    monkeypatch.setattr(depth, "_bedrock", lambda: Fake())
    with pytest.raises(depth.AIUnavailable) as e:
        depth.converse(modelId="x", messages=[])
    assert e.value.code == "ValidationException" and "temperature is not supported" in str(e.value)


def test_report_is_kept_and_labelled_when_bedrock_is_down(drain_env, monkeypatch):
    state, answers, store = drain_env
    _bedrock_down(monkeypatch)
    _labels(monkeypatch, [("Trash", 93.0), ("Drain", 88.0), ("Puddle", 70.0)])
    rid = _report()
    r = store.get(rid)
    assert r["status"] == "open"                                   # not dropped, not "rejected"
    assert r["analysisMode"] == "rekognition_labels" and r["needsReview"] is True and r["confidence"] == "low"
    assert r["severity"] == "blocked" and "Operation not allowed" in r["analysisError"]
    assert "Automatic AI analysis is unavailable" in r["reasoning"] and "Trash 93%" in r["reasoning"]
    from functions.drains import app as api
    rows = json.loads(api.handler(_event("GET /drains", qs={"city": "delhi"}), None)["body"])["drains"]
    assert rows[0]["needsReview"] and rows[0]["analysisMode"] == "rekognition_labels"


def test_report_is_queued_unrated_when_everything_automatic_fails(drain_env, monkeypatch):
    state, answers, store = drain_env
    _bedrock_down(monkeypatch)
    from common import fallback

    def nope(b, k):
        raise RuntimeError("rekognition down")
    monkeypatch.setattr(fallback, "labels_for", nope)
    rid = _report()
    r = store.get(rid)
    assert r["status"] == "open" and r["analysisMode"] == "manual" and r["needsReview"]
    assert "rekognition down" in r["analysisError"] and "needs a person" in r["reasoning"]


def test_fallback_rating_rules():
    from common import fallback
    assert fallback.rate_report([("Trash", 90.0), ("Drain", 80.0)], "e")["severity"] == "blocked"
    assert fallback.rate_report([("Puddle", 85.0)], "e")["severity"] == "partial"
    plain = fallback.rate_report([("Road", 95.0)], "e")
    assert plain["severity"] == "partial" and plain["confidence"] == "low" and "unrated default" in plain["reasoning"]
    assert fallback.after_looks_clear([("Trash", 90.0)])[0] is False
    assert fallback.after_looks_clear([("Road", 90.0)])[0] is True


def test_after_photo_never_clears_when_ai_is_down(drain_env, monkeypatch):
    state, answers, store = drain_env
    from functions.drain_analyze import app as da
    from functions.drains import app as api
    first = _report()
    api.handler(_admin("POST /drains/{id}/assign", {"worker": "Ramesh"}, {"id": first}), None)
    boto3.client("s3").put_object(Bucket="test-photos", Key=f"drains-after/{first}.jpg", Body=_jpeg())
    _bedrock_down(monkeypatch)
    _labels(monkeypatch, [("Road", 90.0)])
    da.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": f"drains-after/{first}.jpg"}}}]}, None)
    r = store.get(first)
    assert r["status"] == "assigned" and r["awaitingReview"] is True and not r.get("clearanceVerified")
    assert "must confirm" in r["afterNote"] and "Operation not allowed" in r["afterError"]
    d = json.loads(api.handler(_event("GET /drains/{id}", path={"id": first}), None)["body"])
    assert d["awaitingReview"] and d["status"] == "assigned" and d["afterUrl"].startswith("https://")

    # dispatcher decisions: wrong code is refused, reject keeps it open, clear marks it MANUAL
    assert api.handler(_admin("POST /drains/{id}/confirm", {"decision": "clear"}, {"id": first}, token="bad"), None)["statusCode"] == 403
    assert api.handler(_admin("POST /drains/{id}/confirm", {"decision": "maybe"}, {"id": first}), None)["statusCode"] == 400
    api.handler(_admin("POST /drains/{id}/confirm", {"decision": "reject", "note": "still silt"}, {"id": first}), None)
    assert store.get(first)["status"] == "assigned" and store.get(first)["afterRejected"] is True
    api.handler(_admin("POST /drains/{id}/confirm", {"decision": "clear"}, {"id": first}), None)
    r = store.get(first)
    assert r["status"] == "cleared" and r["clearanceVerified"] is False and r["clearedBy"] == "dispatcher"
    m = json.loads(api.handler(_event("GET /drains/metrics", qs={"city": "delhi"}), None)["body"])
    assert m["cleared"] == 1 and m["cleared_manual"] == 1 and m["cleared_ai_verified"] == 0


def test_confirm_needs_an_after_photo(drain_env):
    from functions.drains import app as api
    first = _report()
    r = api.handler(_admin("POST /drains/{id}/confirm", {"decision": "clear"}, {"id": first}), None)
    assert r["statusCode"] == 409


def test_stale_analysis_is_reported_and_retry_reanalyses(drain_env, monkeypatch):
    state, answers, store = drain_env
    from functions.drains import app as api
    up = json.loads(api.handler(_event("POST /drains/upload-url", {"lat": 28.6, "lon": 77.2, "city": "delhi",
                                                                     "deviceId": "resident-0020"}), None)["body"])
    rid = up["reportId"]
    # never uploaded: while fresh, retry is refused; once stale the API says the analysis did not finish
    retry = _event("POST /drains/{id}/retry", {"deviceId": "resident-0020"}, {"id": rid})
    assert api.handler(retry, None)["statusCode"] == 409
    store.update(rid, {"ts": int(time.time()) - 400})
    d = json.loads(api.handler(_event("GET /drains/{id}", path={"id": rid}), None)["body"])
    assert d["status"] == "error" and "did not finish" in d["rejection_reason"]
    r = api.handler(retry, None)
    assert r["statusCode"] == 409 and "never arrived" in json.loads(r["body"])["error"]
    # photo arrives but analysis crashed -> status error -> retry succeeds and re-queues
    boto3.client("s3").put_object(Bucket="test-photos", Key=f"drains/{rid}.jpg", Body=_jpeg())
    store.update(rid, {"status": "error", "rejection_reason": "Analysis failed (X). Tap retry."})
    ok = api.handler(retry, None)
    assert ok["statusCode"] == 200 and store.get(rid)["status"] == "analysing"
    assert "rejection_reason" not in store.get(rid)


def test_analyser_crash_is_visible_not_silent(drain_env, monkeypatch):
    state, answers, store = drain_env
    from common import drain_store, weather
    monkeypatch.setattr(weather, "next24h_mm", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    rid = _report()
    r = store.get(rid)
    assert r["status"] == "error" and "Tap retry" in r["rejection_reason"] and "boom" in r["analysisError"]


def test_duplicate_s3_event_is_ignored_and_conditional_write_is_atomic(drain_env):
    state, answers, store = drain_env
    from functions.drain_analyze import app as da
    rid = _report()
    before = store.get(rid)
    da.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": f"drains/{rid}.jpg"}}}]}, None)
    assert store.get(rid) == before                                     # second delivery changed nothing
    assert store.update(rid, {"severity": "partial"}, only_if_status="analysing") is False
    assert store.get(rid)["severity"] == "blocked"


def test_ungrouped_nearby_reports_are_merged_on_read_and_assignment_covers_both(drain_env):
    """GSI eventual consistency: both reports start their own group; reads and assign must still agree."""
    state, answers, store = drain_env
    from functions.drains import app as api
    a = _report()
    b = _report(lat=28.63655, device="resident-0030")
    store.update(b, {"groupId": b})                                       # simulate the race: separate groups
    rows = json.loads(api.handler(_event("GET /drains", qs={"city": "delhi"}), None)["body"])["drains"]
    assert len(rows) == 1 and rows[0]["reportCount"] == 2
    api.handler(_admin("POST /drains/{id}/assign", {"worker": "Asha"}, {"id": a}), None)
    assert store.get(a)["status"] == "assigned" and store.get(b)["status"] == "assigned"
    d = json.loads(api.handler(_event("GET /drains/{id}", path={"id": b}), None)["body"])
    assert d["status"] == "assigned" and d["assignedTo"] == "Asha"
