"""Waterlogging reports from social media and news, through official APIs and feeds only
(no scraping of logged-in sites).

  fetch_*      -> Post dicts {id, url, text, ts, source, author, author_type}
  prefilter    -> keyword + city mention + recency, before spending any model tokens
  extract      -> Bedrock text model returns structured JSON (place, depth words, closure...)
  locate       -> hotspot-name match first, else Amazon Location Places geocode, bbox-checked
  to_report    -> a report item the map, spot merging and routing treat like any other report

Sources that work with no key: Google News RSS, Bluesky (api.bsky.app), Mastodon hashtags.
Optional with credentials (env): Reddit (REDDIT_CLIENT_ID/SECRET), X (X_BEARER_TOKEN, paid),
YouTube Data API (YOUTUBE_API_KEY).
"""
import base64
import hashlib
import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from functools import lru_cache

import boto3

from . import config, depth, geo, rules

log = logging.getLogger()
UA = "CanMyScooterCross/0.1 (hackathon flood-safety app)"

# Words that make a post worth sending to the model (English, Hindi, Malayalam).
KEYWORDS = re.compile(
    r"waterlog|water[- ]?logg|flood|inundat|submerg|knee[- ]?deep|waist[- ]?deep|ankle[- ]?deep|"
    r"underpass|subway closed|water[- ]?filled|jalbharav|jal bharav|जलभराव|जल भराव|पानी भर|बाढ़|"
    r"വെള്ളക്കെട്ട്|വെള്ളം കയറി",
    re.I)

# Official accounts whose closure posts count as ground truth (weight 1.0). Verify handles before use.
OFFICIAL_HANDLES = {
    "delhi": ["dtptraffic"],          # Delhi Traffic Police
    "gurugram": [],                   # add Gurugram Traffic Police handle after checking it
    "kochi": [],                      # add Kochi City Police / district collector handles
    "mumbai": ["MTPHereToHelp"],      # Mumbai Traffic Police
}
SUBREDDITS = {"delhi": ["delhi", "newdelhi"], "gurugram": ["gurgaon"], "kochi": ["Kochi", "Kerala"], "mumbai": ["mumbai"]}
MASTODON_TAGS = {"delhi": ["DelhiRains", "DelhiFloods"], "gurugram": ["GurugramRains", "GurgaonRains"],
                 "kochi": ["KochiRains", "KeralaRains"], "mumbai": ["MumbaiRains"]}

EXTRACT_PROMPT = """You read one public post or news headline from India and decide whether it reports
CURRENT waterlogging / flooding at a specific road, junction, underpass or area in the given city.
Return ONLY JSON, no prose:
{"is_waterlogging_report": bool, "is_current": bool, "place_text": string, "road_or_landmark": string,
 "city": string, "severity_words": string, "depth_cm_low": number|null, "depth_cm_high": number|null,
 "closure": bool, "time_reference": string|null, "confidence": "low"|"medium"|"high"}
Rules:
- is_waterlogging_report=false for forecasts, drain-cleaning plans, politics, old events, other cities.
- is_current=false if the post describes a past day ("last year", "yesterday" with no ongoing issue).
- road_or_landmark: the most specific geocodable name (e.g. "Minto Bridge underpass", "Hero Honda Chowk").
- Map words to depth: ankle ~10, shin ~25, knee ~45, thigh ~65, waist ~90, "vehicles stalled" >=30,
  "bus/car submerged" >=100, "road closed"/"traffic diverted" -> closure=true. Unknown -> null.
- confidence: high only for official accounts or specific depth words with a specific place."""


