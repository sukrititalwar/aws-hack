"""WhatsApp channel: conversation logic + two providers.

Providers
  twilio : Twilio WhatsApp sandbox/number. Inbound webhook -> API Gateway; replies via REST.
           Credentials in SSM Parameter Store (SecureString) under WA_SSM_PREFIX.
  aws    : AWS End User Messaging Social (native WhatsApp Business in AWS). Inbound events arrive
           on an SNS topic; media is fetched to S3 with GetWhatsAppMessageMedia; replies with
           SendWhatsAppMessage.

Conversation (per sender, kept 30 min in the WhatsAppSessions table)
  photo + location (either order) -> report -> analyze Lambda -> verdict reply
  location only                   -> nearby flooded spots for the sender's vehicle
  "car" / "bus" / "scooter" / "EV scooter" ... -> sets the vehicle; "hindi" / "english" -> language
  any other text                  -> matches a known flood spot name, else help
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from functools import lru_cache

import boto3

from . import config, db, geo, social, views

log = logging.getLogger()
SESSION_TTL = 30 * 60
SSM_PREFIX = os.environ.get("WA_SSM_PREFIX", "/scooter-cross/whatsapp")

VEHICLE_WORDS = {
    "walk": "pedestrian", "walking": "pedestrian", "पैदल": "pedestrian", "cycle": "bicycle", "bicycle": "bicycle",
    "scooter": "scooter", "scooty": "scooter", "bike": "scooter", "motorcycle": "scooter", "स्कूटर": "scooter",
    "ev": "ev_scooter", "ईवी": "ev_scooter",
    "auto": "auto", "rickshaw": "auto", "ऑटो": "auto", "car": "car", "कार": "car", "suv": "suv",
    "bus": "bus", "बस": "bus", "truck": "bus", "ambulance": "ambulance",
}
EV_SCOOTER_PHRASES = {"e-scooter", "ev scooter", "electric scooter", "ई-स्कूटर", "ई स्कूटर", "ईवी स्कूटर", "इलेक्ट्रिक स्कूटर"}
ICON = {"pedestrian": "🚶", "bicycle": "🚲", "scooter": "🛵", "ev_scooter": "🛵", "auto": "🛺", "car": "🚗", "suv": "🚙", "bus": "🚌", "ambulance": "🚑"}
GLYPH = {"GO": "✅", "RISKY": "⚠️", "NO_GO": "⛔"}

HELP = {
    "en": ("🌊 *Can My Scooter Cross?*\n"
           "1️⃣ Send a *photo* of the flooded road\n"
           "2️⃣ Send your *location* (📎 → Location → Send current location)\n"
           "I'll reply with the water depth and whether your vehicle can cross.\n\n"
           "• Send just a location to see flooded spots near you\n"
           "• Send a place name (e.g. *Minto Bridge*) for its status\n"
           "• Your vehicle: reply *scooter*, *EV scooter*, *car*, *bus*, *auto*, *walk*…  • *हिंदी* for Hindi"),
    "hi": ("🌊 *क्या मेरा स्कूटर पार कर सकता है?*\n"
           "1️⃣ पानी भरी सड़क की *फ़ोटो* भेजें\n"
           "2️⃣ अपनी *लोकेशन* भेजें (📎 → Location)\n"
           "मैं पानी की गहराई और आपकी गाड़ी के लिए फ़ैसला बताऊँगा।\n\n"
           "• सिर्फ़ लोकेशन भेजें: आस-पास पानी भरी जगहें\n"
           "• जगह का नाम भेजें (जैसे *मिंटो ब्रिज*)\n"
           "• गाड़ी: *scooter*, *ईवी स्कूटर*, *car*, *bus*, *auto*… • *English* के लिए English लिखें"),
}


def user_key(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:24]


def get_session(phone: str) -> dict:
    it = db.table(config.WA_SESSIONS_TABLE).get_item(Key={"user": user_key(phone)}).get("Item")
    s = db.from_ddb(it) if it else {}
    return s if s.get("expiresAt", 0) > time.time() else {"vehicle": s.get("vehicle", "scooter"), "lang": s.get("lang", "en")}


def save_session(phone: str, s: dict):
    s = {k: v for k, v in s.items() if v is not None}
    s.update({"user": user_key(phone), "expiresAt": int(time.time() + SESSION_TTL)})
    # Keep vehicle/lang preference longer than the photo/location state.
    db.table(config.WA_SESSIONS_TABLE).put_item(Item=db.to_ddb(s))


def city_for(lon: float, lat: float) -> str:
    for c, cfg in config.CITIES.items():
        mnx, mny, mxx, mxy = cfg["bbox"]
        if mnx <= lon <= mxx and mny <= lat <= mxy:
            return c
    return min(config.CITIES, key=lambda c: geo.haversine_m(lon, lat, *config.CITIES[c]["center"]))


# ---------------- conversation ----------------

def handle(phone: str, msg: dict, channel: dict) -> str | None:
    """msg: {type: text|image|location, text?, lat?, lon?, fetch_media?: () -> bytes}.
    channel: how to reply later ({"provider": "twilio"|"aws", ...}). Returns the immediate reply."""
    s = get_session(phone)
    lang = s.get("lang", "en")
    now = time.time()

    if msg["type"] == "image":
        img = msg["fetch_media"]()
        key = f"wa-pending/{uuid.uuid4().hex}.jpg"
        views.s3().put_object(Bucket=config.PHOTOS_BUCKET, Key=key, Body=img, ContentType="image/jpeg")
        if s.get("lat") is not None and now - s.get("locTs", 0) < 15 * 60:
            return _create_report(phone, s, key, s["lon"], s["lat"], channel, msg.get("text"))
        s.update({"pendingKey": key, "pendingTs": int(now), "pendingCaption": msg.get("text")})
        save_session(phone, s)
        return ("📍 Got the photo. Now send the *location* of the flooded spot (📎 → Location)."
                if lang == "en" else "📍 फ़ोटो मिल गई। अब उस जगह की *लोकेशन* भेजें (📎 → Location)।")

    if msg["type"] == "location":
        lon, lat = float(msg["lon"]), float(msg["lat"])
        if s.get("pendingKey") and now - s.get("pendingTs", 0) < 15 * 60:
            key = s.pop("pendingKey")
            return _create_report(phone, s, key, lon, lat, channel, s.pop("pendingCaption", None))
        s.update({"lat": lat, "lon": lon, "locTs": int(now)})
        save_session(phone, s)
        return nearby_text(lon, lat, s.get("vehicle", "scooter"), lang)

    text = (msg.get("text") or "").strip()
    low = text.lower()
    if low in ("hindi", "हिंदी", "hi-in"):
        s["lang"] = "hi"
        save_session(phone, s)
        return HELP["hi"]
    if low in ("english", "eng"):
        s["lang"] = "en"
        save_session(phone, s)
        return HELP["en"]
    words = re.findall(r"[\wऀ-ॿ]+", low)
    ev_phrase = " ".join(words[:2])
    veh = "ev_scooter" if low in EV_SCOOTER_PHRASES or ev_phrase in EV_SCOOTER_PHRASES else next(
        (VEHICLE_WORDS[w] for w in words if w in VEHICLE_WORDS), None)
    if veh and len(words) <= 3:
        s["vehicle"] = veh
        save_session(phone, s)
        if veh == "ev_scooter":
            label = "EV Scooter" if lang == "en" else "ई-स्कूटर"
        else:
            label = veh
        return (f"{ICON[veh]} OK, verdicts for *{label}*. Send a photo + location, or just a location."
                if lang == "en" else f"{ICON[veh]} ठीक है, अब *{label}* के लिए बताऊँगा।")
    if low in ("", "hi", "hello", "help", "start", "menu", "join", "नमस्ते") or low.startswith("join "):
        return HELP[lang]
    return place_status_text(text, s.get("vehicle", "scooter"), lang) or HELP[lang]


def _create_report(phone, s, pending_key, lon, lat, channel, caption) -> str:
    city = city_for(lon, lat)
    rid = uuid.uuid4().hex[:16]
    key = f"uploads/{rid}.jpg"
    now = int(time.time())
    db.put_report({
        "reportId": rid, "city": city, "mode": "live", "cell": db.cell_key("live", city, lat, lon),
        "cityMode": f"live#{city}", "lat": lat, "lon": lon, "place": (caption or None) and caption[:120],
        "deviceHash": user_key(phone)[:16], "createdAt": now, "ts": now, "status": "analysing",
        "s3Key": key, "source_type": "photo", "source_platform": "whatsapp",
        "votes": {"still": 0, "cleared": 0, "wrong": 0}, "expiresAt": now + config.EXPIRE_AFTER_H * 3600,
        # Phone is kept only until the verdict is sent, then removed by the analyze Lambda.
        "replyTo": {**channel, "to": phone, "vehicle": s.get("vehicle", "scooter"), "lang": s.get("lang", "en")},
    })
    # Copy into uploads/ -> triggers the same analyze pipeline as the app.
    views.s3().copy_object(Bucket=config.PHOTOS_BUCKET, Key=key, CopySource={"Bucket": config.PHOTOS_BUCKET, "Key": pending_key},
                           ContentType="image/jpeg", MetadataDirective="REPLACE")
    s.pop("pendingKey", None)
    s.update({"lat": lat, "lon": lon, "locTs": now})
    save_session(phone, s)
    return ("🔎 Checking the water depth… reply in about 15 seconds."
            if s.get("lang", "en") == "en" else "🔎 पानी की गहराई जाँच रहे हैं… लगभग 15 सेकंड।")


def verdict_text(report: dict, vehicle: str, lang: str) -> str:
    if report.get("status") != "live":
        return ("❌ " + (report.get("rejection_reason") or "Could not analyse the photo.")
                + ("\nTry a photo showing the water next to a kerb, tyre or person." if lang == "en" else ""))
    v = report["verdicts"][vehicle]
    lines = [f"🌊 *{report.get('place') or 'Flooded spot'}*: about *{round(report['depth_low'])}–{round(report['depth_high'])} cm*"]
    if report.get("danger"):
        lines.append("⚡ *DANGER: electric wire/pole in water. Stay away.*")
    lines.append(f"{ICON[vehicle]} {GLYPH[v['verdict']]} *{v['label_en'] if lang == 'en' else v['label_hi']}*")
    lines.append(v["why"] if lang == "en" else v["why_hi"])
    lines.append(" ".join(f"{ICON[k]}{GLYPH[x['verdict']]}" for k, x in report["verdicts"].items()))
    reason = report.get("reasoning") if lang == "en" else (report.get("reasoning_hi") or report.get("reasoning"))
    if reason:
        lines.append(f"_“{reason}”_")
    if config.APP_URL:
        lines.append(f"🗺️ Safe route: {config.APP_URL}/?city={report['city']}&lat={report['lat']:.5f}&lon={report['lon']:.5f}")
    lines.append("⚠️ Estimate from a photo. If unsure, don't cross. Emergency: 112." if lang == "en"
                 else "⚠️ फ़ोटो से अनुमान। शक हो तो पार न करें। आपात स्थिति: 112")
    return "\n".join(lines)


def nearby_text(lon, lat, vehicle, lang) -> str:
    city = city_for(lon, lat)
    d = 0.02  # ~2 km box
    spots_ = db.active_spots(city, "live", [lon - d, lat - d, lon + d, lat + d])
    spots_.sort(key=lambda s: geo.haversine_m(lon, lat, s["lon"], s["lat"]))
    if not spots_:
        return ("✅ No flooded spots reported within ~2 km right now. Send a photo if you see one."
                if lang == "en" else "✅ अभी ~2 किमी में कोई पानी भरी जगह रिपोर्ट नहीं है।")
    out = [f"{ICON[vehicle]} Flooded spots near you:" if lang == "en" else f"{ICON[vehicle]} आपके पास पानी भरी जगहें:"]
    for s in spots_[:5]:
        dist = geo.haversine_m(lon, lat, s["lon"], s["lat"])
        tag = " (predicted from rain)" if s.get("predicted") else f" · {s['reportCount']} report(s), {s['ageMin']} min ago"
        out.append(f"{GLYPH[s['verdicts'][vehicle]]} {s.get('place') or 'Spot'} – {dist / 1000:.1f} km, ~{s['depth_high']} cm{tag}")
    if config.APP_URL:
        out.append(f"🗺️ {config.APP_URL}/?city={city}")
    return "\n".join(out)


def place_status_text(text: str, vehicle: str, lang: str) -> str | None:
    for city in config.CITIES:
        hs = [h for h in db.hotspots(city) if not h["hotspotId"].startswith("#")]
        h = social.match_hotspot(text, hs)
        if not h:
            continue
        d = 0.003
        near = [s for s in db.active_spots(city, "live", [h["lon"] - d, h["lat"] - d, h["lon"] + d, h["lat"] + d])]
        if near:
            s = near[0]
            kind = "predicted from heavy rain" if s.get("predicted") else f"{s['reportCount']} report(s), {s['ageMin']} min ago"
            return (f"🌊 *{h['name']}*: about {s['depth_low']}–{s['depth_high']} cm ({kind})\n"
                    f"{ICON[vehicle]} {GLYPH[s['verdicts'][vehicle]]} {vehicle}: {s['verdicts'][vehicle].replace('_', '-')}")
        rain = h.get("rainPast3h") or 0
        return (f"✅ *{h['name']}*: no flooding reported right now (rain last 3 h: {rain:.0f} mm). "
                f"It usually floods in heavy rain, so check before entering.")
    return None


# ---------------- providers ----------------

@lru_cache(maxsize=None)
def twilio_creds() -> dict:
    ssm = boto3.client("ssm", region_name=config.REGION)
    names = [f"{SSM_PREFIX}/twilio_account_sid", f"{SSM_PREFIX}/twilio_auth_token", f"{SSM_PREFIX}/twilio_from"]
    r = ssm.get_parameters(Names=names, WithDecryption=True)
    vals = {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in r["Parameters"]}
    return {"sid": vals.get("twilio_account_sid"), "token": vals.get("twilio_auth_token"),
            "from": vals.get("twilio_from", "whatsapp:+14155238886")}


def twilio_signature_ok(url: str, params: dict, signature: str, token: str) -> bool:
    """https://www.twilio.com/docs/usage/security#validating-requests"""
    data = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature or "")


