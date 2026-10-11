"""Signed-in user profile and saved addresses (Home, Work, other frequent places).

All routes sit behind the API Gateway Cognito JWT authorizer: the gateway has already verified the
token's signature, issuer, audience and expiry, so `sub` below is trustworthy. Every query is keyed
by that `sub`, so one user can never read or change another user's places.

  GET    /me                 -> {sub, email, groups}
  GET    /me/places          -> {places: [...]}
  POST   /me/places          {label, kind: home|work|other, address?, lat, lon, city?}
  DELETE /me/places/{id}
"""
import time
import uuid

from boto3.dynamodb.conditions import Key

from common import config, db, geo, http

MAX_PLACES = 20
KINDS = ("home", "work", "other")


def _claims(event) -> dict:
    return (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}


def _table():
    return db.table(config.PLACES_TABLE)


def _list(user: str) -> list[dict]:
    items = [db.from_ddb(i) for i in _table().query(KeyConditionExpression=Key("userId").eq(user)).get("Items", [])]
    items.sort(key=lambda p: (KINDS.index(p["kind"]) if p.get("kind") in KINDS else 9, p.get("createdAt", 0)))
    return items


def _public(p: dict) -> dict:
    return {k: p[k] for k in ("placeId", "label", "kind", "address", "lat", "lon", "city", "createdAt") if k in p}


def _groups(claims: dict) -> list[str]:
    raw = claims.get("cognito:groups") or ""
    if isinstance(raw, list):
        return raw
    return [g for g in str(raw).strip("[]").replace(",", " ").split() if g]


def add_place(user: str, event):
    b = http.body(event)
    label = str(b.get("label") or "").strip()
    kind = b.get("kind") or "other"
    lat, lon = b.get("lat"), b.get("lon")
    if not (1 <= len(label) <= 40):
        return http.bad("Give the place a short name (1 to 40 characters).")
    if kind not in KINDS:
        return http.bad("kind must be home, work or other")
    if not geo.valid_lonlat(lon, lat):
        return http.bad("lat/lon missing or out of range")
    city = str(b.get("city") or "").lower() or None
    if city and city not in config.CITIES:
        return http.bad("unsupported city")
    existing = _list(user)
    # Home and Work are single slots: saving a new one replaces the old one.
    replaced = [p for p in existing if kind in ("home", "work") and p.get("kind") == kind]
    if len(existing) - len(replaced) >= MAX_PLACES:
        return http.bad(f"You can save up to {MAX_PLACES} places. Delete one first.", 409)
    for p in replaced:
        _table().delete_item(Key={"userId": user, "placeId": p["placeId"]})
    item = {"userId": user, "placeId": uuid.uuid4().hex[:12], "label": label[:40], "kind": kind,
            "address": (str(b["address"]).strip()[:200] if b.get("address") else None),
            "lat": float(lat), "lon": float(lon), "city": city, "createdAt": int(time.time())}
    _table().put_item(Item=db.to_ddb(item))
    return http.resp(200, {"place": _public(item), "replaced": [p["placeId"] for p in replaced]})


def handler(event, _ctx):
    claims = _claims(event)
    user = claims.get("sub")
    if not user:                       # the gateway should have refused already; never trust a missing sub
        return http.bad("Please sign in.", 401)
    route = event.get("routeKey", "")
    try:
        if route == "GET /me":
            return http.resp(200, {"sub": user, "email": claims.get("email"), "groups": _groups(claims)})
        if route == "GET /me/places":
            return http.resp(200, {"places": [_public(p) for p in _list(user)]})
        if route == "POST /me/places":
            return add_place(user, event)
        if route == "DELETE /me/places/{id}":
            pid = http.path_param(event, "id")
            _table().delete_item(Key={"userId": user, "placeId": str(pid)})   # scoped to this user by the key
            return http.resp(200, {"ok": True})
    except ValueError as e:
        return http.bad(str(e))
    return http.bad("not found", 404)
