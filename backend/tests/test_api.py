from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from tests.test_rainfall_provider import FakeResponse, _daily_payload

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["satellite_provider"] == "mock"


def test_list_districts_includes_all_v1_districts():
    resp = client.get("/districts")
    assert resp.status_code == 200
    body = resp.json()
    ids = {d["id"] for d in body}
    # IMPLEMENTATION_PLAN.md section 3 (Thatta/Sujawal kept separate — see
    # scripts/build_districts_config.py)
    assert ids == {
        "dadu", "jacobabad", "qambar_shahdadkot", "larkana", "shikarpur",
        "kashmore", "khairpur", "sukkur", "naushahro_feroze", "badin",
        "thatta", "sujawal", "dera_ghazi_khan", "rajanpur",
    }


def test_district_detail_404_for_unknown_id():
    resp = client.get("/districts/not-a-real-district")
    assert resp.status_code == 404


def test_district_detail_409_before_any_refresh():
    # "sukkur" has no risk_snapshots row yet in a freshly synced DB
    resp = client.get("/districts/sukkur")
    assert resp.status_code == 409


def _mocked_get(url, params=None, **kwargs):
    # rainfall_openmeteo and hydrology_openmeteo both `import requests` — the same
    # shared module object — so patching requests.get separately per-module collides
    # (whichever patch context is entered last silently wins for *both* modules).
    # One mock, dispatched on URL, patched once at the requests module level, avoids that.
    if "flood-api" in url:
        return FakeResponse({"daily": {"river_discharge": [100.0] * 3}})
    params = params or {}
    hourly = params.get("hourly", "")
    if "soil_moisture" in hourly:
        # hydrology_openmeteo's historical-baseline fetch (archive API, hourly)
        return FakeResponse({"hourly": {"soil_moisture_0_to_7cm": [0.15] * 3}})
    daily = params.get("daily", "")
    if "soil_moisture" in daily:
        # hydrology_openmeteo's current-value fetch (forecast API, daily)
        return FakeResponse({"daily": {"soil_moisture_0_to_10cm_mean": [0.15] * 3}})
    return FakeResponse(_daily_payload([8.0] * 7))


def test_refresh_then_detail_and_history():
    with patch("requests.get", side_effect=_mocked_get):
        resp = client.post("/districts/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["districts_processed"] == 14
    assert body["errors"] == []

    detail = client.get("/districts/sukkur")
    assert detail.status_code == 200
    d = detail.json()
    assert d["id"] == "sukkur"
    assert d["risk_level"] in {"Low", "Moderate", "High", "Severe"}
    assert 0.0 <= d["risk_score"] <= 1.0
    assert d["signals"]["water_source"] == "mock"
    assert d["signals"]["rainfall_source"] == "open_meteo"
    assert d["signals"]["soil_moisture_source"] == "open_meteo"
    assert d["signals"]["river_discharge_source"] == "open_meteo_glofas"

    history = client.get("/districts/sukkur/history?days=30")
    assert history.status_code == 200
    points = history.json()
    assert len(points) == 1
    assert points[0]["risk_score"] == d["risk_score"]

    summary = client.get("/districts").json()
    sukkur_summary = next(d for d in summary if d["id"] == "sukkur")
    assert sukkur_summary["risk_level"] == d["risk_level"]