def _get(url: str, headers: dict | None = None, timeout=12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _post(text, url, ts, source, author="", author_type="public", pid=None):
    return {"id": pid or url, "url": url, "text": re.sub(r"\s+", " ", text).strip()[:1000], "ts": ts,
            "source": source, "author": author, "author_type": author_type}


# ---------------- fetchers ----------------

def fetch_google_news(city: str, hours: int = 24) -> list[dict]:
    label = config.CITIES[city]["label"]
    out = []
    for q in (f"waterlogging {label}", f"{label} flooded road underpass", f"{label} rain traffic"):
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{q} when:{max(1, hours // 24)}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        root = ET.fromstring(_get(url))
        for it in root.findall(".//item"):
            src = it.find("source")
            out.append(_post(it.findtext("title") or "", it.findtext("link") or "",
                             parsedate_to_datetime(it.findtext("pubDate")).timestamp(), "news",
                             author=src.text if src is not None else "", author_type="news"))
    return out


def fetch_bluesky(city: str, hours: int = 24) -> list[dict]:
    label = config.CITIES[city]["label"]
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    out = []
    for q in (f"{label} waterlogging", f"{label} flooded", f"{label} rain underpass"):
        url = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + urllib.parse.urlencode(
            {"q": q, "sort": "latest", "limit": 50, "since": since})
        for p in json.loads(_get(url)).get("posts", []):
            rec = p.get("record", {})
            handle = p.get("author", {}).get("handle", "")
            rkey = p["uri"].rsplit("/", 1)[-1]
            out.append(_post(rec.get("text", ""), f"https://bsky.app/profile/{handle}/post/{rkey}",
                             _iso_ts(rec.get("createdAt")), "bluesky", handle, pid=p["uri"]))
    return out


def fetch_mastodon(city: str, hours: int = 24) -> list[dict]:
    out = []
    for tag in MASTODON_TAGS.get(city, []):
        for s in json.loads(_get(f"https://mastodon.social/api/v1/timelines/tag/{tag}?limit=40")):
            text = html.unescape(re.sub(r"<[^>]+>", " ", s.get("content", "")))
            out.append(_post(text, s.get("url") or s.get("uri"), _iso_ts(s.get("created_at")), "mastodon",
                             s.get("account", {}).get("acct", "")))
    return out


def fetch_reddit(city: str, hours: int = 24) -> list[dict]:
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return []
    tok_req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=b"grant_type=client_credentials",
        headers={"User-Agent": UA, "Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()})
    token = json.loads(urllib.request.urlopen(tok_req, timeout=10).read())["access_token"]
    out = []
    for sub in SUBREDDITS.get(city, []):
        url = f"https://oauth.reddit.com/r/{sub}/search?" + urllib.parse.urlencode(
            {"q": "waterlogging OR flooded OR underpass OR waterlogged", "restrict_sr": 1, "sort": "new", "t": "day", "limit": 50})
        for c in json.loads(_get(url, {"Authorization": f"bearer {token}"}))["data"]["children"]:
            d = c["data"]
            out.append(_post(f"{d.get('title', '')}. {d.get('selftext', '')[:400]}", "https://www.reddit.com" + d["permalink"],
                             float(d["created_utc"]), "reddit", d.get("author", "")))
    return out


def fetch_x(city: str, hours: int = 24) -> list[dict]:
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return []
    label = config.CITIES[city]["label"]
    officials = OFFICIAL_HANDLES.get(city, [])
    q = f"({label} OR {' OR '.join('from:' + h for h in officials) or label}) (waterlogging OR waterlogged OR flooded OR underpass) -is:retweet"
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(
        {"query": q, "max_results": 50, "tweet.fields": "created_at,author_id", "expansions": "author_id", "user.fields": "username"})
    d = json.loads(_get(url, {"Authorization": f"Bearer {token}"}))
    users = {u["id"]: u["username"] for u in d.get("includes", {}).get("users", [])}
    out = []
    for t in d.get("data", []):
        user = users.get(t["author_id"], "")
        kind = "official" if user.lower() in {h.lower() for h in officials} else "public"
        out.append(_post(t["text"], f"https://x.com/{user}/status/{t['id']}", _iso_ts(t["created_at"]), "x", user, kind))
    return out


def fetch_youtube(city: str, hours: int = 24) -> list[dict]:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(
        {"part": "snippet", "q": f"{config.CITIES[city]['label']} waterlogging", "type": "video", "order": "date",
         "publishedAfter": after, "maxResults": 25, "key": key})
    return [_post(f"{i['snippet']['title']}. {i['snippet']['description'][:300]}",
                  f"https://www.youtube.com/watch?v={i['id']['videoId']}", _iso_ts(i["snippet"]["publishedAt"]),
                  "youtube", i["snippet"]["channelTitle"], "news")
            for i in json.loads(_get(url)).get("items", [])]


FETCHERS = [fetch_google_news, fetch_bluesky, fetch_mastodon, fetch_reddit, fetch_x, fetch_youtube]


def fetch_all(city: str, hours: int = 24) -> tuple[list[dict], dict]:
    posts, stats = [], {}
    for f in FETCHERS:
        name = f.__name__.replace("fetch_", "")
        try:
            got = f(city, hours)
            stats[name] = len(got)
            posts.extend(got)
        except Exception as e:  # one broken source must not stop the others
            stats[name] = f"error: {type(e).__name__}"
            log.warning("source %s failed for %s: %s", name, city, e)
    seen, uniq = set(), []
    for p in posts:
        k = p["id"] or hashlib.sha1(p["text"].encode()).hexdigest()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq, stats


def _iso_ts(s: str | None) -> float:
    if not s:
        return 0.0
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---------------- filter / extract / locate ----------------

def prefilter(posts: list[dict], city: str, hotspots: list[dict], max_age_h: float, now: float | None = None) -> list[dict]:
    """Cheap filter before any model call: recent + waterlogging words + mentions this city or
    one of its hotspots."""
    now = now or time.time()
    names = [n.lower() for n in config.CITIES[city]["names"]]
    out = []
    for p in posts:
        t = p["text"].lower()
        if now - p["ts"] > max_age_h * 3600 or not KEYWORDS.search(t):
            continue
        if not (any(n in t for n in names) or match_hotspot(t, hotspots)):
            continue
        out.append(p)
    return out


@lru_cache(maxsize=None)
def _bedrock():
    return boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION)


def extract(post: dict, city: str) -> dict:
    """Bedrock text extraction, temperature 0."""
    msg = f"City: {config.CITIES[city]['label']}. Source: {post['source']} ({post['author_type']}). Post: {post['text']}"
    r = _bedrock().converse(modelId=config.SOCIAL_MODEL_ID, system=[{"text": EXTRACT_PROMPT}],
                            messages=[{"role": "user", "content": [{"text": msg}]}],
                            inferenceConfig={"temperature": 0, "maxTokens": 400})
    text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
    return depth.extract_json(text)


DEPTH_WORDS = [("waist", 80, 100), ("thigh", 55, 70), ("knee", 40, 55), ("shin", 20, 30), ("ankle", 8, 15),
               ("submerged", 60, 120), ("stalled", 30, 50), ("घुटने", 40, 55), ("कमर", 80, 100)]


def heuristic_extract(post: dict, city: str, hotspots: list[dict]) -> dict:
    """No-model fallback for local testing: depth words + hotspot names. Not used in production."""
    t = post["text"].lower()
    lo = hi = None
    for w, a, b in DEPTH_WORDS:
        if w in t:
            lo, hi = a, b
            break
    place = next((h["name"] for h in hotspots if h["name"].lower().split(" (")[0].split(" underpass")[0] in t), "")
    return {"is_waterlogging_report": bool(place), "is_current": True, "road_or_landmark": place, "place_text": place,
            "city": city, "severity_words": "", "depth_cm_low": lo, "depth_cm_high": hi,
            "closure": bool(re.search(r"closed|diverted|बंद", t)), "time_reference": None, "confidence": "low"}


def _name_key(s: str) -> str:
    return re.sub(r"\b(underpass|junction|jn|chowk|road|rd|bridge|the|near|at)\b|[^a-z0-9 ]", " ", s.lower()).split()


def match_hotspot(text: str, hotspots: list[dict]):
    """Hotspot whose distinctive name words all appear in the text (fast, exact ground truth)."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    best = None
    for h in hotspots:
        for name in [h["name"], *(h.get("aliases") or [])]:
            key = [w for w in _name_key(name) if len(w) > 1]
            if key and all(w in words for w in key) and (best is None or len(key) > best[0]):
                best = (len(key), h)
    return best[1] if best else None


@lru_cache(maxsize=None)
def _places():
    return boto3.client("geo-places", region_name=config.REGION)


def geocode(text: str, city: str):
    """Amazon Location Places (v2) geocode, biased to and filtered by the city bbox."""
    c = config.CITIES[city]
    r = _places().geocode(QueryText=f"{text}, {c['label']}", BiasPosition=c["center"], MaxResults=1,
                          Filter={"IncludeCountries": ["IND"], "BoundingBox": c["bbox"]})
    items = r.get("ResultItems", [])
    if not items:
        return None
    lon, lat = items[0]["Position"]
    return lon, lat, items[0].get("Title", text)


def locate(ext: dict, post_text: str, city: str, hotspots: list[dict]):
    """(lon, lat, place, how) or None. Hotspot names win; geocodes snap to a hotspot within 300 m."""
    q = ext.get("road_or_landmark") or ext.get("place_text") or ""
    h = match_hotspot(f"{q} {post_text}", hotspots)
    if h:
        return h["lon"], h["lat"], h["name"], "hotspot"
    if not q:
        return None
    try:
        g = geocode(q, city)
    except Exception as e:
        log.warning("geocode failed for %r: %s", q, e)
        return None
    if not g:
        return None
    lon, lat, title = g
    min_lon, min_lat, max_lon, max_lat = config.CITIES[city]["bbox"]
    if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
        return None
    for h in hotspots:
        if geo.haversine_m(lon, lat, h["lon"], h["lat"]) <= 300:
            return h["lon"], h["lat"], h["name"], "geocode+hotspot"
    return lon, lat, q or title, "geocode"


def report_id(post: dict) -> str:
    return "soc-" + hashlib.sha1(post["id"].encode()).hexdigest()[:14]


def to_report(post: dict, ext: dict, loc, city: str, mode: str = "live", ts: float | None = None) -> dict:
    """Report item. No depth words -> 'waterlogging reported' ~10-25 cm, low confidence (the rules
    engine escalates, so small vehicles get RISKY or worse)."""
    lon, lat, place, how = loc
    closure = bool(ext.get("closure"))
    lo, hi = ext.get("depth_cm_low"), ext.get("depth_cm_high")
    if hi is None:
        lo, hi = (40, 60) if closure else (10, 25)
    lo = lo if lo is not None else max(0, hi - 15)
    conf = ext.get("confidence") if ext.get("confidence") in ("low", "medium", "high") else "low"
    official = post["author_type"] == "official"
    a = {"depth_cm_high": hi, "confidence": conf, "image_quality": "ok", "flowing_water": False, "hazards": []}
    r = rules.verdicts_for(a)
    verdicts = r["verdicts"]
    if closure and official:
        for v in verdicts.values():
            v["verdict"] = "NO_GO"
            v["why"] = "Officially closed or diverted because of waterlogging."
            v["why_hi"] = "जलभराव के कारण आधिकारिक तौर पर बंद/डायवर्ट।"
    label = ("@" + post["author"]) if official else (post["author"] if post["author_type"] == "news" else "Public post")
    t = ts or post["ts"]
    snippet = post["text"][:180] + ("…" if len(post["text"]) > 180 else "")
    return {
        "reportId": report_id(post), "city": city, "mode": mode,
        "cell": f"{mode}#{city}#{geo.geohash_encode(lat, lon, config.GEOHASH_PRECISION)}",
        "cityMode": f"{mode}#{city}", "lat": lat, "lon": lon, "place": place,
        "createdAt": int(time.time()), "ts": int(t), "status": "live",
        "source_type": "official" if official else "social", "source_platform": post["source"],
        "source_url": post["url"], "source_label": label, "closure": closure, "locatedBy": how,
        "depth_low": lo, "depth_high": hi, "confidence": conf, "image_quality": "ok",
        "flowing_water": False, "hazards": [], "verdicts": verdicts, "danger": False,
        "reasoning": f"{label} ({post['source']}): “{snippet}”" + (f" Depth from words: {ext.get('severity_words')}." if ext.get("severity_words") else ""),
        "reasoning_hi": f"{label} ({post['source']}) की पोस्ट से। विवरण के लिए स्रोत देखें।",
        "votes": {"still": 0, "cleared": 0, "wrong": 0}, "extraction": ext,
        "expiresAt": int(t) + config.EXPIRE_AFTER_H * 3600 if mode == "live" else None,
    }
