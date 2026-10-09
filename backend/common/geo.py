"""Small dependency-free geo helpers: distances, geohash, bbox cover, point-to-segment."""
import math

EARTH_R = 6371000.0
_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def geohash_encode(lat: float, lon: float, precision: int) -> str:
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, bit_count, even = [], 0, 0, True
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            bits = (bits << 1) | 1
            rng[0] = mid
        else:
            bits <<= 1
            rng[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(_B32[bits])
            bits, bit_count = 0, 0
    return "".join(out)


def geohash_cell_size(precision: int) -> tuple[float, float]:
    """(lon_deg, lat_deg) size of a geohash cell."""
    lon_bits = math.ceil(precision * 5 / 2)
    lat_bits = math.floor(precision * 5 / 2)
    return 360.0 / (2 ** lon_bits), 180.0 / (2 ** lat_bits)


def cover_bbox(bbox, precision: int, max_cells: int = 200) -> list[str]:
    """Geohash cells covering bbox (minLon, minLat, maxLon, maxLat)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    dlon, dlat = geohash_cell_size(precision)
    cells = set()
    lat = min_lat
    while lat <= max_lat + dlat:
        lon = min_lon
        while lon <= max_lon + dlon:
            cells.add(geohash_encode(min(lat, max_lat), min(lon, max_lon), precision))
            if len(cells) > max_cells:
                raise ValueError("bbox too large")
            lon += dlon
        lat += dlat
    return sorted(cells)


def valid_lonlat(lon, lat) -> bool:
    try:
        return -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90
    except (TypeError, ValueError):
        return False


def parse_bbox(s: str):
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be minLon,minLat,maxLon,maxLat")
    min_lon, min_lat, max_lon, max_lat = parts
    if not (valid_lonlat(min_lon, min_lat) and valid_lonlat(max_lon, max_lat)):
        raise ValueError("bbox out of range")
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox min > max")
    return parts


def point_segment_m(px, py, ax, ay, bx, by) -> float:
    """Distance in metres from point P to segment AB, all (lon, lat). Local equirectangular
    projection: accurate to well under 1 % at city scale."""
    k = math.cos(math.radians(py))
    to_m = math.pi / 180 * EARTH_R
    ax_, ay_ = (ax - px) * k * to_m, (ay - py) * to_m
    bx_, by_ = (bx - px) * k * to_m, (by - py) * to_m
    dx, dy = bx_ - ax_, by_ - ay_
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax_ * dx + ay_ * dy) / seg2))
    cx, cy = ax_ + t * dx, ay_ + t * dy
    return math.hypot(cx, cy)


def point_polyline_m(px, py, coords) -> float:
    if len(coords) == 1:
        return haversine_m(px, py, coords[0][0], coords[0][1])
    return min(point_segment_m(px, py, *coords[i], *coords[i + 1]) for i in range(len(coords) - 1))
