"""WhatsApp flow end to end on moto: Twilio webhook -> session -> report -> analyze -> reply."""
import json
import urllib.parse
from io import BytesIO

import boto3
import pytest

from tests.test_handlers import FLOOD, aws  # noqa: F401  (fixture)

TOKEN = "test-auth-token"
URL = "https://abc.execute-api.ap-south-1.amazonaws.com/whatsapp/twilio"


def _jpeg():
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 160)).save(b, "JPEG")
    return b.getvalue()


def twilio_event(params: dict):
    from common import whatsapp as wa
    import base64, hashlib, hmac
    data = URL + "".join(k + params[k] for k in sorted(params))
    sig = base64.b64encode(hmac.new(TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()
    assert wa.twilio_signature_ok(URL, params, sig, TOKEN)
    return {"routeKey": "POST /whatsapp/twilio", "rawPath": "/whatsapp/twilio",
            "requestContext": {"domainName": "abc.execute-api.ap-south-1.amazonaws.com", "http": {"sourceIp": "1.1.1.1"}},
            "headers": {"x-twilio-signature": sig}, "body": urllib.parse.urlencode(params)}


@pytest.fixture
def wa_env(aws, monkeypatch):  # noqa: F811
    from common import whatsapp as wa
    monkeypatch.setattr(wa, "twilio_creds", lambda: {"sid": "AC1", "token": TOKEN, "from": "whatsapp:+14155238886"})
    monkeypatch.setattr(wa, "twilio_fetch_media", lambda url: _jpeg())
    sent = []
    monkeypatch.setattr(wa, "send", lambda ch, to, text: sent.append((ch["provider"], to, text)))
    boto3.resource("dynamodb").Table("Hotspots").put_item(Item={
        "city": "delhi", "hotspotId": "minto-bridge", "name": "Minto Bridge underpass", "aliases": ["Minto Bridge"],
        "lat": __import__("decimal").Decimal("28.63345"), "lon": __import__("decimal").Decimal("77.22667"),
        "kind": "underpass", "risk": "normal"})
    return sent


def test_signature_rejects_tampering():
    from common import whatsapp as wa
    assert not wa.twilio_signature_ok(URL, {"Body": "hi"}, "bad", TOKEN)


def test_photo_then_location_gives_verdict(wa_env, monkeypatch):
    from common import depth, db
    from functions.analyze import app as analyze
    from functions.whatsapp import app as wh
    me = "whatsapp:+919800000001"

    r = wh.handler(twilio_event({"From": me, "Body": "car"}), None)
    assert r["statusCode"] == 200 and "car" in r["body"]

    r = wh.handler(twilio_event({"From": me, "Body": "", "NumMedia": "1", "MediaUrl0": "https://api.twilio.com/m/1",
                                 "MediaContentType0": "image/jpeg"}), None)
    assert "location" in r["body"].lower()

    r = wh.handler(twilio_event({"From": me, "Latitude": "28.63345", "Longitude": "77.22667"}), None)
    assert "Checking" in r["body"]

    # the copy into uploads/ is what triggers analyze in AWS; run it directly here
    keys = [o["Key"] for o in boto3.client("s3").list_objects_v2(Bucket="test-photos", Prefix="uploads/")["Contents"]]
    assert len(keys) == 1
    rid = keys[0].split("/")[1].split(".")[0]
    rep = db.get_report(rid)
    assert rep["city"] == "delhi" and rep["replyTo"]["to"] == me and rep["source_platform"] == "whatsapp"

    monkeypatch.setattr(analyze, "_unsafe", lambda b, k: None)
    monkeypatch.setattr(depth, "estimate_depth", lambda img, c, p: (depth.normalise(FLOOD), {}))
    analyze.handler({"Records": [{"s3": {"bucket": {"name": "test-photos"}, "object": {"key": keys[0]}}}]}, None)

    provider, to, text = wa_env[-1]
    assert provider == "twilio" and to == me
    assert "20–30 cm" in text and "🚗" in text and "Car" in text
    assert "replyTo" not in db.get_report(rid)  # phone number removed after replying


def test_location_only_lists_nearby_and_place_name_status(wa_env):
    from functions.whatsapp import app as wh
    me = "whatsapp:+919800000002"
    r = wh.handler(twilio_event({"From": me, "Latitude": "28.6334", "Longitude": "77.2266"}), None)
    assert "No flooded spots" in r["body"]
    r = wh.handler(twilio_event({"From": me, "Body": "Is Minto Bridge flooded?"}), None)
    assert "Minto Bridge underpass" in r["body"] and "no flooding reported" in r["body"]
    r = wh.handler(twilio_event({"From": me, "Body": "hi"}), None)
    assert "Send a *photo*" in r["body"]


def test_aws_end_user_messaging_text(wa_env):
    from functions.whatsapp import app as wh
    entry = {"id": "1", "changes": [{"field": "messages", "value": {"messages": [
        {"from": "919800000003", "id": "wamid.1", "type": "text", "text": {"body": "hello"}}]}}]}
    msg = {"context": {"MetaPhoneNumberIds": [{"arn": "arn:aws:social-messaging:ap-south-1:1:phone-number-id/abc", "metaPhoneNumberId": "abc"}]},
           "whatsAppWebhookEntry": json.dumps(entry)}
    wh.handler({"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(msg)}}]}, None)
    provider, to, text = wa_env[-1]
    assert provider == "aws" and to == "919800000003" and "photo" in text
