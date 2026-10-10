"""Per-device hourly counter in DynamoDB (TTL cleans it up)."""
import time

from botocore.exceptions import ClientError

from . import config, db


def limited(bucket: str, device_id: str, limit: int) -> bool:
    """True if this device already used `limit` actions of kind `bucket` this hour."""
    hour = int(time.time() // 3600)
    try:
        db.table(config.RATELIMIT_TABLE).update_item(
            Key={"key": f"{bucket}#{device_id}#{hour}"},
            UpdateExpression="ADD n :one SET expiresAt = :exp",
            ConditionExpression="attribute_not_exists(n) OR n < :lim",
            ExpressionAttributeValues={":one": 1, ":lim": limit, ":exp": (hour + 2) * 3600},
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise
