"""WhatsApp inbound.

  POST /whatsapp/twilio  : Twilio webhook (form-encoded), signature-checked, replies with TwiML.
  SNS event              : AWS End User Messaging Social inbound (Meta webhook entry inside).
"""
import base64
import json
import logging
import urllib.parse
from xml.sax.saxutils import escape

from common import whatsapp as wa

log = logging.getLogger()
log.setLevel(logging.INFO)


def _twiml(text: str | None) -> dict:
    body = f"<Response><Message>{escape(text)}</Message></Response>" if text else "<Response/>"
    return {"statusCode": 200, "headers": {"Content-Type": "text/xml"}, "body": body}


def twilio(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    params = {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
    ctx = event.get("requestContext", {})
    url = f"https://{ctx.get('domainName')}{event.get('rawPath')}"
    sig = (event.get("headers") or {}).get("x-twilio-signature", "")
    if not wa.twilio_signature_ok(url, params, sig, wa.twilio_creds()["token"] or ""):
        log.warning("bad Twilio signature for %s", url)
        return {"statusCode": 403, "body": "forbidden"}

    phone = params.get("From", "")
    if params.get("Latitude") and params.get("Longitude"):
        msg = {"type": "location", "lat": params["Latitude"], "lon": params["Longitude"]}
    elif int(params.get("NumMedia") or 0) > 0 and params.get("MediaContentType0", "").startswith("image/"):
        url0 = params["MediaUrl0"]
        msg = {"type": "image", "text": params.get("Body"), "fetch_media": lambda: wa.twilio_fetch_media(url0)}
    else:
        msg = {"type": "text", "text": params.get("Body", "")}
    try:
        reply = wa.handle(phone, msg, {"provider": "twilio"})
    except Exception:
        log.exception("whatsapp handling failed")
        reply = "Sorry, something went wrong. Please try again."
    return _twiml(reply)


def aws_social(record):
    """One SNS record from AWS End User Messaging Social."""
    m = json.loads(record["Sns"]["Message"])
    phone_ids = m.get("context", {}).get("MetaPhoneNumberIds", [])
    origin = phone_ids[0]["arn"] if phone_ids else None
    entry = json.loads(m["whatsAppWebhookEntry"])
    channel = {"provider": "aws", "phoneNumberId": origin}
    for change in entry.get("changes", []):
        for message in change.get("value", {}).get("messages", []):
            phone = message["from"]
            t = message.get("type")
            if t == "location":
                msg = {"type": "location", "lat": message["location"]["latitude"], "lon": message["location"]["longitude"]}
            elif t == "image":
                mid = message["image"]["id"]
                msg = {"type": "image", "text": message["image"].get("caption"),
                       "fetch_media": lambda mid=mid: wa.aws_fetch_media(origin, mid)}
            else:
                msg = {"type": "text", "text": (message.get("text") or {}).get("body", "")}
            try:
                reply = wa.handle(phone, msg, channel)
            except Exception:
                log.exception("whatsapp handling failed")
                reply = "Sorry, something went wrong. Please try again."
            if reply:
                wa.send(channel, phone, reply)


def handler(event, _ctx):
    if "Records" in event:
        for rec in event["Records"]:
            if rec.get("EventSource") == "aws:sns" or "Sns" in rec:
                aws_social(rec)
        return {"ok": True}
    return twilio(event)
