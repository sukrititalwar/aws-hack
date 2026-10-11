"""Open-Meteo hourly forecast adapter for route-level predictions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import urllib.parse
import urllib.request


class WeatherProviderError(RuntimeError):
    """A forecast could not be fetched or normalized."""


FIELDS = ("precipitation", "precipitation_probability", "rain", "weather_code")
URL = "https://api.open-meteo.com/v1/forecast"
MAX_LOCATIONS_PER_REQUEST = 50


def _timestamp(value):
    if not isinstance(value, str):
        raise WeatherProviderError("Open-Meteo returned an invalid hourly timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WeatherProviderError("Open-Meteo returned an invalid hourly timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _number(value, field):
    if value is None:
        return None
    if isinstance(value, bool):
        raise WeatherProviderError(f"Open-Meteo returned an invalid {field} value")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherProviderError(f"Open-Meteo returned an invalid {field} value") from exc
    if not math.isfinite(result):
        raise WeatherProviderError(f"Open-Meteo returned a non-finite {field} value")
    if field in ("precipitation", "rain") and result < 0:
        raise WeatherProviderError(f"Open-Meteo returned a negative {field} value")
    if field == "precipitation_probability" and not 0 <= result <= 100:
        raise WeatherProviderError("Open-Meteo returned an invalid precipitation probability")
    if field == "weather_code":
        if not result.is_integer() or not 0 <= result <= 99:
            raise WeatherProviderError("Open-Meteo returned an invalid weather code")
        return int(result)
    return result


def normalize_forecast(payload):
    """Normalize one Open-Meteo location into UTC hourly records and metric units."""
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise WeatherProviderError("Open-Meteo response has no hourly forecast")
    hourly = payload["hourly"]
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise WeatherProviderError("Open-Meteo response has no hourly timestamps")
    units = payload.get("hourly_units") or {}
    expected_units = {
        "precipitation": "mm",
        "precipitation_probability": "%",
        "rain": "mm",
        "weather_code": "wmo code",
    }
    for field, expected in expected_units.items():
        unit = units.get(field)
        if unit is not None and str(unit).lower() != expected:
            raise WeatherProviderError(f"Open-Meteo returned unexpected units for {field}")
        if field not in hourly or not isinstance(hourly[field], list) or len(hourly[field]) != len(times):
            raise WeatherProviderError(f"Open-Meteo response has invalid hourly {field} data")

    records = []
    for index, value in enumerate(times):
        record = {"time": _timestamp(value)}
        for field in FIELDS:
            record[field] = _number(hourly[field][index], field)
        records.append(record)
    if records != sorted(records, key=lambda item: item["time"]):
        raise WeatherProviderError("Open-Meteo hourly timestamps are not ordered")
    return records


def _fetch_chunk(points, timeout_s):
    query = urllib.parse.urlencode({
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.5f}" for _, lon in points),
        "hourly": ",".join(FIELDS),
        "forecast_days": 2,
        "timezone": "UTC",
    })
    try:
        with urllib.request.urlopen(f"{URL}?{query}", timeout=timeout_s) as response:
            payload = json.loads(response.read())
    except Exception as exc:
        raise WeatherProviderError("Open-Meteo forecast request failed") from exc
    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(points):
        raise WeatherProviderError("Open-Meteo returned a different number of locations than requested")
    return [normalize_forecast(location) for location in locations]


def fetch_forecasts(points, timeout_s=6):
    """Fetch normalized hourly forecasts in input order for (lat, lon) locations."""
    if not points:
        return []
    batches = [points[i:i + MAX_LOCATIONS_PER_REQUEST]
               for i in range(0, len(points), MAX_LOCATIONS_PER_REQUEST)]
    with ThreadPoolExecutor(max_workers=min(4, len(batches))) as executor:
        results = list(executor.map(lambda batch: _fetch_chunk(batch, timeout_s), batches))
    return [forecast for batch in results for forecast in batch]


def at_time(records, timestamp):
    """Interpolate numerical forecast values at a UTC epoch; never extrapolate over an hour."""
    if not records:
        return None
    target = datetime.fromtimestamp(timestamp, timezone.utc)
    before = next((record for record in reversed(records) if record["time"] <= target), None)
    after = next((record for record in records if record["time"] >= target), None)
    if before and after:
        span = (after["time"] - before["time"]).total_seconds()
        fraction = 0 if span == 0 else (target - before["time"]).total_seconds() / span
        values = {}
        for field in FIELDS:
            a, b = before[field], after[field]
            values[field] = (a + (b - a) * fraction) if a is not None and b is not None else (a if a is not None else b)
        return values
    nearest = before or after
    if abs((nearest["time"] - target).total_seconds()) > 3600:
        return None
    return {field: nearest[field] for field in FIELDS}
