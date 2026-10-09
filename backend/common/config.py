"""Central configuration. Every tunable number lives here so it can be documented and changed in one place."""
import os

# ---- AWS resources (injected by SAM template as env vars) ----
REGION = os.environ.get("AWS_REGION", "ap-south-1")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", REGION)
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")
PHOTOS_BUCKET = os.environ.get("PHOTOS_BUCKET", "")
DATA_BUCKET = os.environ.get("DATA_BUCKET", PHOTOS_BUCKET)
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "Reports")
HOTSPOTS_TABLE = os.environ.get("HOTSPOTS_TABLE", "Hotspots")
SUBSCRIPTIONS_TABLE = os.environ.get("SUBSCRIPTIONS_TABLE", "Subscriptions")
RATELIMIT_TABLE = os.environ.get("RATELIMIT_TABLE", "RateLimits")
ALERTS_TOPIC_ARN = os.environ.get("ALERTS_TOPIC_ARN", "")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
WA_SESSIONS_TABLE = os.environ.get("WA_SESSIONS_TABLE", "WhatsAppSessions")
SOCIAL_MODEL_ID = os.environ.get("SOCIAL_MODEL_ID", BEDROCK_MODEL_ID)  # a cheaper text model is fine
APP_URL = os.environ.get("APP_URL", "")

# ---- Vehicles ----
VEHICLES = ["pedestrian", "bicycle", "scooter", "auto", "car", "suv", "bus", "ambulance"]

# Verdict thresholds in cm, applied to depth_cm_high (worst case).
#   depth <  go           -> GO
#   go <= depth < no_go   -> RISKY
#   depth >= no_go        -> NO_GO
# Starting assumptions from the flood-safety rule of thumb (~15 cm moving water knocks a
# person down, ~30 cm floats many cars, ~60 cm sweeps most vehicles) plus low two-wheeler
# exhausts / air intakes. Tune with tests/eval_depth.py.
THRESHOLDS = {
    "pedestrian": {"go": 10, "no_go": 30},
    "bicycle":    {"go": 10, "no_go": 20},
    "scooter":    {"go": 10, "no_go": 20},
    "auto":       {"go": 15, "no_go": 25},
    "car":        {"go": 15, "no_go": 30},
    "suv":        {"go": 25, "no_go": 45},
    "bus":        {"go": 40, "no_go": 60},
    "ambulance":  {"go": 20, "no_go": 35},
}

# Hazards that escalate every verdict one level.
ESCALATING_HAZARDS = {"strong_current", "open_drain_or_manhole_risk", "electric_pole_or_wire_in_water"}
# Hazard that forces NO_GO for everyone.
FATAL_HAZARD = "electric_pole_or_wire_in_water"

# ---- Spot merging ----
SPOT_RADIUS_M = 75
SPOT_WINDOW_MIN = 90
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
SOURCE_WEIGHT = {"photo": 1.0, "social": 0.5, "official": 1.0}
WRONG_VOTE_PENALTY = 0.25         # each "wrong" vote multiplies weight by (1 - this), floor below
MIN_REPORT_WEIGHT = 0.1
CLEARED_VOTES_NEEDED = 3
CLEARED_QUIET_MIN = 30            # no new photo for this long + enough clears -> cleared
FADE_AFTER_H = 3
EXPIRE_AFTER_H = 6
STALE_PHOTO_H = 6                 # EXIF time older than this (live mode) -> stale

# ---- Routing ----
EDGE_BLOCK_RADIUS_M = 40
RISKY_PENALTY = 5.0
SPEED_KMH = {
    "pedestrian": 4.5, "bicycle": 12, "scooter": 20, "auto": 18,
    "car": 20, "suv": 20, "bus": 15, "ambulance": 25,
}

# ---- Abuse controls ----
REPORTS_PER_DEVICE_PER_HOUR = 10

# ---- Geo ----
GEOHASH_PRECISION = 5   # ~4.9 km x 4.9 km cells: a city viewport is a handful of queries

# Demo cities: centre + bbox (minLon, minLat, maxLon, maxLat)
# names: words used to find social posts about the city (and to reject posts about elsewhere)
CITIES = {
    "delhi": {"center": [77.2300, 28.6100], "bbox": [76.84, 28.40, 77.35, 28.88],
              "label": "Delhi", "names": ["delhi", "new delhi", "दिल्ली"]},
    "gurugram": {"center": [77.0500, 28.4600], "bbox": [76.93, 28.37, 77.15, 28.54],
                 "label": "Gurugram", "names": ["gurugram", "gurgaon", "गुरुग्राम", "गुड़गांव"]},
    "kochi": {"center": [76.2900, 9.9800], "bbox": [76.20, 9.85, 76.40, 10.10],
              "label": "Kochi", "names": ["kochi", "ernakulam", "cochin", "കൊച്ചി", "എറണാകുളം"]},
    "mumbai": {"center": [72.8475, 19.1080], "bbox": [72.80, 18.90, 72.99, 19.30],
               "label": "Mumbai", "names": ["mumbai", "मुंबई"]},
}

# ---- Rain -> predicted flooding at chronic hotspots (used until a real report arrives) ----
RAIN_NOW_MM_H = 7.5          # IMD "heavy" hourly intensity is ~7.5 mm/h and above
RAIN_PAST3H_FLOOD_MM = 20    # this much in the last 3 h: hotspots are likely flooded now
RAIN_NEXT3H_WARN_MM = 15     # this much forecast in the next 3 h: warn
PREDICTED_SUPPRESS_M = 150   # a real report within this distance replaces the prediction
