from common import config, spots

NOW = 1_700_000_000


def rep(rid, lat=19.1, lon=72.85, mins_ago=10, depth=25, conf="high", **kw):
    r = {"reportId": rid, "lat": lat, "lon": lon, "ts": NOW - mins_ago * 60,
         "depth_low": depth - 10, "depth_high": depth, "confidence": conf,
         "image_quality": "good", "flowing_water": False, "hazards": [], "votes": {}}
    r.update(kw)
    return r


def test_nearby_reports_merge():
    # ~30 m apart, 20 min apart -> one spot
    s = spots.build_spots([rep("a", mins_ago=30), rep("b", lat=19.10027, mins_ago=10)], NOW)
    assert len(s) == 1
    assert s[0]["reportCount"] == 2
    assert s[0]["spotId"] == "a"


def test_far_reports_do_not_merge():
    s = spots.build_spots([rep("a"), rep("b", lat=19.102)], NOW)  # ~220 m
    assert len(s) == 2


def test_time_window_splits_spots():
    # same place but 120 min apart -> separate spots
    s = spots.build_spots([rep("a", mins_ago=150), rep("b", mins_ago=30)], NOW)
    assert len(s) == 2


def test_confidence_weighted_median():
    # Two low-confidence 10 cm reports (0.8) vs one high 40 cm (1.0) -> 40 wins the median
    rs = [rep("a", depth=10, conf="low"), rep("b", depth=10, conf="low", mins_ago=9),
          rep("c", depth=40, conf="high", mins_ago=8)]
    s = spots.build_spots(rs, NOW)[0]
    assert s["depth_high"] == 40
    assert s["verdicts"]["scooter"] == "NO_GO"


def test_wrong_votes_reduce_weight():
    rs = [rep("a", depth=10, conf="medium"), rep("b", depth=40, conf="high", mins_ago=9,
                                                 votes={"wrong": 3})]
    assert spots.build_spots(rs, NOW)[0]["depth_high"] == 10


def test_expiry_and_fade():
    assert spots.build_spots([rep("a", mins_ago=7 * 60)], NOW) == []
    s = spots.build_spots([rep("a", mins_ago=4 * 60)], NOW)[0]
    assert s["faded"] is True and s["ageMin"] == 240


def test_still_flooded_vote_keeps_alive():
    r = rep("a", mins_ago=7 * 60, lastStillTs=NOW - 600)
    s = spots.build_spots([r], NOW)
    assert len(s) == 1 and s[0]["ageMin"] == 10 and not s[0]["faded"]


def test_cleared_votes():
    r = rep("a", mins_ago=45, votes={"cleared": 3})
    assert spots.build_spots([r], NOW) == []
    # recent photo: not cleared yet even with 3 clears
    r2 = rep("b", mins_ago=10, votes={"cleared": 3})
    assert len(spots.build_spots([r2], NOW)) == 1
    assert spots.build_spots([r], NOW, include_cleared=True)[0]["status"] == "cleared"


def test_future_reports_ignored_for_replay():
    assert spots.build_spots([rep("a", mins_ago=-10)], NOW) == []


def test_official_closure_is_no_go_for_all():
    r = rep("a", depth=5, source_type="official", closure=True)
    s = spots.build_spots([r], NOW)[0]
    assert set(s["verdicts"].values()) == {"NO_GO"}


def test_social_reports_weigh_less():
    assert spots.report_weight(rep("a", source_type="social")) == config.CONFIDENCE_WEIGHT["high"] * 0.5
