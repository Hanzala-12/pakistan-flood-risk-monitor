"""No live network calls — requests.get is monkeypatched, same pattern as
test_rainfall_provider.py."""
import datetime
from dataclasses import dataclass
from unittest.mock import patch

from app.ingestion.hydrology_openmeteo import OpenMeteoHydrologyProvider


@dataclass
class FakeDistrict:
    id: str = "sukkur"
    centroid_lat: float = 27.7
    centroid_lon: float = 68.87
    discharge_query_point_lon: float | None = 68.98
    discharge_query_point_lat: float | None = 27.95


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _soil_payload(values):
    """Current-value shape — the forecast API's daily aggregate."""
    return {"daily": {"soil_moisture_0_to_10cm_mean": values}}


def _soil_baseline_payload(values):
    """Historical-baseline shape — the archive API's hourly variable (a
    different endpoint with a different response shape than the current-value
    fetch; see hydrology_openmeteo._fetch_soil_moisture_baseline)."""
    return {"hourly": {"soil_moisture_0_to_7cm": values}}


def _discharge_payload(values):
    return {"daily": {"river_discharge": values}}


# ---- Soil moisture -----------------------------------------------------

def test_soil_moisture_anomaly_zero_at_baseline():
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_soil_payload([0.15, 0.15, 0.15])),
        ] + [FakeResponse(_soil_baseline_payload([0.15, 0.15, 0.15]))] * 5

        result = provider.get_soil_moisture_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.soil_moisture_m3m3 == 0.15
    assert result.baseline_m3m3 == 0.15
    assert result.soil_moisture_anomaly == 0.0
    assert result.source == "open_meteo"


def test_soil_moisture_anomaly_saturates_when_much_wetter_than_baseline():
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_soil_payload([0.40, 0.40, 0.40])),  # very wet
        ] + [FakeResponse(_soil_baseline_payload([0.05, 0.05, 0.05]))] * 5  # dry baseline

        result = provider.get_soil_moisture_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.soil_moisture_anomaly == 1.0


def test_soil_moisture_network_failure_falls_back_to_neutral():
    import requests
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get", side_effect=requests.RequestException("boom")):
        result = provider.get_soil_moisture_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.source == "open_meteo_unavailable"
    assert result.soil_moisture_anomaly == 0.0


# ---- River discharge -----------------------------------------------------

def test_river_discharge_anomaly_zero_at_baseline():
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_discharge_payload([5900, 5900, 5900])),
        ] + [FakeResponse(_discharge_payload([5900, 5900, 5900]))] * 5

        result = provider.get_river_discharge_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.river_discharge_cms == 5900
    assert result.baseline_cms == 5900
    assert result.river_discharge_anomaly == 0.0
    assert result.source == "open_meteo_glofas"


def test_river_discharge_anomaly_saturates_when_far_above_baseline():
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get") as mock_get:
        mock_get.side_effect = [
            FakeResponse(_discharge_payload([20000, 20000, 20000])),  # flood-level flow
        ] + [FakeResponse(_discharge_payload([2000, 2000, 2000]))] * 5  # normal baseline

        result = provider.get_river_discharge_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.river_discharge_anomaly == 1.0


def test_river_discharge_no_calibration_returns_neutral_without_network_call():
    provider = OpenMeteoHydrologyProvider()
    district = FakeDistrict(discharge_query_point_lon=None, discharge_query_point_lat=None)
    with patch("app.ingestion.hydrology_openmeteo.requests.get") as mock_get:
        result = provider.get_river_discharge_signal(district, datetime.date(2026, 8, 15))

    mock_get.assert_not_called()
    assert result.source == "unavailable_no_calibration"
    assert result.river_discharge_anomaly == 0.0


def test_river_discharge_network_failure_falls_back_to_neutral():
    import requests
    provider = OpenMeteoHydrologyProvider()
    with patch("app.ingestion.hydrology_openmeteo.requests.get", side_effect=requests.RequestException("boom")):
        result = provider.get_river_discharge_signal(FakeDistrict(), datetime.date(2026, 8, 15))

    assert result.source == "open_meteo_unavailable"
    assert result.river_discharge_anomaly == 0.0


def test_river_discharge_queries_calibrated_point_not_centroid():
    """The whole point of calibration: querying the district centroid instead of
    the calibrated river point would silently read ~0 (verified against the
    real API before building any of this — see calibrate_discharge_points.py)."""
    provider = OpenMeteoHydrologyProvider()
    captured_params = []

    def fake_get(url, params=None, timeout=None):
        captured_params.append(params)
        return FakeResponse(_discharge_payload([100, 100, 100]))

    district = FakeDistrict()
    with patch("app.ingestion.hydrology_openmeteo.requests.get", side_effect=fake_get):
        provider.get_river_discharge_signal(district, datetime.date(2026, 8, 15))

    first_call = captured_params[0]
    assert first_call["latitude"] == district.discharge_query_point_lat
    assert first_call["longitude"] == district.discharge_query_point_lon
    assert first_call["latitude"] != district.centroid_lat
