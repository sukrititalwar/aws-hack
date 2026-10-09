"""EventBridge every 15 min: real rainfall at every hotspot -> risk level -> SNS alert.

Open-Meteo (free, no key) gives the last 3 h (model analysis of what fell), the current hour
and the next 3 h at each hotspot. Risk levels:
  flooding_likely_now : >= RAIN_PAST3H_FLOOD_MM in the last 3 h, or >= RAIN_NOW_MM_H right now
                        -> the API adds a low-confidence *predicted* spot there (routing avoids it
                           for small vehicles) until a real report confirms or replaces it
  likely_flooded_soon : >= RAIN_NEXT3H_WARN_MM forecast in the next 3 h -> warning only
  normal
Also writes a per-city "#weather" item for the app's rain banner.

DEMO_RAIN_KEY: S3 key of {hotspotId: {"past3h": mm, "now": mm, "next3h": mm}} to replay a storm.
"""
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import boto3

from common import config, db, views

log = logging.getLogger()
log.setLevel(logging.INFO)
sns = boto3.client("sns", region_name=config.REGION)


def fetch_rain(points: list[tuple[float, float]]) -> list[dict]:
    """[{past3h, now, next3h}] per (lat, lon)."""
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{p[0]:.4f}" for p in points),
        "longitude": ",".join(f"{p[1]:.4f}" for p in points),
        "hourly": "precipitation", "current": "precipitation",
        "past_hours": 3, "forecast_hours": 3, "timezone": "Asia/Kolkata",
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=15) as r:
        data = json.loads(r.read())
    data = data if isinstance(data, list) else [data]
    out = []
    for d in data:
        p = [x or 0 for x in d["hourly"]["precipitation"]]
        out.append({"past3h": sum(p[:3]), "now": float((d.get("current") or {}).get("precipitation") or 0),
                    "next3h": sum(p[3:6])})
    return out


def risk_of(r: dict) -> str:
    if r["past3h"] >= config.RAIN_PAST3H_FLOOD_MM or r["now"] >= config.RAIN_NOW_MM_H:
        return "flooding_likely_now"
    if r["next3h"] >= config.RAIN_NEXT3H_WARN_MM:
        return "likely_flooded_soon"
    return "normal"


def handler(event, _ctx):
    demo = None
    if os.environ.get("DEMO_RAIN_KEY"):
        demo = json.loads(views.s3().get_object(Bucket=config.DATA_BUCKET, Key=os.environ["DEMO_RAIN_KEY"])["Body"].read())
    t = db.table(config.HOTSPOTS_TABLE)
    now = int(time.time())
    alerts = []
    for city, cfg in config.CITIES.items():
        hs = [h for h in db.hotspots(city) if not h["hotspotId"].startswith("#")]
        points = [(h["lat"], h["lon"]) for h in hs] + [(cfg["center"][1], cfg["center"][0])]
        try:
            rain = ([demo.get(h["hotspotId"], {"past3h": 0, "now": 0, "next3h": 0}) for h in hs] + [{"past3h": 0, "now": 0, "next3h": 0}]
                    if demo is not None else fetch_rain(points))
        except Exception:
            log.exception("rain fetch failed for %s", city)
            continue
        for h, r in zip(hs, rain):
            risk = risk_of(r)
            t.update_item(Key={"city": city, "hotspotId": h["hotspotId"]},
                          UpdateExpression="SET #r = :r, rainPast3h = :p, rainNow = :n, rainNext3h = :f, riskUpdatedAt = :t",
                          ExpressionAttributeNames={"#r": "risk"},
                          ExpressionAttributeValues=db.to_ddb({":r": risk, ":p": float(r["past3h"]), ":n": float(r["now"]),
                                                               ":f": float(r["next3h"]), ":t": now}))
            if risk != "normal" and risk != h.get("risk"):
                alerts.append((city, h, r, risk))
        c = rain[-1]
        raining = max([x["now"] for x in rain] + [0])
        t.put_item(Item=db.to_ddb({
            "city": city, "hotspotId": "#weather", "rainNow": float(c["now"]), "rainPast3h": float(c["past3h"]),
            "rainNext3h": float(c["next3h"]), "maxRainNowAtHotspots": float(raining),
            "hotspotsAtRisk": sum(1 for r in rain[:-1] if risk_of(r) != "normal"),
            "updatedAt": now, "source": "Open-Meteo forecast API (model data, CC BY 4.0)"}))

    if alerts and config.ALERTS_TOPIC_ARN:
        for city in {a[0] for a in alerts}:
            now_l = [a for a in alerts if a[0] == city and a[3] == "flooding_likely_now"]
            soon_l = [a for a in alerts if a[0] == city and a[3] == "likely_flooded_soon"]
            parts = []
            if now_l:
                parts.append("Heavy rain now. Likely flooded: " + ", ".join(a[1]["name"] for a in now_l[:5]) + ".")
            if soon_l:
                parts.append("Heavy rain expected in 3 h at: " + ", ".join(a[1]["name"] for a in soon_l[:5]) + ".")
            sns.publish(TopicArn=config.ALERTS_TOPIC_ARN, Subject=f"Rain warning: {config.CITIES[city]['label']}",
                        Message=" ".join(parts) + " Avoid underpasses on a scooter or small car. Check the app for a safe route.",
                        MessageAttributes={"audience": {"DataType": "String", "StringValue": "all"}})
    log.info("risk update done, %d hotspots changed to at-risk", len(alerts))
    return {"newly_at_risk": len(alerts)}
