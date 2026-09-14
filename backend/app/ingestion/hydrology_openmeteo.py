"""
Two more real, no-signup signals via Open-Meteo's forecast and flood APIs —
found by researching other open-source flood-risk projects (see README
"Data sourcing decisions") rather than guessed at independently.

**Soil moisture** — an antecedent-moisture signal. Two districts with
identical 7-day rainfall can carry very different flood risk depending on
whether the ground was already saturated from weeks of prior rain or coming
off a dry spell; this is a well-established hydrology concept (antecedent
moisture condition, part of the SCS curve-number method), and Open-Meteo
happens to serve real soil moisture directly — not something derived from
rainfall the way some other projects proxy it — so the real value is used
rather than a computed stand-in.

**River discharge** — actual GloFAS-modeled river flow (m^3/s) at each
district's calibrated discharge point (see
scripts/calibrate_discharge_points.py — querying the naive nearest-river
point reads 0.00 m^3/s even on the Indus at Sukkur; GloFAS's own channel
grid doesn't align with the HydroRIVERS centerline used for the static
terrain-proximity score elsewhere in this project, verified before writing
any of this). This is the most direct, dynamic flood indicator in the whole
system — actual water currently in the channel, not a proxy for it.

Both follow the same "current value vs. seasonal baseline" pattern as
rainfall_openmeteo.py, duplicated here rather than factored into a shared
helper — that module already has passing tests and duplicating ~30 lines
was judged lower-risk than refactoring tested code while adding two new
signals at once.
"""
import datetime
import logging
from dataclasses import dataclass

import requests

from app.config import get_settings
from app.ingestion.baseline_store import get_cached_baseline, set_cached_baseline

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
REQUEST_TIMEOUT_S = 20

# Same saturating-anomaly shape as rainfall_openmeteo.py: 1x baseline -> 0,
# >= this multiple of baseline -> 1. Documented heuristic, not fitted.
SOIL_MOISTURE_SATURATION_MULTIPLE = 1.8
RIVER_DISCHARGE_SATURATION_MULTIPLE = 3.0
BASELINE_FLOOR = 0.01  # avoids a division-by-near-zero anomaly from a trivial baseline


@dataclass
class SoilMoistureResult:
    soil_moisture_anomaly: float      # 0..1
    soil_moisture_m3m3: float          # current value, m^3/m^3 (0=dry, ~0.5=saturated)
    baseline_m3m3: float
    source: str                        # "open_meteo" | "open_meteo_unavailable" | "unavailable_no_data"


@dataclass
class RiverDischargeResult:
    river_discharge_anomaly: float    # 0..1
    river_discharge_cms: float         # current value, m^3/s
    baseline_cms: float
    source: str                        # "open_meteo_glofas" | "open_meteo_unavailable" | "unavailable_no_calibration"


@dataclass(frozen=True)
class _BaselineCacheKey:
    district_id: str
    week_of_year: int
    kind: str  # "soil" | "discharge"


