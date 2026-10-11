"""DrainReady: get blocked drains cleared BEFORE the next storm.

Pure logic (no AWS), unit-tested in tests/test_drains.py:
  * group duplicate reports of the same blockage (same place, still open)
  * priority = blockage severity x number of independent reports x forecast rain x known
    flood hotspot nearby
  * metrics: cleared before rain, median time to clearance, repeat blockages

A drain report is a dict:
  reportId, city, lat, lon, ts, status (analysing|open|assigned|cleared|rejected),
  severity (partial|blocked), blockage_type, groupId, assignedTo, assignedAt, clearedAt,
  rainNext24h (mm forecast at the time of the report), afterSeverity
"""
import math
import statistics

from . import geo

GROUP_RADIUS_M = 30          # same drain: reports this close and still open are one blockage
REPEAT_RADIUS_M = 50         # a new blockage this close to a cleared one counts as a repeat
REPEAT_WINDOW_DAYS = 30
RAIN_URGENT_MM = 15          # forecast rain in the next 24 h that makes a blockage urgent
HOTSPOT_RADIUS_M = 150

SEVERITY_WEIGHT = {"partial": 1.5, "blocked": 3.0}
OPEN = ("open", "assigned")


def find_group(new: dict, existing: list[dict]) -> str | None:
    """groupId of the nearest still-open report within GROUP_RADIUS_M, else None."""
    best = None
    for r in existing:
        if r.get("status") not in OPEN or r["reportId"] == new["reportId"]:
            continue
        d = geo.haversine_m(new["lon"], new["lat"], r["lon"], r["lat"])
        if d <= GROUP_RADIUS_M and (best is None or d < best[0]):
            best = (d, r.get("groupId") or r["reportId"])
    return best[1] if best else None


def priority(members: list[dict], hotspots: list[dict] | None = None) -> dict:
    """Score one group of reports. Higher = clear it sooner. Reasons are shown to the dispatcher."""
    live = [m for m in members if m.get("severity") in SEVERITY_WEIGHT]
    sev = max((SEVERITY_WEIGHT[m["severity"]] for m in live), default=1.0)
    n = len({m.get("deviceHash") or m["reportId"] for m in live}) or 1
    rain = max((float(m.get("rainNext24h") or 0) for m in members), default=0.0)
    rain_factor = 1 + min(rain / 20, 2)                    # 1x dry .. 3x at >= 40 mm
    dup_factor = 1 + 0.5 * math.log1p(n - 1)              # 1x for one report, ~1.35x for 2, 1.7x for 4
    lat = sum(m["lat"] for m in members) / len(members)
    lon = sum(m["lon"] for m in members) / len(members)
    near = [h for h in (hotspots or [])
            if geo.haversine_m(lon, lat, h["lon"], h["lat"]) <= HOTSPOT_RADIUS_M]
    hotspot_factor = 1.5 if near else 1.0
    score = sev * dup_factor * rain_factor * hotspot_factor
    reasons = [f"{'fully blocked' if sev >= 3 else 'partly blocked'}"]
    if n > 1:
        reasons.append(f"{n} independent reports")
    if rain >= RAIN_URGENT_MM:
        reasons.append(f"{rain:.0f} mm rain forecast in 24 h")
    if near:
        reasons.append(f"near known flood spot: {near[0]['name']}")
    return {"score": round(score, 2), "reasons": reasons, "reportCount": n,
            "urgent": rain >= RAIN_URGENT_MM, "rainNext24h": round(rain, 1),
            "nearHotspot": near[0]["name"] if near else None}


SKIP = ("analysing", "rejected", "error")   # not (yet) a real blockage


def _status(ms: list[dict]) -> str:
    st = {m["status"] for m in ms}
    if st == {"cleared"}:
        return "cleared"
    if "assigned" in st:
        return "assigned"
    if "open" in st:
        return "open"
    return "cleared" if "cleared" in st else ms[0]["status"]


def cluster(reports: list[dict]) -> list[list[dict]]:
    """Reports -> blockage groups (each sorted oldest first).

    Starts from the stored groupId, then merges OPEN groups that are within GROUP_RADIUS_M of each
    other. The analyser groups at write time, but a DynamoDB index is eventually consistent, so two
    near-simultaneous reports of one drain can both start their own group; merging on read makes
    the list correct regardless. Cleared groups are never merged (a new report near a cleared drain
    is a repeat blockage)."""
    by_gid: dict[str, list[dict]] = {}
    for r in reports:
        if r.get("status") in SKIP:
            continue
        by_gid.setdefault(r.get("groupId") or r["reportId"], []).append(r)
    groups = [sorted(ms, key=lambda m: m["ts"]) for ms in by_gid.values()]
    idx = [i for i, g in enumerate(groups) if _status(g) in OPEN]
    parent = {i: i for i in idx}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def close(a, b):
        return any(geo.haversine_m(x["lon"], x["lat"], y["lon"], y["lat"]) <= GROUP_RADIUS_M for x in a for y in b)

    for n, i in enumerate(idx):
        for j in idx[n + 1:]:
            if find(i) != find(j) and close(groups[i], groups[j]):
                parent[find(j)] = find(i)
    merged: dict[int, list[dict]] = {}
    for i, g in enumerate(groups):
        merged.setdefault(find(i) if i in parent else i, []).extend(g)
    return [sorted(ms, key=lambda m: m["ts"]) for ms in merged.values()]


