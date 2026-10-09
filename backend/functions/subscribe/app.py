"""POST /subscriptions  {contact: email | +91.. phone, vehicle, name?, route: GeoJSON LineString}

Subscribes the contact to the shared SNS alerts topic with a filter policy, so it only receives
alerts for its own route plus city-wide rain warnings.
"""
import json
import re
import time
import uuid

import boto3

from common import config, db, http

sns = boto3.client("sns", region_name=config.REGION)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


def handler(event, _ctx):
    try:
        b = http.body(event)
    except ValueError as e:
        return http.bad(str(e))
    contact = str(b.get("contact") or "").strip()
    vehicle = b.get("vehicle")
    route = b.get("route") or {}
    if EMAIL.match(contact):
        protocol = "email"
    elif PHONE.match(contact):
        protocol = "sms"
    else:
        return http.bad("contact must be an email or a phone number like +919812345678")
    if vehicle not in config.VEHICLES:
        return http.bad("bad vehicle")
    coords = route.get("coordinates") if route.get("type") == "LineString" else None
    if not coords or len(coords) < 2 or len(coords) > 5000:
        return http.bad("route must be a GeoJSON LineString")

    sub_id = uuid.uuid4().hex[:12]
    arn = sns.subscribe(
        TopicArn=config.ALERTS_TOPIC_ARN, Protocol=protocol, Endpoint=contact,
        Attributes={"FilterPolicy": json.dumps({"audience": [sub_id, "all"]})},
        ReturnSubscriptionArn=True,
    )["SubscriptionArn"]
    db.table(config.SUBSCRIPTIONS_TABLE).put_item(Item=db.to_ddb({
        "subId": sub_id, "vehicle": vehicle, "name": str(b.get("name") or "My route")[:60],
        "route": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "protocol": protocol, "snsSubscriptionArn": arn, "createdAt": int(time.time()),
    }))
    note = ("Check your inbox and click the AWS confirmation link to start alerts."
            if protocol == "email" else "SMS alerts are on.")
    return http.resp(200, {"subId": sub_id, "note": note})
