"""DynamoDB access for drain reports. Table: PK reportId, GSI byCity (city, ts)."""
import time
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from . import config, db, drains


def table():
    return db.table(config.DRAINS_TABLE)


def put(item: dict):
    table().put_item(Item=db.to_ddb(item))


def get(report_id: str) -> dict | None:
    it = table().get_item(Key={"reportId": report_id}).get("Item")
    return db.from_ddb(it) if it else None


def update(report_id: str, fields: dict, only_if_status: str | None = None, remove: list[str] | None = None) -> bool:
    """SET fields (None values are skipped). With only_if_status the write is atomic and returns
    False if the report is no longer in that status (a duplicate S3 event or a concurrent change)."""
    from botocore.exceptions import ClientError
    fields = db.to_ddb(fields)
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields) if fields else ""
    if remove:
        expr += (" " if expr else "") + "REMOVE " + ", ".join(f"#{k}" for k in remove)
    names = {f"#{k}": k for k in [*fields, *(remove or [])]}
    values = {f":{k}": v for k, v in fields.items()}
    kw = {"Key": {"reportId": report_id}, "UpdateExpression": expr, "ExpressionAttributeNames": names}
    if values:
        kw["ExpressionAttributeValues"] = values
    if only_if_status:
        kw["ConditionExpression"] = "#status = :__expected"
        kw["ExpressionAttributeNames"]["#status"] = "status"
        kw.setdefault("ExpressionAttributeValues", {})[":__expected"] = only_if_status
    try:
        table().update_item(**kw)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


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


def group_ids(city: str, any_id: str) -> list[str]:
    """Every report id in the blockage that contains `any_id`, as the priority list shows it
    (grouping is recomputed from the data, so this matches what the user sees)."""
    for row in drains.build_groups(for_city(city)):
        if any_id == row["groupId"] or any_id in row["reportIds"]:
            return row["reportIds"]
    return [any_id]


def update_group(city: str, any_id: str, fields: dict, remove: list[str] | None = None):
    """Apply the same change to every report in a blockage (status lives on all of them)."""
    for rid in group_ids(city, any_id):
        update(rid, fields, remove=remove)