def twilio_fetch_media(url: str) -> bytes:
    c = twilio_creds()
    auth = base64.b64encode(f"{c['sid']}:{c['token']}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=20) as r:  # follows the redirect to Twilio's media CDN
        return r.read()


def send(channel: dict, to: str, text: str):
    if channel.get("provider") == "twilio":
        c = twilio_creds()
        body = urllib.parse.urlencode({"From": c["from"], "To": to, "Body": text[:1600]}).encode()
        auth = base64.b64encode(f"{c['sid']}:{c['token']}".encode()).decode()
        req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{c['sid']}/Messages.json",
                                     data=body, headers={"Authorization": f"Basic {auth}"})
        urllib.request.urlopen(req, timeout=15).read()
    elif channel.get("provider") == "aws":
        boto3.client("socialmessaging", region_name=config.REGION).send_whatsapp_message(
            originationPhoneNumberId=channel["phoneNumberId"], metaApiVersion="v20.0",
            message=json.dumps({"messaging_product": "whatsapp", "to": to, "type": "text",
                                "text": {"preview_url": True, "body": text[:4000]}}).encode())
    else:
        raise ValueError(f"unknown provider {channel}")


def aws_fetch_media(phone_number_id: str, media_id: str) -> bytes:
    """AWS End User Messaging Social writes inbound media into our bucket, then we read it."""
    prefix = f"wa-media/{media_id}"
    boto3.client("socialmessaging", region_name=config.REGION).get_whatsapp_message_media(
        mediaId=media_id, originationPhoneNumberId=phone_number_id,
        destinationS3File={"bucketName": config.PHOTOS_BUCKET, "key": prefix})
    objs = views.s3().list_objects_v2(Bucket=config.PHOTOS_BUCKET, Prefix=prefix).get("Contents", [])
    return views.s3().get_object(Bucket=config.PHOTOS_BUCKET, Key=objs[0]["Key"])["Body"].read()
