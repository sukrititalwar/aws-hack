import pytest

from common import config, rules


def a(depth, **kw):
    base = {"depth_cm_high": depth, "confidence": "high", "image_quality": "good",
            "flowing_water": False, "hazards": []}
    base.update(kw)
    return base


def v(assessment, vehicle):
    return rules.verdicts_for(assessment)["verdicts"][vehicle]["verdict"]


# Every vehicle, every threshold boundary: just below GO, at GO, just below NO_GO, at NO_GO.
@pytest.mark.parametrize("vehicle", config.VEHICLES)
def test_threshold_boundaries(vehicle):
    t = config.THRESHOLDS[vehicle]
    assert v(a(0), vehicle) == "GO"
    assert v(a(t["go"] - 0.1), vehicle) == "GO"
    assert v(a(t["go"]), vehicle) == "RISKY"
    assert v(a(t["no_go"] - 0.1), vehicle) == "RISKY"
    assert v(a(t["no_go"]), vehicle) == "NO_GO"
    assert v(a(200), vehicle) == "NO_GO"


def test_table_from_spec():
    # Spot checks straight from the README table.
    assert v(a(25), "scooter") == "NO_GO"
    assert v(a(16), "ev_scooter") == "NO_GO"
    assert v(a(16), "scooter") == "RISKY"
    assert v(a(25), "car") == "RISKY"
    assert v(a(25), "suv") == "RISKY"
    assert v(a(24), "suv") == "GO"
    assert v(a(45), "bus") == "RISKY"
    assert v(a(30), "pedestrian") == "NO_GO"


def test_ev_scooter_threshold_boundaries_and_cautious_copy():
    assert v(a(11.9), "ev_scooter") == "GO"
    assert v(a(12), "ev_scooter") == "RISKY"
    assert v(a(12.1), "ev_scooter") == "RISKY"
    assert v(a(15.9), "ev_scooter") == "RISKY"
    assert v(a(16), "ev_scooter") == "NO_GO"
    assert v(a(16.1), "ev_scooter") == "NO_GO"

    below = rules.verdicts_for(a(11.9))["verdicts"]["ev_scooter"]
    warning = rules.verdicts_for(a(12))["verdicts"]["ev_scooter"]
    assert below["label_en"] == "EV Scooter: Below app caution threshold"
    assert below["label_hi"] == "ई-स्कूटर: ऐप की सावधानी सीमा से कम"
    assert below["category"] == "potentially_unsafe"
    assert "not a safety guarantee" in below["why"]
    assert "सुरक्षा की गारंटी नहीं" in below["why_hi"]
    assert "threshold is a precaution" in warning["why"]
    assert "ऐप की सीमा एहतियात है" in warning["why_hi"]


@pytest.mark.parametrize("kw", [
    {"confidence": "low"},
    {"image_quality": "poor"},
    {"flowing_water": True},
    {"hazards": ["strong_current"]},
    {"hazards": ["open_drain_or_manhole_risk"]},
])
def test_single_escalation_bumps_one_level(kw):
    # car: 10 cm is GO, escalated once -> RISKY; 20 cm is RISKY -> NO_GO
    assert v(a(10, **kw), "car") == "RISKY"
    assert v(a(20, **kw), "car") == "NO_GO"
    assert v(a(40, **kw), "car") == "NO_GO"  # cannot go past NO_GO


def test_low_confidence_and_poor_quality_count_once():
    assert v(a(10, confidence="low", image_quality="poor"), "car") == "RISKY"


def test_escalations_stack():
    # flowing + low confidence: GO -> NO_GO
    assert v(a(5, flowing_water=True, confidence="low"), "suv") == "NO_GO"


def test_non_escalating_hazards():
    assert v(a(5, hazards=["debris", "submerged_vehicle", "poor_visibility_night"]), "car") == "GO"


def test_electric_wire_is_no_go_for_everyone():
    r = rules.verdicts_for(a(0, hazards=["electric_pole_or_wire_in_water"]))
    assert r["danger"] is True
    assert all(x["verdict"] == "NO_GO" for x in r["verdicts"].values())
    assert "Electric" in r["verdicts"]["bus"]["why"]


def test_uses_depth_high_worst_case():
    r = rules.verdicts_for({"depth_cm_low": 5, "depth_cm_high": 22, "confidence": "high"})
    assert r["verdicts"]["scooter"]["verdict"] == "NO_GO"


def test_output_shape_and_text():
    r = rules.verdicts_for(a(25))["verdicts"]
    s = r["scooter"]
    assert set(s) == {"vehicle", "verdict", "category", "label_en", "label_hi", "why", "why_hi"}
    assert s["label_en"] == "Scooter / bike: Do not cross"
    assert "exhaust" in s["why"] and "25 cm" in s["why"]
    assert set(r) == set(config.VEHICLES)


def test_worst():
    assert rules.worst(["GO", "RISKY"]) == "RISKY"
    assert rules.worst(["GO", "NO_GO", "RISKY"]) == "NO_GO"
    assert rules.worst([]) == "GO"


def test_categories_and_inspection():
    r = rules.verdicts_for(a(5))
    assert not r["needs_inspection"] and r["verdicts"]["car"]["category"] == "passable"
    assert rules.verdicts_for(a(20))["verdicts"]["car"]["category"] == "potentially_unsafe"
    assert rules.verdicts_for(a(60))["verdicts"]["car"]["category"] == "unsafe"
    # a GO we are not sure about must never be shown as "passable"
    low = rules.verdicts_for(a(5, confidence="low", depth_cm_low=0))
    assert low["needs_inspection"] and "low confidence" in low["inspection_reasons"]
    assert low["verdicts"]["suv"]["verdict"] == "RISKY"          # escalated, as before
    wide = rules.verdicts_for(a(5, depth_cm_low=0, reference_objects=[{"object": "kerb"}]))
    assert not wide["needs_inspection"]
    wide = rules.verdicts_for(a(45, depth_cm_low=5, reference_objects=[{"object": "kerb"}]))
    assert wide["needs_inspection"] and "very wide depth range" in wide["inspection_reasons"]


def test_no_reference_object_escalates_and_requires_inspection():
    r = rules.verdicts_for(a(5, reference_objects=[]))
    assert r["needs_inspection"] and "no reference object visible" in r["inspection_reasons"]
    assert r["verdicts"]["car"]["verdict"] == "RISKY"
    assert r["verdicts"]["car"]["category"] == "potentially_unsafe"
