"""Real rainfall ingestion via Open-Meteo — no API key or account required.

Why Open-Meteo instead of the plan's suggested NASA GPM IMERG / Google Earth
Engine (IMPLEMENTATION_PLAN.md section 6.2): both of those need a registered
account (Earthdata login, or a GCP project for GEE) before a single request
works. Open-Meteo's archive API serves real reanalysis-based precipitation
with no signup, current through today (verified at build time — it is not
delayed by the several-day lag some reanalysis products have), which is what
makes this the one ingestion signal in v1 that's live by default instead of
mocked. It's not GPM IMERG specifically, but it's real, current
precipitation data, not a placeholder — worth stating plainly in the README
rather than presenting GPM as used when it isn't.

Two kinds of calls per district:
  1. Daily precipitation for the 7 days ending on `as_of` -> the "recent
     rainfall" signal. Using the archive endpoint (rather than the forecast
     endpoint's `past_days`, which is always relative to *today*) is what
     makes `get_rainfall_signal` correct for a historical `as_of` too, so
     scripts/seed_history.py can backfill real past rainfall instead of
     today's numbers stamped onto old dates.
  2. Archive precipitation for the same week-of-year in each of the last
     `rainfall_baseline_years` years, averaged -> a seasonal baseline for
     "is this an unusual amount of rain for this place, this time of year."
     Cached in-process per (district, week) so the daily job doesn't refetch
     5 years of history for the same week every single run.
"""
import datetime
import logging
from dataclasses import dataclass

import requests

from app.config import get_settings
from app.ingestion.base import RainfallProvider, RainfallResult
from app.ingestion.baseline_store import get_cached_baseline, set_cached_baseline

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT_S = 20

# Anomaly saturates once 7-day rainfall reaches this multiple of the seasonal
# baseline — i.e. "3x the normal amount of rain for this week" already reads
# as maximally anomalous (1.0). Below baseline reads as 0. Documented
# heuristic, same spirit as the fusion weights in app/fusion/risk.py.
ANOMALY_SATURATION_MULTIPLE = 3.0
# Floor added to the baseline so districts with a near-zero dry-season
# baseline don't get a division-by-near-zero anomaly score from a trivial
# rain event.
BASELINE_FLOOR_MM = 5.0


@dataclass(frozen=True)
class _BaselineCacheKey:
    district_id: str
    week_of_year: int


class OpenMeteoRainfallProvider(RainfallProvider):
    def __init__(self):
        self._baseline_cache: dict[_BaselineCacheKey, float] = {}

    def get_rainfall_signal(self, district, as_of: datetime.date, db=None) -> RainfallResult:
        try:
            recent_daily = self._fetch_daily_precip(
                district.centroid_lat, district.centroid_lon,
                as_of - datetime.timedelta(days=6), as_of,
            )
            rainfall_3d = round(sum(recent_daily[-3:]), 1)
            rainfall_7d = round(sum(recent_daily), 1)
            baseline_7d = self._get_seasonal_baseline(district, as_of, db)
            anomaly = self._anomaly_score(rainfall_7d, baseline_7d)

            return RainfallResult(
                rainfall_anomaly=anomaly,
                rainfall_3d_mm=rainfall_3d,
                rainfall_7d_mm=rainfall_7d,
                baseline_7d_mm=baseline_7d,
                source="open_meteo",
            )
        except requests.RequestException as e:
            logger.warning("Open-Meteo request failed for %s (%s) — falling back to neutral rainfall signal.", district.id, e)
            return RainfallResult(
                rainfall_anomaly=0.0,
                rainfall_3d_mm=0.0,
                rainfall_7d_mm=0.0,
                baseline_7d_mm=0.0,
                source="open_meteo_unavailable",
            )

    @staticmethod
    def _anomaly_score(rainfall_7d: float, baseline_7d: float) -> float:
        denom = baseline_7d + BASELINE_FLOOR_MM
        ratio = rainfall_7d / denom
        # ratio of 1.0 (right at baseline) -> anomaly 0; ratio >= SATURATION -> anomaly 1.
        score = (ratio - 1.0) / (ANOMALY_SATURATION_MULTIPLE - 1.0)
        return round(max(0.0, min(1.0, score)), 3)

    def _fetch_daily_precip(self, lat: float, lon: float, start: datetime.date, end: datetime.date) -> list[float]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_sum",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "UTC",
        }
        resp = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        values = resp.json()["daily"]["precipitation_sum"]
        return [v or 0.0 for v in values]

    def _get_seasonal_baseline(self, district, as_of: datetime.date, db=None) -> float:
        settings = get_settings()
        week = as_of.isocalendar()[1]
        key = _BaselineCacheKey(district.id, week)
        if key in self._baseline_cache:
            return self._baseline_cache[key]
        cached = get_cached_baseline(db, district.id, week, "rainfall")
        if cached is not None:
            self._baseline_cache[key] = cached
            return cached

        weekly_totals = []
        for years_back in range(1, settings.rainfall_baseline_years + 1):
            year = as_of.year - years_back
            try:
                # Feb 29 has no equivalent in a non-leap year; fall back a day.
                anchor = as_of.replace(year=year)
            except ValueError:
                anchor = as_of.replace(year=year, day=28)
            start = anchor - datetime.timedelta(days=6)
            try:
                total = sum(self._fetch_daily_precip(district.centroid_lat, district.centroid_lon, start, anchor))
                weekly_totals.append(total)
            except (requests.RequestException, ValueError) as e:
                logger.warning("Baseline fetch failed for %s year %s: %s", district.id, year, e)

        baseline = round(sum(weekly_totals) / len(weekly_totals), 1) if weekly_totals else 0.0
        self._baseline_cache[key] = baseline
        if weekly_totals:  # only persist a baseline backed by at least one real year
            set_cached_baseline(db, district.id, week, "rainfall", baseline)
        return baseline