class OpenMeteoHydrologyProvider:
    def __init__(self):
        self._baseline_cache: dict[_BaselineCacheKey, float] = {}

    # ---- Soil moisture ---------------------------------------------------
    def get_soil_moisture_signal(self, district, as_of: datetime.date, db=None) -> SoilMoistureResult:
        try:
            current = self._fetch_soil_moisture(district.centroid_lat, district.centroid_lon, as_of - datetime.timedelta(days=2), as_of)
            baseline = self._get_baseline(district, as_of, kind="soil", db=db,
                                           fetch_fn=lambda lat, lon, start, end: self._fetch_soil_moisture_baseline(lat, lon, start, end))
            anomaly = self._anomaly_score(current, baseline, SOIL_MOISTURE_SATURATION_MULTIPLE)
            return SoilMoistureResult(anomaly, round(current, 3), round(baseline, 3), "open_meteo")
        except requests.RequestException as e:
            logger.warning("Soil moisture request failed for %s (%s) — falling back to neutral signal.", district.id, e)
            return SoilMoistureResult(0.0, 0.0, 0.0, "open_meteo_unavailable")

    def _fetch_soil_moisture(self, lat: float, lon: float, start: datetime.date, end: datetime.date) -> float:
        """Current value — the forecast API's own recent-window soil moisture,
        real and near-real-time. This endpoint only accepts dates within
        roughly its own forecast/recent-past window (verified live: rejects
        anything before ~93 days ago with a 400), which is fine here since
        `as_of` is always "now" for this call — see `_fetch_soil_moisture_baseline`
        for the multi-year-back case, which needs a different endpoint."""
        params = {
            "latitude": lat, "longitude": lon,
            "daily": "soil_moisture_0_to_10cm_mean",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "timezone": "UTC",
        }
        resp = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        values = [v for v in resp.json()["daily"]["soil_moisture_0_to_10cm_mean"] if v is not None]
        return values[-1] if values else 0.0  # most recent day in the window

    def _fetch_soil_moisture_baseline(self, lat: float, lon: float, start: datetime.date, end: datetime.date) -> float:
        """Historical-years value for the baseline average. The forecast API
        above only serves a rolling recent window (verified live: a start_date
        from a year ago gets `400 "start_date is out of allowed range"`), so
        this queries the separate Historical Weather (ERA5-Land reanalysis)
        archive instead — the same one rainfall_openmeteo.py already uses for
        its own baseline. That archive has no daily soil-moisture aggregate
        (verified live: `daily=soil_moisture_0_to_10cm_mean` parses but always
        returns null), only hourly, and only in ERA5-Land's own depth bands
        (0-7/7-28/28-100/100-255cm, not the forecast model's 0-10cm) — so this
        is the closest available layer, not an exact match to the current-value
        fetch's depth band. Close enough for a same-shape anomaly comparison,
        not claimed to be the identical quantity."""
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "soil_moisture_0_to_7cm",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "timezone": "UTC",
        }
        resp = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        values = [v for v in resp.json()["hourly"]["soil_moisture_0_to_7cm"] if v is not None]
        return values[-1] if values else 0.0  # most recent hour in the window

    # ---- River discharge ---------------------------------------------------
    def get_river_discharge_signal(self, district, as_of: datetime.date, db=None) -> RiverDischargeResult:
        if district.discharge_query_point_lon is None or district.discharge_query_point_lat is None:
            return RiverDischargeResult(0.0, 0.0, 0.0, "unavailable_no_calibration")
        try:
            lat, lon = district.discharge_query_point_lat, district.discharge_query_point_lon
            current = self._fetch_discharge(lat, lon, as_of - datetime.timedelta(days=2), as_of)
            baseline = self._get_baseline(district, as_of, kind="discharge", db=db,
                                           fetch_fn=lambda la, lo, start, end: self._fetch_discharge(la, lo, start, end),
                                           lat=lat, lon=lon)
            anomaly = self._anomaly_score(current, baseline, RIVER_DISCHARGE_SATURATION_MULTIPLE)
            return RiverDischargeResult(anomaly, round(current, 1), round(baseline, 1), "open_meteo_glofas")
        except requests.RequestException as e:
            logger.warning("River discharge request failed for %s (%s) — falling back to neutral signal.", district.id, e)
            return RiverDischargeResult(0.0, 0.0, 0.0, "open_meteo_unavailable")

    def _fetch_discharge(self, lat: float, lon: float, start: datetime.date, end: datetime.date) -> float:
        params = {
            "latitude": lat, "longitude": lon,
            "daily": "river_discharge",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        }
        resp = requests.get(FLOOD_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        values = [v for v in resp.json()["daily"]["river_discharge"] if v is not None]
        return values[-1] if values else 0.0

    # ---- Shared helpers ---------------------------------------------------
    @staticmethod
    def _anomaly_score(current: float, baseline: float, saturation_multiple: float) -> float:
        denom = baseline + BASELINE_FLOOR
        ratio = current / denom
        score = (ratio - 1.0) / (saturation_multiple - 1.0)
        return round(max(0.0, min(1.0, score)), 3)

    def _get_baseline(self, district, as_of: datetime.date, kind: str, fetch_fn, lat=None, lon=None, db=None) -> float:
        settings = get_settings()
        week = as_of.isocalendar()[1]
        key = _BaselineCacheKey(district.id, week, kind)
        if key in self._baseline_cache:
            return self._baseline_cache[key]
        cached = get_cached_baseline(db, district.id, week, kind)
        if cached is not None:
            self._baseline_cache[key] = cached
            return cached

        query_lat = lat if lat is not None else district.centroid_lat
        query_lon = lon if lon is not None else district.centroid_lon

        samples = []
        for years_back in range(1, settings.rainfall_baseline_years + 1):
            year = as_of.year - years_back
            try:
                anchor = as_of.replace(year=year)
            except ValueError:
                anchor = as_of.replace(year=year, day=28)
            start = anchor - datetime.timedelta(days=2)
            try:
                samples.append(fetch_fn(query_lat, query_lon, start, anchor))
            except (requests.RequestException, ValueError) as e:
                logger.warning("Baseline fetch failed for %s (%s) year %s: %s", district.id, kind, year, e)

        baseline = round(sum(samples) / len(samples), 3) if samples else 0.0
        self._baseline_cache[key] = baseline
        if samples:  # only persist a baseline backed by at least one real year
            set_cached_baseline(db, district.id, week, kind, baseline)
        return baseline
