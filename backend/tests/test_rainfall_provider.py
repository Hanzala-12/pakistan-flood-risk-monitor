"""No live network calls — requests.get is monkeypatched so this runs in CI
with no internet access."""
import datetime
from dataclasses import dataclass
from unittest.mock import patch

from app.ingestion.rainfall_openmeteo import OpenMeteoRainfallProvider


@dataclass
class FakeDistrict:
    id: str = "dadu"
    centroid_lat: float = 26.7
    centroid_lon: float = 67.7


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _daily_payload(values):
    return {"daily": {"precipitation_sum": values}}


def test_anomaly_zero_when_at_baseline():
    provider = OpenMeteoRainfallProvider()
    with patch("app.ingestion.rainfall_openmeteo.requests.get") as mock_get:
        # 7 days at 10mm/day -> rainfall_7d = 70mm; 5 baseline years all match exactly
        mock_get.side_effect = [
            FakeResponse(_daily_payload([10.0] * 7)),
        ] + [FakeResponse(_daily_payload([10.0] * 7))] * 5

        result = provider.get_rainfall_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.rainfall_7d_mm == 70.0
    assert result.baseline_7d_mm == 70.0
    assert result.rainfall_anomaly == 0.0
    assert result.source == "open_meteo"


def test_anomaly_saturates_at_high_multiple():
    provider = OpenMeteoRainfallProvider()
    with patch("app.ingestion.rainfall_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_daily_payload([100.0] * 7)),  # 700mm in 7 days
        ] + [FakeResponse(_daily_payload([10.0 / 7] * 7))] * 5  # tiny baseline (~10mm/week)

        result = provider.get_rainfall_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.rainfall_anomaly == 1.0


def test_network_failure_falls_back_to_neutral_signal():
    import requests

    provider = OpenMeteoRainfallProvider()
    with patch("app.ingestion.rainfall_openmeteo.requests.get", side_effect=requests.RequestException("boom")):
        result = provider.get_rainfall_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.source == "open_meteo_unavailable"
    assert result.rainfall_anomaly == 0.0


def test_baseline_cache_avoids_refetching_same_week():
    provider = OpenMeteoRainfallProvider()
    with patch("app.ingestion.rainfall_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_daily_payload([5.0] * 7)),
        ] + [FakeResponse(_daily_payload([5.0] * 7))] * 5

        district = FakeDistrict()
        as_of = datetime.date(2026, 8, 15)
        provider.get_rainfall_signal(district, as_of)
        calls_after_first = mock_get.call_count

        mock_get.side_effect = [FakeResponse(_daily_payload([5.0] * 7))]
        provider.get_rainfall_signal(district, as_of)
        calls_after_second = mock_get.call_count

    # second call should only fetch the recent-7-days window (1 call), reusing the cached baseline
    assert calls_after_second - calls_after_first == 1


def test_get_rainfall_signal_uses_as_of_not_today():
    """The whole point of using the archive endpoint for the 'recent' window
    too: it must ask for days ending at `as_of`, not at today's date, so
    scripts/seed_history.py can backfill real historical rainfall."""
    provider = OpenMeteoRainfallProvider()
    captured_params = []

    def fake_get(url, params=None, timeout=None):
        captured_params.append(params)
        return FakeResponse(_daily_payload([1.0] * 7))

    with patch("app.ingestion.rainfall_openmeteo.requests.get", side_effect=fake_get):
        as_of = datetime.date(2025, 7, 1)  # far in the past relative to "today"
        provider.get_rainfall_signal(FakeDistrict(), as_of)

    recent_call = captured_params[0]
    assert recent_call["end_date"] == "2025-07-01"
    assert recent_call["start_date"] == "2025-06-25"
