"""POST /reports/{id}/vote  {type: still_flooded|cleared|wrong, deviceId}

One vote per device per report. "still_flooded" refreshes the report's freshness timer.
"""
import hashlib
import time

from botocore.exceptions import ClientError

from common import config, db, http

VOTE_FIELD = {"still_flooded": "still", "cleared": "cleared", "wrong": "wrong"}


def handler(event, _ctx):
    rid = http.path_param(event, "id")
    try:
        b = http.body(event)
    except ValueError as e:
        return http.bad(str(e))
    vtype = b.get("type")
    device = str(b.get("deviceId") or "")
    if vtype not in VOTE_FIELD:
        return http.bad("type must be still_flooded, cleared or wrong")
    if len(device) < 8:
        return http.bad("deviceId required")
    voter = hashlib.sha256(device.encode()).hexdigest()[:16]

    report = db.get_report(rid)
    if not report or report.get("status") != "live":
        return http.bad("report not found or not live", 404)

    now = int(time.time())
    expr = "ADD votes.#f :one, voters :me"
    values = {":one": 1, ":me": {voter}, ":voter": voter}
    if vtype == "still_flooded" and report.get("mode") == "live":
        expr += " SET lastStillTs = :now, expiresAt = :exp"
        values.update({":now": now, ":exp": now + config.EXPIRE_AFTER_H * 3600})
    try:
        r = db.table(config.REPORTS_TABLE).update_item(
            Key={"reportId": rid},
            UpdateExpression=expr,
            ConditionExpression="attribute_not_exists(voters) OR NOT contains(voters, :voter)",
            ExpressionAttributeNames={"#f": VOTE_FIELD[vtype]},
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return http.bad("You already voted on this report.", 409)
        raise
    return http.resp(200, {"votes": db.from_ddb(r["Attributes"].get("votes", {}))})
