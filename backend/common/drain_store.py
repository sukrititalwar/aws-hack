"""DynamoDB access for drain reports. Table: PK reportId, GSI byCity (city, ts)."""
import time
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from . import config, db


def table():
    return db.table(config.DRAINS_TABLE)


def put(item: dict):
    table().put_item(Item=db.to_ddb(item))


def get(report_id: str) -> dict | None:
    it = table().get_item(Key={"reportId": report_id}).get("Item")
    return db.from_ddb(it) if it else None


def update(report_id: str, fields: dict):
    fields = db.to_ddb(fields)
    table().update_item(
        Key={"reportId": report_id},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames={f"#{k}": k for k in fields},
        ExpressionAttributeValues={f":{k}": v for k, v in fields.items()})


def for_city(city: str, days: int = 90) -> list[dict]:
    since = Decimal(int(time.time() - days * 86400))
    items, kw = [], {"IndexName": "byCity", "KeyConditionExpression": Key("city").eq(city) & Key("ts").gte(since)}
    while True:
        page = table().query(**kw)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return [db.from_ddb(i) for i in items]
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def members(city: str, group_id: str) -> list[dict]:
    return [r for r in for_city(city) if (r.get("groupId") or r["reportId"]) == group_id]


def update_group(city: str, group_id: str, fields: dict):
    """Apply the same change to every report in a blockage group (status lives on all of them)."""
    for m in members(city, group_id):
        update(m["reportId"], fields)
