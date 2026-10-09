"""End-to-end handler smoke tests against moto (mocked DynamoDB/S3). Bedrock and Rekognition
are stubbed, so this checks our wiring: upload-url -> analyze -> reports/spots -> vote -> route."""
import gzip
import json
import os

import boto3
import pytest

moto = pytest.importorskip("moto")

os.environ.update({
    "AWS_DEFAULT_REGION": "ap-south-1", "AWS_REGION": "ap-south-1",
    "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
    "PHOTOS_BUCKET": "test-photos", "DATA_BUCKET": "test-photos",
    "REPORTS_TABLE": "Reports", "HOTSPOTS_TABLE": "Hotspots",
    "SUBSCRIPTIONS_TABLE": "Subscriptions", "RATELIMIT_TABLE": "RateLimits", "WA_SESSIONS_TABLE": "WhatsAppSessions",
})

FLOOD = {"is_flooded_road_photo": True, "depth_cm_low": 20, "depth_cm_high": 30, "confidence": "high",
         "reference_objects": [{"object": "car tyre", "observation": "half covered", "implied_depth_cm": 30}],
         "reasoning": "Water covers half the car tyre.", "reasoning_hi": "पानी कार के आधे टायर तक है।",
         "flowing_water": False, "hazards": ["none"], "location_type": "underpass", "image_quality": "good"}


def _event(route, body=None, path=None, qs=None):
    return {"routeKey": route, "body": json.dumps(body) if body is not None else None,
            "pathParameters": path, "queryStringParameters": qs,
            "requestContext": {"http": {"sourceIp": "1.2.3.4"}}}


@pytest.fixture
def aws(monkeypatch):
    from common import config
    for k in ["PHOTOS_BUCKET", "DATA_BUCKET", "REPORTS_TABLE", "HOTSPOTS_TABLE",
              "SUBSCRIPTIONS_TABLE", "RATELIMIT_TABLE", "WA_SESSIONS_TABLE"]:
        monkeypatch.setattr(config, k, os.environ[k])
    monkeypatch.setattr(config, "REGION", "ap-south-1")
    with moto.mock_aws():
        ddb = boto3.client("dynamodb")
        ddb.create_table(
            TableName="Reports", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": t} for n, t in
                                  [("reportId", "S"), ("cell", "S"), ("cityMode", "S"), ("ts", "N")]],
            KeySchema=[{"AttributeName": "reportId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {"IndexName": ix, "Projection": {"ProjectionType": "ALL"},
                 "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": "ts", "KeyType": "RANGE"}]}
                for ix, pk in [("byCell", "cell"), ("byCity", "cityMode")]])
        ddb.create_table(TableName="Hotspots", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "city", "AttributeType": "S"},
                                               {"AttributeName": "hotspotId", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "city", "KeyType": "HASH"},
                                    {"AttributeName": "hotspotId", "KeyType": "RANGE"}])
        for name, key in [("RateLimits", "key"), ("Subscriptions", "subId"), ("WhatsAppSessions", "user")]:
            ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                             AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                             KeySchema=[{"AttributeName": key, "KeyType": "HASH"}])
        boto3.client("s3").create_bucket(Bucket="test-photos",
                                         CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        from common import db, views
        db._ddb.cache_clear()
        views.s3.cache_clear()
        yield


def test_full_flow(aws, monkeypatch):
    from io import BytesIO

    from PIL import Image

    from common import depth
    from functions.analyze import app as analyze
    from functions.reports import app as reports
    from functions.route import app as route
    from functions.upload_url import app as upload
    from functions.vote import app as vote

    # 1. upload url
    r = upload.handler(_event("POST /reports/upload-url",
                              {"lat": 19.101, "lon": 72.8505, "city": "mumbai", "place": "Test subway",
                               "deviceId": "device-123456"}), None)
    assert r["statusCode"] == 200, r
    out = json.loads(r["body"])
    rid = out["reportId"]
    assert out["fields"]["key"] == f"uploads/{rid}.jpg"

    # 2. "upload" + analyze with stubbed Rekognition and Bedrock
    buf = BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 160)).save(buf, "JPEG")
    boto3.client("s3").put_object(Bucket="test-photos", Key=f"uploads/{rid}.jpg", Body=buf.getvalue())
    monkeypatch.setattr(analyze, "_unsafe", lambda b, k: None)
    monkeypatch.setattr(depth, "estimate_depth",
                        lambda img, city, place: (depth.normalise(FLOOD), {"latency_ms": 1234}))
    analyze.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"},
                                         "object": {"key": f"uploads/{rid}.jpg"}}}]}, None)

    # 3. poll
    got = json.loads(reports.handler(_event("GET /reports/{id}", path={"id": rid}), None)["body"])
    assert got["status"] == "live"
    assert got["verdicts"]["scooter"]["verdict"] == "NO_GO"
    assert got["verdicts"]["suv"]["verdict"] == "RISKY"
    assert "deviceHash" not in got and "phash" not in got
    assert got["photoUrl"].startswith("https://")

    # 4. spots
    spots = json.loads(reports.handler(_event("GET /spots", qs={"city": "mumbai"}), None)["body"])["spots"]
    assert len(spots) == 1 and spots[0]["depth_high"] == 30

    # 5. vote once ok, twice rejected
    ev = _event("POST /reports/{id}/vote", {"type": "still_flooded", "deviceId": "voter-9999999"}, {"id": rid})
    assert vote.handler(ev, None)["statusCode"] == 200
    assert vote.handler(ev, None)["statusCode"] == 409

    # 6. route around it on the synthetic grid from test_routing
    from tests.test_routing import EDGES, NODES
    gz = gzip.compress(json.dumps({"nodes": NODES, "edges": EDGES}).encode())
    boto3.client("s3").put_object(Bucket="test-photos", Key="graphs/mumbai.json.gz", Body=gz)
    route._GRAPHS.clear()
    res = json.loads(route.handler(_event("POST /route", {"from": NODES[0], "to": NODES[2],
                                                          "vehicle": "scooter", "city": "mumbai"}), None)["body"])
    assert res["normal"]["distance_m"] == 210
    assert res["safe"]["distance_m"] == 432
    assert res["avoided_spots"][0]["spotId"] == rid

    # SUV: spot is only RISKY (30 cm); detour 432 < 105*5+105, so it also detours but isn't blocked
    res_suv = json.loads(route.handler(_event("POST /route", {"from": NODES[0], "to": NODES[2],
                                                              "vehicle": "suv", "city": "mumbai"}), None)["body"])
    assert res_suv["safe"] is not None


def test_rate_limit(aws):
    from functions.upload_url import app as upload
    body = {"lat": 19.1, "lon": 72.85, "city": "mumbai", "deviceId": "spammy-device"}
    codes = [upload.handler(_event("POST /reports/upload-url", body), None)["statusCode"] for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_validation(aws):
    from functions.route import app as route
    from functions.upload_url import app as upload
    assert upload.handler(_event("POST", {"lat": 200, "lon": 72, "deviceId": "x" * 10}), None)["statusCode"] == 400
    assert route.handler(_event("POST", {"from": [72, 19], "to": [72, 19], "vehicle": "tank"}), None)["statusCode"] == 400
