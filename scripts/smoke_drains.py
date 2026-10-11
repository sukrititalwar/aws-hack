"""End-to-end smoke test of DrainReady against a DEPLOYED API (real S3, Lambda, DynamoDB, Bedrock).

  python scripts/smoke_drains.py --api https://<id>.execute-api.ap-south-1.amazonaws.com
  python scripts/smoke_drains.py --api <url> --admin-token <AdminToken>     # also tests assign + clearance

It sends ONE clearly labelled test report (a generated grey image, so a real model should say "not a
drain" and reject it; use --photo with a real drain photo to exercise the full path), then checks
each step and prints PASS / FAIL / NOTE. Exit code 1 if anything failed.

What it proves, in order:
  1. upload-url: the API accepts a report and returns a presigned S3 POST
  2. upload: the photo reaches S3 (no CORS/size/type problem)
  3. analysis: the analyser Lambda ran and the DynamoDB record left "analysing"
     (and which path was used: AI, labelled fallback, or an explicit error with the real cause)
  4. retry: the retry route works on a stuck report
  5. dispatcher (needs --admin-token): assign works, a worker's after-photo is only accepted as
     "cleared" when AI verification succeeds, otherwise it waits for manual confirmation
"""
import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

FAILS = []


def say(tag, msg):
    print(f"[{tag:4}] {msg}")
    if tag == "FAIL":
        FAILS.append(msg)


def call(api, method, path, body=None, token=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["x-admin-token"] = token
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(api + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200].decode(errors="replace")}


def photo_bytes(path):
    if path:
        return open(path, "rb").read()
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 600), (70, 70, 70))
    d = ImageDraw.Draw(im)
    for i in range(8):
        d.rectangle([150 + i * 10, 200 + i * 5, 650 - i * 10, 420 - i * 5], outline=(30, 30, 30))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def s3_post(url, fields, data):
    bnd = "----smoke" + uuid.uuid4().hex
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="photo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                 + data + f"\r\n--{bnd}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode(errors="replace")


def wait(api, rid, until, label, limit=90):
    t0, last = time.time(), None
    while time.time() - t0 < limit:
        time.sleep(2)
        s, d = call(api, "GET", f"/drains/{rid}")
        if s != 200:
            say("FAIL", f"{label}: GET /drains/{rid} -> {s} {d}")
            return None
        st = (d.get("status"), d.get("awaitingReview"), d.get("afterNote"))
        if st != last:
            print(f"        +{time.time() - t0:4.0f}s status={d.get('status')} mode={d.get('analysisMode')} awaitingReview={d.get('awaitingReview')}")
            last = st
        if until(d):
            return d
    say("FAIL", f"{label}: still not done after {limit}s (last status {last[0] if last else '?'})")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--admin-token")
    ap.add_argument("--photo", help="a real photo of a blocked drain (recommended)")
    ap.add_argument("--origin", help="send this Origin header (to check CORS), e.g. your Amplify URL")
    ap.add_argument("--lat", type=float, default=28.6364)
    ap.add_argument("--lon", type=float, default=77.2224)
    a = ap.parse_args()
    api = a.api.rstrip("/")
    dev = "smoke-" + uuid.uuid4().hex[:10]
    img = photo_bytes(a.photo)

    s, up = call(api, "POST", "/drains/upload-url", {"lat": a.lat, "lon": a.lon, "city": "delhi", "deviceId": dev,
                                                    "note": "SMOKE TEST (automated, ignore)"}, origin=a.origin)
    if s != 200:
        return say("FAIL", f"1. upload-url -> {s} {up}") or 1
    say("PASS", f"1. upload-url ok, report {up['reportId']}")

    s, err = s3_post(up["uploadUrl"], up["fields"], img)
    if s not in (200, 201, 204):
        return say("FAIL", f"2. S3 upload -> {s} {err}") or 1
    say("PASS", f"2. photo uploaded to S3 ({len(img) // 1024} KB)")

    d = wait(api, up["reportId"], lambda x: x["status"] != "analysing", "3. analysis")
    if not d:
        s, r = call(api, "POST", f"/drains/{up['reportId']}/retry", {"deviceId": dev})
        say("NOTE", f"retry while stuck -> {s} {r}")
        return 1
    if d["status"] == "error":
        say("FAIL", f"3. analysis ended in an explicit error (visible to the user): {d.get('rejection_reason')} | cause: {d.get('analysisError')}")
        s, r = call(api, "POST", f"/drains/{up['reportId']}/retry", {"deviceId": dev})
        say("PASS" if s == 200 else "FAIL", f"4. retry route -> {s} {r}")
        return 1
    mode = d.get("analysisMode")
    if d["status"] == "rejected" and str(d.get("rejection_reason", "")).startswith("Analysis failed"):
        # An older build recorded crashes as "rejected". A real rejection has a reason about the photo.
        return say("FAIL", f"3. the analyser crashed instead of analysing: {d['rejection_reason']}") or 1
    if d["status"] == "rejected":
        say("NOTE", f"3. analysed and rejected (expected for a non-drain test image): {d.get('rejection_reason')}")
        if not a.photo:
            say("NOTE", "re-run with --photo <real drain photo> to test grouping, assignment and clearance")
        say("PASS", f"3. analysis completed (mode={mode or 'bedrock'})")
        return 1 if FAILS else 0
    if mode == "bedrock" or mode is None:
        say("PASS", f"3. AI analysis worked: {d.get('severity')} ({d.get('confidence')} confidence)")
    else:
        say("NOTE", f"3. AI was unavailable; the labelled fallback was used ({mode}). Cause: {d.get('analysisError')}")
        say("PASS", "3. report was kept and labelled instead of being lost")

    if not a.admin_token:
        say("NOTE", "pass --admin-token to also test assign + after-photo clearance")
        return 1 if FAILS else 0
    gid = d["groupId"]
    s, r = call(api, "POST", f"/drains/{gid}/assign", {"worker": "Smoke Tester"}, token="wrong-code")
    say("PASS" if s == 403 else "FAIL", f"5a. dispatcher route refuses a wrong code -> {s}")
    s, r = call(api, "POST", f"/drains/{gid}/assign", {"worker": "Smoke Tester"}, token=a.admin_token)
    say("PASS" if s == 200 else "FAIL", f"5b. assign -> {s} {r}")
    s, up2 = call(api, "POST", f"/drains/{gid}/after-url", {}, token=a.admin_token)
    if s != 200:
        return say("FAIL", f"5c. after-url -> {s} {up2}") or 1
    s, err = s3_post(up2["uploadUrl"], up2["fields"], img)
    say("PASS" if s in (200, 201, 204) else "FAIL", f"5c. after-photo uploaded -> {s} {err}")
    d2 = wait(api, gid, lambda x: x["status"] == "cleared" or x.get("awaitingReview") or (x.get("afterNote") and x["status"] != "analysing"), "5d. after-photo check")
    if d2:
        if d2["status"] == "cleared":
            say("PASS", f"5d. cleared, verified by {d2.get('clearedBy')}")
        elif d2.get("awaitingReview"):
            say("PASS", "5d. AI verification unavailable: NOT auto-cleared, waiting for a dispatcher (correct)")
        else:
            say("PASS", f"5d. not cleared: {d2.get('afterNote')}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    code = main()
    print("\nRESULT:", "FAILED" if FAILS or code else "OK", f"({len(FAILS)} failure(s))")
    sys.exit(1 if FAILS or code else 0)