def build_groups(reports: list[dict], hotspots: list[dict] | None = None) -> list[dict]:
    """One row per blockage, ranked by priority (open/assigned first)."""
    rows = []
    for members in cluster(reports):
        head = members[0]
        pr = priority(members, hotspots)
        status = _status(members)
        assigned = [m for m in members if m.get("assignedTo")]
        cleared = [m for m in members if m.get("clearedAt")]
        rows.append({
            "groupId": head.get("groupId") or head["reportId"], "city": head["city"], "status": status,
            "lat": round(sum(m["lat"] for m in members) / len(members), 6),
            "lon": round(sum(m["lon"] for m in members) / len(members), 6),
            "severity": max((m["severity"] for m in members if m.get("severity")),
                            key=lambda s: SEVERITY_WEIGHT.get(s, 0), default=None),
            "blockage_type": head.get("blockage_type"), "note": head.get("note"),
            "firstReported": head["ts"],
            "assignedTo": max(assigned, key=lambda m: m.get("assignedAt") or 0)["assignedTo"] if assigned else None,
            "assignedAt": max((m.get("assignedAt") or 0 for m in assigned), default=None),
            "clearedAt": max((m["clearedAt"] for m in cleared), default=None),
            "analysisMode": head.get("analysisMode", "bedrock"),
            "needsReview": any(m.get("needsReview") for m in members) and status != "cleared",
            "awaitingReview": any(m.get("awaitingReview") for m in members) and status != "cleared",
            "afterNote": next((m["afterNote"] for m in reversed(members) if m.get("afterNote")), None),
            "clearedBy": ("ai" if any(m.get("clearanceVerified") for m in members) else "manual") if status == "cleared" else None,
            "reportIds": [m["reportId"] for m in members], **pr,
        })
    rows.sort(key=lambda g: (g["status"] == "cleared", -g["score"], g["firstReported"]))
    return rows


def metrics(reports: list[dict], now: float) -> dict:
    """The three impact numbers (plus how clearances were verified), from merged groups."""
    groups = cluster(reports)
    heads = []
    for ms in groups:
        h = dict(ms[0])
        h["status"] = _status(ms)
        h["clearedAt"] = max((m["clearedAt"] for m in ms if m.get("clearedAt")), default=None)
        h["ai_verified"] = any(m.get("clearanceVerified") for m in ms)
        h["rainNext24h"] = max((float(m.get("rainNext24h") or 0) for m in ms), default=0.0)
        heads.append(h)
    cleared = [h for h in heads if h["status"] == "cleared" and h.get("clearedAt")]
    hours = [(h["clearedAt"] - h["ts"]) / 3600 for h in cleared]
    # "Before rainfall": cleared while rain was forecast at report time, and within 24 h of the
    # report (i.e. inside the forecast window). This is based on the forecast we stored, not on
    # a rain gauge, and the dashboard says so.
    rain_cases = [h for h in cleared if h["rainNext24h"] >= RAIN_URGENT_MM]
    before_rain = [h for h in rain_cases if h["clearedAt"] - h["ts"] <= 24 * 3600]
    # Repeat blockages: a newer blockage within 50 m of an earlier cleared one inside 30 days.
    repeats = 0
    for h in heads:
        for c in cleared:
            if c is h or h["ts"] < c["clearedAt"]:
                continue
            if (h["ts"] - c["clearedAt"] <= REPEAT_WINDOW_DAYS * 86400 and
                    geo.haversine_m(h["lon"], h["lat"], c["lon"], c["lat"]) <= REPEAT_RADIUS_M):
                repeats += 1
                break
    open_now = [h for h in heads if h["status"] in OPEN]
    return {
        "reported": len(heads), "open": len(open_now),
        "assigned": sum(1 for h in open_now if h["status"] == "assigned"),
        "cleared": len(cleared),
        "cleared_ai_verified": sum(1 for h in cleared if h["ai_verified"]),
        "cleared_manual": sum(1 for h in cleared if not h["ai_verified"]),
        "median_hours_to_clear": round(statistics.median(hours), 1) if hours else None,
        "rain_forecast_cases": len(rain_cases), "cleared_before_rain": len(before_rain),
        "repeat_blockages": repeats,
        "basis": "Rain = forecast stored when the blockage was reported (Open-Meteo), not a gauge reading.",
    }
