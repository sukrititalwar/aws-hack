import pytest

from common import geo
from common.depth import extract_json, normalise


def test_haversine_known_distance():
    # ~1 degree of latitude
    assert abs(geo.haversine_m(72.85, 19.0, 72.85, 20.0) - 111_195) < 50


def test_geohash_known_value():
    assert geo.geohash_encode(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_cover_bbox_contains_corners():
    bbox = [72.83, 19.08, 72.87, 19.13]
    cells = geo.cover_bbox(bbox, 5)
    for lon, lat in [(72.83, 19.08), (72.87, 19.13), (72.85, 19.10), (72.83, 19.13)]:
        assert geo.geohash_encode(lat, lon, 5) in cells


def test_cover_bbox_too_large():
    with pytest.raises(ValueError):
        geo.cover_bbox([60, 5, 100, 35], 6)


def test_parse_bbox():
    assert geo.parse_bbox("72.8,19.0,72.9,19.1") == [72.8, 19.0, 72.9, 19.1]
    with pytest.raises(ValueError):
        geo.parse_bbox("72.9,19.0,72.8,19.1")
    with pytest.raises(ValueError):
        geo.parse_bbox("1,2,3")


def test_point_segment():
    # Point ~100 m north of an east-west segment
    d = geo.point_segment_m(72.85, 19.0009, 72.84, 19.0, 72.86, 19.0)
    assert 95 < d < 105
    # Beyond the segment end: distance to the endpoint
    d2 = geo.point_segment_m(72.87, 19.0, 72.84, 19.0, 72.86, 19.0)
    assert abs(d2 - geo.haversine_m(72.87, 19.0, 72.86, 19.0)) < 2


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}


def test_normalise_clamps_and_orders():
    n = normalise({"is_flooded_road_photo": True, "depth_cm_low": 40, "depth_cm_high": "20",
                   "confidence": "very", "hazards": ["none", "debris", "aliens"]})
    assert (n["depth_cm_low"], n["depth_cm_high"]) == (20, 40)
    assert n["confidence"] == "low"
    assert n["hazards"] == ["debris"]
