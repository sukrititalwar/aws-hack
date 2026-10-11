"""Saved places: per-user isolation, validation, Home/Work slots, limits (moto; the JWT is the gateway's job)."""
import json

import boto3
import pytest

from tests.test_handlers import aws  # noqa: F401  (fixture)


def ev(route, sub="user-a", body=None, path=None, email="a@example.com", groups=None):
    claims = {"sub": sub, "email": email}
    if groups is not None:
        claims["cognito:groups"] = groups
    return {"routeKey": route, "body": json.dumps(body) if body is not None else None, "pathParameters": path,
            "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


@pytest.fixture
def places(aws, monkeypatch):  # noqa: F811
    from common import config, db
    monkeypatch.setattr(config, "PLACES_TABLE", "SavedPlaces")
    boto3.client("dynamodb").create_table(
        TableName="SavedPlaces", BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "userId", "AttributeType": "S"}, {"AttributeName": "placeId", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "userId", "KeyType": "HASH"}, {"AttributeName": "placeId", "KeyType": "RANGE"}])
    db._ddb.cache_clear()
    from functions.places import app
    return app


def add(app, **kw):
    body = {"label": "Home", "kind": "home", "lat": 28.6139, "lon": 77.209, "address": "Connaught Place, New Delhi", "city": "delhi"}
    body.update(kw.pop("body", {}))
    return app.handler(ev("POST /me/places", body=body, **kw), None)


def listing(app, **kw):
    return json.loads(app.handler(ev("GET /me/places", **kw), None)["body"])["places"]


def test_requires_a_signed_in_user(places):
    r = places.handler({"routeKey": "GET /me/places", "requestContext": {}}, None)
    assert r["statusCode"] == 401


def test_profile_reads_claims(places):
    r = json.loads(places.handler(ev("GET /me", groups="[dispatchers admins]"), None)["body"])
    assert r == {"sub": "user-a", "email": "a@example.com", "groups": ["dispatchers", "admins"]}


def test_add_list_delete_roundtrip(places):
    r = add(places)
    assert r["statusCode"] == 200
    p = json.loads(r["body"])["place"]
    assert p["label"] == "Home" and p["lat"] == 28.6139 and "userId" not in p
    assert [x["placeId"] for x in listing(places)] == [p["placeId"]]
    assert places.handler(ev("DELETE /me/places/{id}", path={"id": p["placeId"]}), None)["statusCode"] == 200
    assert listing(places) == []


def test_users_cannot_see_or_delete_each_others_places(places):
    p = json.loads(add(places, sub="user-a")["body"])["place"]
    assert listing(places, sub="user-b") == []
    places.handler(ev("DELETE /me/places/{id}", sub="user-b", path={"id": p["placeId"]}), None)   # other user's id
    assert len(listing(places, sub="user-a")) == 1


def test_home_and_work_are_single_slots_other_is_not(places):
    add(places, body={"label": "Home", "kind": "home"})
    r = json.loads(add(places, body={"label": "New flat", "kind": "home", "lat": 28.5}) ["body"])
    assert len(r["replaced"]) == 1
    add(places, body={"label": "Office", "kind": "work"})
    add(places, body={"label": "Gym", "kind": "other"})
    add(places, body={"label": "Mum's", "kind": "other"})
    got = listing(places)
    assert [p["kind"] for p in got] == ["home", "work", "other", "other"]    # ordered home, work, others
    assert [p["label"] for p in got][:2] == ["New flat", "Office"]


@pytest.mark.parametrize("body,msg", [
    ({"label": ""}, "short name"), ({"label": "x" * 41}, "short name"), ({"kind": "castle"}, "kind"),
    ({"lat": 200}, "lat/lon"), ({"city": "atlantis"}, "city"),
])
def test_validation(places, body, msg):
    r = add(places, body=body)
    assert r["statusCode"] == 400 and msg in json.loads(r["body"])["error"]


def test_limit_of_20_places(places):
    for i in range(20):
        assert add(places, body={"label": f"P{i}", "kind": "other"})["statusCode"] == 200
    r = add(places, body={"label": "one too many", "kind": "other"})
    assert r["statusCode"] == 409
    # but Home can still be replaced at the limit
    assert add(places, body={"label": "Home", "kind": "home"})["statusCode"] == 409   # no home yet, so it counts as new


def test_unknown_route(places):
    assert places.handler(ev("PATCH /me/places"), None)["statusCode"] == 404
