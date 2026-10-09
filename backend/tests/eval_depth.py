"""Accuracy evaluation on archived photos with known depth (data/eval_set.csv).

Reports MAE (cm, using the midpoint of the predicted range), % within +-10 cm, and the
dangerous error rate: how often the scooter verdict was MORE optimistic than the verdict the
true depth would give (e.g. we said GO, truth was NO_GO).

  cd backend && python -m tests.eval_depth            # uses data/demo_cache, calls Bedrock for new photos
"""
import csv
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from common import config, rules  # noqa: E402
from seed_demo import cached_assessment  # noqa: E402

LEVEL = {l: i for i, l in enumerate(rules.LEVELS)}


def main(city="mumbai"):
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "data", "eval_set.csv"), encoding="utf-8"))
            if r.get("file") and not r["file"].startswith("#")]
    if not rows:
        print("data/eval_set.csv has no rows yet. Add 20-30 photos with known depth.")
        return
    results = []
    for r in rows:
        p = os.path.join(ROOT, "data", "demo_photos", r["file"])
        if not os.path.exists(p):
            p = os.path.join(ROOT, "data", r["file"])
        a = cached_assessment(p, city, "")["assessment"]
        true = float(r["true_depth_cm"])
        mid = (a["depth_cm_low"] + a["depth_cm_high"]) / 2
        pred_v = rules.verdicts_for(a)["verdicts"]
        true_v = rules.verdicts_for({"depth_cm_high": true, "confidence": "high"})["verdicts"]
        row = {"file": r["file"], "true": true, "low": a["depth_cm_low"], "high": a["depth_cm_high"],
               "confidence": a["confidence"], "abs_err": abs(mid - true), "in_range": a["depth_cm_low"] <= true <= a["depth_cm_high"]}
        for v in config.VEHICLES:
            row[f"{v}_pred"] = pred_v[v]["verdict"]
            row[f"{v}_true"] = true_v[v]["verdict"]
            row[f"{v}_optimistic"] = LEVEL[pred_v[v]["verdict"]] < LEVEL[true_v[v]["verdict"]]
        results.append(row)

    n = len(results)
    mae = sum(r["abs_err"] for r in results) / n
    within10 = sum(r["abs_err"] <= 10 for r in results) / n
    in_range = sum(r["in_range"] for r in results) / n
    print(f"\n{'file':32} {'true':>5} {'pred':>9} {'conf':>6} {'scooter pred/true':>20}")
    for r in results:
        flag = "  <-- TOO OPTIMISTIC" if r["scooter_optimistic"] else ""
        print(f"{r['file'][:32]:32} {r['true']:5.0f} {r['low']:4.0f}-{r['high']:<4.0f} {r['confidence']:>6} "
              f"{r['scooter_pred']:>9}/{r['scooter_true']:<9}{flag}")
    print(f"\nPhotos: {n}")
    print(f"Mean absolute error (range midpoint): {mae:.1f} cm")
    print(f"Within +-10 cm: {within10:.0%}   True depth inside predicted range: {in_range:.0%}")
    summary = {"n": n, "mae_cm": round(mae, 1), "within_10cm": round(within10, 3), "in_range": round(in_range, 3)}
    for v in config.VEHICLES:
        opt = sum(r[f"{v}_optimistic"] for r in results)
        go_vs_nogo = sum(r[f"{v}_pred"] == "GO" and r[f"{v}_true"] == "NO_GO" for r in results)
        summary[f"{v}_too_optimistic"] = opt
        summary[f"{v}_go_when_nogo"] = go_vs_nogo
        print(f"  {v:11} too optimistic: {opt}/{n}   said GO when truth NO-GO: {go_vs_nogo}")
    out = os.path.join(ROOT, "data", "eval_results.json")
    json.dump({"summary": summary, "rows": results}, open(out, "w"), indent=1)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
